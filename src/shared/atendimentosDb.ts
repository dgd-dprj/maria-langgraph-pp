import pg from "pg";
import { logger } from "./logger.js";

const { Pool } = pg;

// chatId é a chave — 1 chatId pertence a exatamente 1 flowId pra sempre (é o
// que permite GET e POST /atendimentos/respostas não precisarem de flowId
// de novo: o servidor resolve sozinho). Chave primária em chat_id também
// bloqueia a colisão que motivou essa tabela: tentar criar um atendimento
// com um chatId já usado por OUTRO flowId vira erro explícito (ver
// registrar()), em vez de dois fluxos pisando no mesmo checkpoint do
// LangGraph (que é indexado só por thread_id=chatId, sem separar por fluxo).
// Issue #83 — colunas de desfecho preenchidas na conclusão (concluir()),
// dado de negócio estruturado pra consulta SQL direta (datasource Postgres
// no Grafana), sem depender só de CloudWatch Logs Insights (issue #82).
// Mesmos campos do log "atendimento finalizado" (rotas/atendimentos.ts).
export interface ConclusaoAtendimento {
  statusFinal: "concluido" | "handoff_humano" | "expirado";
  destino?: string;
  motivoHandoff?: string;
  tokensGastos?: { input: number; output: number; total: number };
}

// Issue #166 — TTL de inatividade. `atualizadoEm` é a última vez que uma
// resposta foi PROCESSADA de verdade (não a criação — `criado_em` continua
// fixo). `aguardandoConfirmacaoTtl`/`respostaPendente` existem só entre a
// pergunta de confirmação ("quer continuar?") e a resposta a ela — fora
// dessa janela, ficam false/undefined.
export interface AtividadeAtendimento {
  atualizadoEm: Date;
  statusFinal: string | undefined;
  aguardandoConfirmacaoTtl: boolean;
  respostaPendente: string | undefined;
}

export interface AtendimentosStore {
  registrar(chatId: string, flowId: string): Promise<{ ok: true } | { ok: false; flowIdExistente: string }>;
  buscarFlowId(chatId: string): Promise<string | undefined>;
  concluir(chatId: string, dados: ConclusaoAtendimento): Promise<void>;
  buscarAtividade(chatId: string): Promise<AtividadeAtendimento | undefined>;
  marcarAtividade(chatId: string): Promise<void>;
  marcarAguardandoConfirmacaoTtl(chatId: string, respostaPendente: string): Promise<void>;
  resolverConfirmacaoTtlContinuar(chatId: string): Promise<string | undefined>;
}

interface RegistroEmMemoria {
  flowId: string;
  atualizadoEm: Date;
  statusFinal: string | undefined;
  aguardandoConfirmacaoTtl: boolean;
  respostaPendente: string | undefined;
}

// Sem DATABASE_URL (testes, que não carregam .env) cai pra um Map em
// memória — mesmo padrão de criarCheckpointer() (shared/checkpointer.ts).
// Guarda os mesmos campos de atividade/TTL do Postgres (issue #166) — testes
// de TTL usam TTL_INATIVIDADE_HORAS=0 pra forçar expiração sem mockar Date.
function criarStoreEmMemoria(): AtendimentosStore {
  const mapa = new Map<string, RegistroEmMemoria>();
  return {
    async registrar(chatId, flowId) {
      const existente = mapa.get(chatId);
      if (existente !== undefined) return existente.flowId === flowId ? { ok: true } : { ok: false, flowIdExistente: existente.flowId };
      mapa.set(chatId, { flowId, atualizadoEm: new Date(), statusFinal: undefined, aguardandoConfirmacaoTtl: false, respostaPendente: undefined });
      return { ok: true };
    },
    async buscarFlowId(chatId) {
      return mapa.get(chatId)?.flowId;
    },
    async concluir(chatId, dados) {
      const registro = mapa.get(chatId);
      if (registro) registro.statusFinal = dados.statusFinal;
    },
    async buscarAtividade(chatId) {
      const registro = mapa.get(chatId);
      if (!registro) return undefined;
      return {
        atualizadoEm: registro.atualizadoEm,
        statusFinal: registro.statusFinal,
        aguardandoConfirmacaoTtl: registro.aguardandoConfirmacaoTtl,
        respostaPendente: registro.respostaPendente,
      };
    },
    async marcarAtividade(chatId) {
      const registro = mapa.get(chatId);
      if (registro) registro.atualizadoEm = new Date();
    },
    async marcarAguardandoConfirmacaoTtl(chatId, respostaPendente) {
      const registro = mapa.get(chatId);
      if (registro) {
        registro.aguardandoConfirmacaoTtl = true;
        registro.respostaPendente = respostaPendente;
      }
    },
    async resolverConfirmacaoTtlContinuar(chatId) {
      const registro = mapa.get(chatId);
      if (!registro) return undefined;
      const pendente = registro.respostaPendente;
      registro.aguardandoConfirmacaoTtl = false;
      registro.respostaPendente = undefined;
      registro.atualizadoEm = new Date();
      return pendente;
    },
  };
}

