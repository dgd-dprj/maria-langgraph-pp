import pg from "pg";
import { BedrockEmbeddings } from "@langchain/aws";
import { logger } from "./logger.js";

const { Pool } = pg;

export interface FluxoParaIndexar {
  id: string;
  nome: string;
  descricao: string;
}

interface BuscaFluxos {
  buscarCandidatos(mensagem: string, k: number, catalogo: FluxoParaIndexar[]): Promise<FluxoParaIndexar[]>;
  // Issue #180 — dispara a indexação sem esperar uma busca de verdade
  // acontecer, usado pra pré-aquecer no boot do servidor. Só a variante
  // Postgres precisa disso (a em-memória já é rápida e só existe em teste).
  aquecer?(catalogo: FluxoParaIndexar[]): Promise<void>;
}

// Titan Embed Text v2 default — troca só se algum dia mudar de modelo (ver
// gerarEmbedding abaixo, mesmo padrão de BEDROCK_MODEL_ID nos outros
// módulos de IA).
const DIMENSOES = 1024;

function clienteEmbeddings(): BedrockEmbeddings {
  return new BedrockEmbeddings({
    model: process.env.BEDROCK_EMBEDDING_MODEL_ID ?? "amazon.titan-embed-text-v2:0",
    region: process.env.AWS_REGION ?? "us-east-1",
  });
}

// NODE_ENV=test nunca chama Bedrock de verdade — mesmo padrão de
// ia/extrair.ts e ia/reescrever.ts (suíte rápida, sem custo). O vetor fake
// só precisa ser CONSISTENTE pro mesmo texto (mesmo texto → mesmo vetor) —
// os testes deste módulo verificam CONTAGEM/corte de candidatos, não
// relevância semântica real (isso é comportamento de IA, não é algo pra
// unit test determinístico).
function embeddingFalso(texto: string): number[] {
  const tamanho = 16;
  const vetor = new Array(tamanho).fill(0);
  for (let i = 0; i < texto.length; i++) vetor[i % tamanho] += texto.charCodeAt(i);
  return vetor;
}

async function gerarEmbedding(texto: string): Promise<number[]> {
  if (process.env.NODE_ENV === "test") return embeddingFalso(texto);
  return clienteEmbeddings().embedQuery(texto);
}

function similaridadeCosseno(a: number[], b: number[]): number {
  let produto = 0;
  let normaA = 0;
  let normaB = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    produto += a[i] * b[i];
    normaA += a[i] * a[i];
    normaB += b[i] * b[i];
  }
  if (normaA === 0 || normaB === 0) return 0;
  return produto / (Math.sqrt(normaA) * Math.sqrt(normaB));
}

// Sem DATABASE_URL (testes) cai pra busca em memória com cosseno calculado
// em JS — mesmo padrão de criarStoreEmMemoria() (shared/atendimentosDb.ts)
// e MemorySaver (shared/checkpointer.ts). Embeddings ficam num cache local
// (Map) só pra não recalcular a cada chamada dentro do mesmo teste/processo.
function criarBuscaEmMemoria(): BuscaFluxos {
  const cache = new Map<string, number[]>();
  async function embeddingCacheado(chave: string, texto: string): Promise<number[]> {
    let vetor = cache.get(chave);
    if (!vetor) {
      vetor = await gerarEmbedding(texto);
      cache.set(chave, vetor);
    }
    return vetor;
  }
  return {
    async buscarCandidatos(mensagem, k, catalogo) {
      if (catalogo.length <= k) return catalogo;
      const embeddingMensagem = await gerarEmbedding(mensagem);
      const comSimilaridade = await Promise.all(
        catalogo.map(async (f) => ({
          fluxo: f,
          similaridade: similaridadeCosseno(embeddingMensagem, await embeddingCacheado(f.id, f.descricao)),
        }))
      );
      comSimilaridade.sort((a, b) => b.similaridade - a.similaridade);
      return comSimilaridade.slice(0, k).map((c) => c.fluxo);
    },
  };
}

// Vetores trafegam como string `'[v1,v2,...]'` + cast `::vector` — sem a
// dependência npm `pgvector` (repo pequeno, cast manual já resolve com o
// `pg` cru que o resto do projeto já usa, ver atendimentosDb.ts).
function paraLiteralVector(vetor: number[]): string {
  return `[${vetor.join(",")}]`;
}