async function criarStorePostgres(url: string): Promise<AtendimentosStore> {
  const pool = new Pool({ connectionString: url });
  await pool.query(`
    CREATE TABLE IF NOT EXISTS atendimentos (
      chat_id TEXT PRIMARY KEY,
      flow_id UUID NOT NULL,
      criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `);
  // Issue #83 — colunas de desfecho, adicionadas via ALTER (não recriação):
  // tabela já existe em prod com linhas, CREATE TABLE IF NOT EXISTS não
  // alcança colunas novas numa tabela já existente. Todas nullable — só
  // ganham valor em concluir(), continuam NULL enquanto o atendimento está
  // em andamento (é o que distingue "em andamento" de "concluído" pra quem
  // consulta via SQL direto).
  await pool.query(`
    ALTER TABLE atendimentos
      ADD COLUMN IF NOT EXISTS concluido_em TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS status_final TEXT,
      ADD COLUMN IF NOT EXISTS destino TEXT,
      ADD COLUMN IF NOT EXISTS motivo_handoff TEXT,
      ADD COLUMN IF NOT EXISTS tokens_entrada INTEGER,
      ADD COLUMN IF NOT EXISTS tokens_saida INTEGER,
      ADD COLUMN IF NOT EXISTS tokens_total INTEGER
  `);
  // Issue #166 — TTL de inatividade. atualizado_em começa igual a criado_em
  // (backfill pras linhas que já existiam) e passa a ser tocado em toda
  // resposta processada com sucesso (marcarAtividade).
  await pool.query(`
    ALTER TABLE atendimentos
      ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS aguardando_confirmacao_ttl BOOLEAN NOT NULL DEFAULT false,
      ADD COLUMN IF NOT EXISTS resposta_pendente_ttl TEXT
  `);
  // Bug real achado ao vivo (2026-09-25, testando a issue #171 contra Verde
  // homolog de verdade): ADD COLUMN IF NOT EXISTS sem DEFAULT só preenche
  // atualizado_em nas linhas JÁ existentes (via o UPDATE de backfill
  // abaixo) — toda linha NOVA inserida por registrar() (sem essa coluna no
  // INSERT) ficava com atualizado_em NULL, e `.getTime()` em rotas/
  // atendimentos.ts quebrava com "Cannot read properties of null" na
  // primeira resposta de qualquer atendimento criado depois da migração.
  // SET DEFAULT é idempotente — seguro rodar em toda inicialização.
  await pool.query(`ALTER TABLE atendimentos ALTER COLUMN atualizado_em SET DEFAULT now()`);
  await pool.query(`UPDATE atendimentos SET atualizado_em = criado_em WHERE atualizado_em IS NULL`);
  logger.info("[atendimentosDb] tabela 'atendimentos' pronta (Postgres)");

  return {
    async registrar(chatId, flowId) {
      // ON CONFLICT DO NOTHING + RETURNING: se inseriu, rowCount>0 (era novo).
      // Se não inseriu (já existia), busca o flow_id real pra comparar —
      // mesmo chatId+flowId de novo é idempotente (ok), chatId com OUTRO
      // flowId é o conflito que essa tabela existe pra pegar.
      const inserido = await pool.query<{ flow_id: string }>(
        `INSERT INTO atendimentos (chat_id, flow_id) VALUES ($1, $2)
         ON CONFLICT (chat_id) DO NOTHING
         RETURNING flow_id`,
        [chatId, flowId]
      );
      if ((inserido.rowCount ?? 0) > 0) return { ok: true };
      const existente = await pool.query<{ flow_id: string }>(`SELECT flow_id FROM atendimentos WHERE chat_id = $1`, [chatId]);
      const flowIdExistente = existente.rows[0]?.flow_id ?? flowId;
      return flowIdExistente === flowId ? { ok: true } : { ok: false, flowIdExistente };
    },
    async buscarFlowId(chatId) {
      const res = await pool.query<{ flow_id: string }>(`SELECT flow_id FROM atendimentos WHERE chat_id = $1`, [chatId]);
      return res.rows[0]?.flow_id;
    },
    async concluir(chatId, dados) {
      await pool.query(
        `UPDATE atendimentos
         SET concluido_em = now(), status_final = $2, destino = $3, motivo_handoff = $4,
             tokens_entrada = $5, tokens_saida = $6, tokens_total = $7
         WHERE chat_id = $1`,
        [
          chatId,
          dados.statusFinal,
          dados.destino ?? null,
          dados.motivoHandoff ?? null,
          dados.tokensGastos?.input ?? null,
          dados.tokensGastos?.output ?? null,
          dados.tokensGastos?.total ?? null,
        ]
      );
    },
    async buscarAtividade(chatId) {
      const res = await pool.query<{
        atualizado_em: Date;
        status_final: string | null;
        aguardando_confirmacao_ttl: boolean;
        resposta_pendente_ttl: string | null;
      }>(
        `SELECT atualizado_em, status_final, aguardando_confirmacao_ttl, resposta_pendente_ttl
         FROM atendimentos WHERE chat_id = $1`,
        [chatId]
      );
      const linha = res.rows[0];
      if (!linha) return undefined;
      return {
        atualizadoEm: linha.atualizado_em,
        statusFinal: linha.status_final ?? undefined,
        aguardandoConfirmacaoTtl: linha.aguardando_confirmacao_ttl,
        respostaPendente: linha.resposta_pendente_ttl ?? undefined,
      };
    },
    async marcarAtividade(chatId) {
      await pool.query(`UPDATE atendimentos SET atualizado_em = now() WHERE chat_id = $1`, [chatId]);
    },
    async marcarAguardandoConfirmacaoTtl(chatId, respostaPendente) {
      await pool.query(
        `UPDATE atendimentos SET aguardando_confirmacao_ttl = true, resposta_pendente_ttl = $2 WHERE chat_id = $1`,
        [chatId, respostaPendente]
      );
    },
    async resolverConfirmacaoTtlContinuar(chatId) {
      const res = await pool.query<{ resposta_pendente_ttl: string | null }>(
        `UPDATE atendimentos
         SET aguardando_confirmacao_ttl = false, resposta_pendente_ttl = NULL, atualizado_em = now()
         WHERE chat_id = $1
         RETURNING resposta_pendente_ttl`,
        [chatId]
      );
      return res.rows[0]?.resposta_pendente_ttl ?? undefined;
    },
  };
}

// Memoizado a nível de módulo — mesmo racional de criarCheckpointer()
// (shared/checkpointer.ts): 1 pool compartilhado por processo.
let storePromise: Promise<AtendimentosStore> | undefined;

export function obterAtendimentosStore(): Promise<AtendimentosStore> {
  if (!storePromise) {
    const url = process.env.DATABASE_URL;
    storePromise = url ? criarStorePostgres(url) : Promise.resolve(criarStoreEmMemoria());
  }
  return storePromise;
}