function criarBuscaPostgres(url: string): BuscaFluxos {
  const pool = new Pool({ connectionString: url });
  const prontoPromise = (async () => {
    await pool.query(`CREATE EXTENSION IF NOT EXISTS vector`);
    await pool.query(`
      CREATE TABLE IF NOT EXISTS fluxo_embeddings (
        id TEXT PRIMARY KEY,
        nome TEXT NOT NULL,
        descricao TEXT NOT NULL,
        embedding vector(${DIMENSOES}) NOT NULL
      )
    `);
    logger.info("[embeddingsFluxos] tabela 'fluxo_embeddings' pronta (pgvector)");
  })();

  // Catálogo é estático no código (fluxos/index.ts) — indexar 1x por
  // processo (memoizado abaixo) é suficiente. Reindexação de verdade só
  // precisaria disso se o catálogo passasse a mudar em runtime sem reiniciar
  // o processo (fora de escopo aqui).
  //
  // Issue #180 — achado ao vivo: 76 fluxos indexados um por vez (loop
  // serial, um embedding Bedrock por vez) levou 56s, bloqueando a 1ª
  // requisição do orquestrador depois de cada restart do processo. Agora
  // roda em lotes concorrentes (CONCORRENCIA por vez) — não afeta o
  // resultado (cada item é independente), só o tempo total.
  const CONCORRENCIA = 10;
  let indexadoPromise: Promise<void> | undefined;
  async function indexar(catalogo: FluxoParaIndexar[]): Promise<void> {
    await prontoPromise;
    for (let i = 0; i < catalogo.length; i += CONCORRENCIA) {
      const lote = catalogo.slice(i, i + CONCORRENCIA);
      await Promise.all(
        lote.map(async (f) => {
          const vetor = await gerarEmbedding(f.descricao);
          await pool.query(
            `INSERT INTO fluxo_embeddings (id, nome, descricao, embedding)
             VALUES ($1, $2, $3, $4::vector)
             ON CONFLICT (id) DO UPDATE SET nome = $2, descricao = $3, embedding = $4::vector`,
            [f.id, f.nome, f.descricao, paraLiteralVector(vetor)]
          );
        })
      );
    }
    logger.info({ total: catalogo.length }, "[embeddingsFluxos] catálogo (re)indexado");
  }
  // Se `indexar` falhar (ex: throttling do Bedrock — mais provável agora
  // com lotes concorrentes do que era com o loop serial), reseta a promise
  // memoizada em vez de deixá-la rejeitada pra sempre — sem isso, TODA
  // chamada futura (aquecimento de boot ou requisição real) ficaria presa
  // no mesmo erro até reiniciar o processo (achado no code review da #180).
  function garantirIndexado(catalogo: FluxoParaIndexar[]): Promise<void> {
    if (!indexadoPromise) {
      indexadoPromise = indexar(catalogo).catch((err) => {
        indexadoPromise = undefined;
        throw err;
      });
    }
    return indexadoPromise;
  }

  return {
    aquecer: garantirIndexado,
    async buscarCandidatos(mensagem, k, catalogo) {
      if (catalogo.length <= k) return catalogo;
      await garantirIndexado(catalogo);
      const embeddingMensagem = paraLiteralVector(await gerarEmbedding(mensagem));
      const inicio = Date.now();
      const res = await pool.query<{ id: string; nome: string; descricao: string }>(
        `SELECT id, nome, descricao FROM fluxo_embeddings
         WHERE id = ANY($2)
         ORDER BY embedding <=> $1::vector
         LIMIT $3`,
        [embeddingMensagem, catalogo.map((f) => f.id), k]
      );
      logger.info({ candidatos: res.rows.length, tempoMs: Date.now() - inicio }, "[embeddingsFluxos] busca por similaridade concluída");
      return res.rows;
    },
  };
}

// Memoizado a nível de módulo — mesmo racional de criarCheckpointer()
// (shared/checkpointer.ts) e obterAtendimentosStore() (shared/atendimentosDb.ts).
let buscaPromise: Promise<BuscaFluxos> | undefined;

function obterBuscaFluxos(): Promise<BuscaFluxos> {
  if (!buscaPromise) {
    const url = process.env.DATABASE_URL;
    buscaPromise = Promise.resolve(url ? criarBuscaPostgres(url) : criarBuscaEmMemoria());
  }
  return buscaPromise;
}

// Ponto de entrada usado por rotas/orquestrador.ts — com poucos candidatos
// (≤ k), devolve o catálogo INTEIRO sem gastar embedding nenhum (mesmo
// comportamento de antes desta feature existir). Só busca por similaridade
// de verdade quando o catálogo cresce além de k.
export async function buscarCandidatos(mensagem: string, k: number, catalogo: FluxoParaIndexar[]): Promise<FluxoParaIndexar[]> {
  const busca = await obterBuscaFluxos();
  return busca.buscarCandidatos(mensagem, k, catalogo);
}

// Issue #180 — chamado no boot do servidor (fire-and-forget, ver
// src/server.ts) pra disparar a indexação ANTES da 1ª requisição real
// precisar dela. garantirIndexado() é memoizado por processo — se uma
// requisição real chegar antes disso terminar, ela reaproveita a MESMA
// promise em andamento, não dispara uma segunda indexação.
export async function aquecerCatalogo(catalogo: FluxoParaIndexar[]): Promise<void> {
  const busca = await obterBuscaFluxos();
  await busca.aquecer?.(catalogo);
}
