import { randomUUID } from "node:crypto";
import type { FastifyBaseLogger, FastifyInstance } from "fastify";
import { Command } from "@langchain/langgraph";
import { buscarFluxo, ID_VIOLENCIA_DOMESTICA, type FluxoConfig } from "../fluxos/index.js";
import { obterAtendimentosStore } from "../shared/atendimentosDb.js";

// Issue #92 — SÓ no log interno (observabilidade), não no campo `status` da
// resposta HTTP (esse continua exatamente como sempre foi, contrato com a
// Tykhe intacto). "concluido" aqui cobre TANTO o statusFinal "concluido"
// QUANTO "handoff_humano" — dos 2 jeitos a conversa com o bot terminou;
// `destino` é quem diz o que aconteceu de fato. Mapeamento aberto: só
// violência doméstica tem um "agendamento" real hoje (encaminhamento
// criado no Verde) — outros fluxos concluindo com sucesso ainda não têm
// destino conhecido (fica ausente até algum fluxo novo precisar de um).
function destinoDoLog(fluxoId: string, statusFinal: string | undefined): string | undefined {
  if (statusFinal === "handoff_humano") return "atendimento_humano";
  if (statusFinal === "expirado") return "sessao_expirada";
  if (fluxoId === ID_VIOLENCIA_DOMESTICA) return "agendamento";
  return undefined;
}

// Issue #166 — TTL de inatividade. Lido a cada request (não módulo-level)
// de propósito — testes setam TTL_INATIVIDADE_HORAS=0 em process.env pra
// forçar "sempre expirado" sem esperar tempo real nem mockar Date; um const
// avaliado 1x na importação não veria essa mudança feita depois do módulo
// já carregado.
function ttlInatividadeHoras(): number {
  return Number(process.env.TTL_INATIVIDADE_HORAS ?? "24");
}

const TEXTO_CONFIRMACAO_TTL = "Já faz um tempo desde sua última mensagem. Quer continuar de onde você parou?";
const MENSAGEM_EXPIRADO =
  "Essa conversa expirou por inatividade. Pra continuar, inicie um novo atendimento.";

export interface InterruptValue {
  pergunta: string;
  tipo: string;
  opcoes?: string[];
}

interface Links {
  self: { href: string };
  responder?: { href: string; method: "POST" };
}

// Dados cross-fluxo úteis fora do state específico de cada um — hoje só
// `cpf` (decisão 2026-09-09): serve pra quem for chamar uma API do Verde
// direto (fora do fluxo) sem precisar re-perguntar o CPF que a própria
// conversa já coletou. Cresce conforme mais campos desse tipo aparecerem;
// NÃO é o mesmo que `metadados` (que é o state completo, específico de
// cada fluxo, com schema próprio em fluxos/*/api.ts).
export interface DadosColetados {
  cpf?: string;
}

export interface RespostaAtendimento {
  resposta: string;
  tipoResposta: string;
  opcoes?: string[];
  status: string;
  // sempre presente — metadados é fluxo-específico (schema diferente por
  // fluxo, ver fluxos/*/api.ts), sem isso não dá pra saber a qual fluxo ele
  // pertence quando não se sabe de antemão (ex: veio do orquestrador).
  flowId: string;
  metadados: object;
  dadosColetados: DadosColetados;
  // Só presente quando status:concluido/handoff_humano (issue #35) — soma
  // de TODOS os tokens de IA gastos nesta conversa (fluxos/*/state.ts,
  // campo tokensGastos com reducer de soma), discriminando entrada/saída
  // (issue #69) num objeto único (issue #92 — substitui os 3 campos soltos
  // anteriores). {0,0,0} quando nenhuma chamada de IA rodou de verdade,
  // nunca ausente/undefined nesse caso.
  tokensGastos?: { input: number; output: number; total: number };
  _links: Links;
}

type ValoresAtendimento = Record<string, unknown> & {
  statusFinal?: string;
  mensagemFinal?: string;
  cpf?: string;
  tokensGastos?: { input: number; output: number; total: number };
};

function montarDadosColetados(values: ValoresAtendimento): DadosColetados {
  return {
    ...(typeof values.cpf === "string" ? { cpf: values.cpf } : {}),
  };
}

// Contrato mínimo que qualquer grafo compilado do LangGraph precisa cumprir
// pra plugar nessas rotas — evita amarrar esse módulo aos generics internos
// do CompiledStateGraph (cada fluxo tem um state type diferente). Quem
// registra em fluxos/index.ts faz o cast.
export interface GrafoAtendimento {
  invoke(input: unknown, config: unknown): Promise<unknown>;
  getState(config: unknown): Promise<{
    tasks?: Array<{ interrupts?: Array<{ value: InterruptValue }> }>;
    values?: unknown;
    next?: unknown[];
  }>;
}

// Nem self nem responder carregam flowId — a tabela `atendimentos`
// (shared/atendimentosDb.ts) resolve flowId a partir do chatId sozinha, GET
// e POST /respostas não precisam mais que o cliente mande de novo.
function montarLinks(chatId: string, status: string): Links {
  const links: Links = { self: { href: `/atendimentos/${chatId}` } };
  if (status === "em_andamento") {
    links.responder = { href: `/atendimentos/respostas`, method: "POST" };
  }
  return links;
}

// Exportado — orquestrador (src/orquestrador/graph.ts) também precisa
// extrair o __interrupt__ do invoke(), mesmo mecanismo do LangGraph.
export function extrairInterruptDoInvoke(resultado: unknown): InterruptValue | undefined {
  return (resultado as { __interrupt__?: Array<{ value: InterruptValue }> }).__interrupt__?.[0]?.value;
}

const linksSchema = {
  type: "object",
  properties: {
    self: { type: "object", properties: { href: { type: "string" } } },
    responder: {
      type: "object",
      properties: { href: { type: "string" }, method: { type: "string", enum: ["POST"] } },
    },
  },
} as const;

// additionalProperties:true — o 409 de "atendimento já concluído" (ver
// POST /atendimentos/respostas) enriquece o erro com resposta/status/
// metadados/dadosColetados/flowId; sem isso o fast-json-stringify do
// Fastify DESCARTA silenciosamente qualquer campo não declarado aqui.
const erroSchema = { type: "object", properties: { erro: { type: "string" } }, additionalProperties: true } as const;

// metadados varia por fluxo — QUAL grafo (portanto qual schema exato) só se
// sabe em runtime, lendo flowId. Docs ficam genéricas aqui (não dá pra
// declarar um schema fixo por rota quando a rota atende qualquer fluxo); ver
// fluxos/*/api.ts pro shape real de cada um.
const respostaAtendimentoSchema = {
  type: "object",
  properties: {
    resposta: { type: "string", description: "Texto da pergunta (se em_andamento) ou mensagem final" },
    tipoResposta: { type: "string", enum: ["texto", "sim_nao", "opcoes"] },
    opcoes: { type: "array", items: { type: "string" } },
    status: {
      type: "string",
      enum: ["em_andamento", "concluido", "handoff_humano", "expirado"],
      description:
        "expirado (issue #166): atendimento parado por mais de TTL_INATIVIDADE_HORAS e a pessoa escolheu não continuar — precisa iniciar um novo atendimento (novo chatId) pra seguir.",
    },
    flowId: { type: "string", format: "uuid", description: "Fluxo a que esse atendimento pertence — identifica o schema de metadados" },
    metadados: {
      type: "object",
      additionalProperties: true,
      description: "Shape depende do fluxo (flowId, ver GET /fluxos) — presente em toda resposta, reflete o state coletado até agora",
    },
    dadosColetados: {
      type: "object",
      properties: { cpf: { type: "string" } },
      description: "Dados cross-fluxo já coletados (ex: CPF) — útil pra chamar Verde direto sem re-perguntar",
    },
    tokensGastos: {
      type: "object",
      properties: {
        input: { type: "number" },
        output: { type: "number" },
        total: { type: "number" },
      },
      description:
        "Tokens de IA gastos nesta conversa, discriminados (issue #69) — entrada e saída custam diferente no Bedrock. Só presente quando status:concluido/handoff_humano.",
    },
    _links: linksSchema,
  },
} as const;

const flowIdSchema = { type: "string", format: "uuid", description: "Id do fluxo — ver GET /fluxos" } as const;

const paramsComChatIdSchema = {
  type: "object",
  properties: { chatId: { type: "string" } },
  required: ["chatId"],
} as const;

// Compartilhado entre POST base, GET :chatId e POST /respostas — os 3
// terminam no MESMO shape de resposta, só muda como chegam no
// `interrupt`/`values`.
function montarRespostaAtendimento(
  fluxo: FluxoConfig,
  fluxoId: string,
  chatId: string,
  interrupt: InterruptValue | undefined,
  values: ValoresAtendimento
): RespostaAtendimento {
  // metadados e dadosColetados vão em TODA resposta agora (decisão
  // 2026-09-09) — antes só apareciam quando status !== em_andamento.
  // fluxo.extrairMetadados já é seguro de chamar com state parcial (cada
  // campo é opcional no schema de cada fluxo, ver fluxos/*/api.ts). flowId
  // também sempre presente — sem ele não dá pra saber a qual fluxo o
  // `metadados` pertence (schema difere por fluxo).
  const metadados = fluxo.extrairMetadados(values);
  const dadosColetados = montarDadosColetados(values);
  if (interrupt) {
    return {
      resposta: interrupt.pergunta,
      tipoResposta: interrupt.tipo,
      opcoes: interrupt.opcoes,
      status: "em_andamento",
      flowId: fluxoId,
      metadados,
      dadosColetados,
      _links: montarLinks(chatId, "em_andamento"),
    };
  }
  const status = values.statusFinal ?? "concluido";
  // mensagemFinal (opcional, por fluxo) sobrescreve o texto genérico — usado
  // por fluxos com mais de 1 desfecho possível de "concluido"/"handoff_humano"
  // (ex: violenciaDomestica, que tem 3 tipos de encaminhamento com mensagens
  // diferentes — ver fluxos/violenciaDomestica/graph.ts). Ausente (undefined),
  // cai no texto único fluxo.mensagemConcluido/mensagemHandoff — comportamento
  // idêntico a antes desse campo existir (pessoaPresa nunca seta isso).
  const mensagem = values.mensagemFinal ?? (status === "concluido" ? fluxo.mensagemConcluido : fluxo.mensagemHandoff);
  return {
    resposta: mensagem,
    tipoResposta: "texto",
    status,
    flowId: fluxoId,
    metadados,
    dadosColetados,
    // {0,0,0} (não undefined) quando nenhuma chamada de IA rodou de verdade
    // nesta conversa — issue #35 (entrada/saída discriminados na #69,
    // agrupados num objeto único na #92).
    tokensGastos: values.tokensGastos ?? { input: 0, output: 0, total: 0 },
    _links: montarLinks(chatId, status),
  };
}

export type ResultadoCriarAtendimento =
  | { statusCode: 400 | 409; corpo: { erro: string } }
  | { statusCode: 200; corpo: RespostaAtendimento; location: string };

// Núcleo de "criar (ou retomar) um atendimento" — extraído pra ser
// reaproveitado tanto pela criação manual (POST /atendimentos, flowId
// explícito) quanto pelo orquestrador (rotas/orquestrador.ts, flowId vem de
// classificação por IA a partir de texto livre). As duas rotas resolvem
// fluxoId de um jeito diferente, mas a partir daí o comportamento é
// idêntico — idempotência, registro na tabela chatId→flowId, tudo aqui.
export async function criarAtendimento(
  fluxo: FluxoConfig,
  fluxoId: string,
  chatIdBody: string | undefined,
  dadosConhecidos: Record<string, unknown> | undefined,
  log: FastifyBaseLogger
): Promise<ResultadoCriarAtendimento> {
  if (!chatIdBody && process.env.NODE_ENV !== "test") {
    return { statusCode: 400, corpo: { erro: "chatId obrigatório" } };
  }
  const chatIdGerado = !chatIdBody;
  const chatId = chatIdBody || randomUUID();
  if (chatIdGerado) log.warn({ fluxoId, chatId }, "chatId ausente na requisição — gerado UUID (só permitido em NODE_ENV=test)");

  // Registra chatId→flowId ANTES de tocar no grafo — se esse chatId já
  // pertence a outro flowId, 409 aqui, sem chegar perto do checkpoint (ver
  // comentário grande em registrarRotasAtendimento). Mesmo chatId+flowId de
  // novo é idempotente (ok:true), cai no fluxo normal abaixo — que já sabe
  // lidar com "chatId já existe" via getState.
  const store = await obterAtendimentosStore();
  const registro = await store.registrar(chatId, fluxoId);
  if (!registro.ok) {
    log.warn({ chatId, fluxoId, flowIdExistente: registro.flowIdExistente }, "chatId já pertence a outro flowId");
    return { statusCode: 409, corpo: { erro: `chatId já está em uso pelo flowId ${registro.flowIdExistente}` } };
  }

  // fluxoId vai junto no configurable — é isso que deixa contextoAtual()
  // (shared/contexto.ts) correlacionar os logs de dentro dos nós do grafo
  // (verde.ts/reescrever.ts/extrair.ts) com o fluxo certo, além do chatId
  // (thread_id).
  const config = { configurable: { thread_id: chatId, fluxoId } };

  // Idempotente: se esse chatId JÁ tem atendimento em andamento, devolve o
  // estado atual (igual ao GET) — NUNCA chama invoke({}) de novo. Bug real
  // achado ao vivo 2026-08-31: invoke({}) num thread_id existente reinicia
  // o grafo do zero, apagando todo o progresso da conversa se a Tykhe
  // chamar POST de novo (retry, reconexão) em vez de GET.
  const estadoAnterior = await fluxo.grafo.getState(config);
  const interruptAnterior = estadoAnterior.tasks?.[0]?.interrupts?.[0]?.value;
  const valoresAnteriores = (estadoAnterior.values ?? {}) as ValoresAtendimento;
  const jaExiste = !!interruptAnterior || Object.keys(valoresAnteriores).length > 0;

  if (jaExiste) {
    log.warn({ fluxoId, chatId }, "POST em chatId que já existe — devolvendo estado atual, sem reiniciar");
    return {
      statusCode: 200,
      location: `/atendimentos/${chatId}`,
      corpo: montarRespostaAtendimento(fluxo, fluxoId, chatId, interruptAnterior, valoresAnteriores),
    };
  }

  log.info({ fluxoId, chatId, evento: "atendimento_criado" }, "atendimento criado");
  const resultado = await fluxo.grafo.invoke(dadosConhecidos ?? {}, config);

  const interrupt = extrairInterruptDoInvoke(resultado);
  // Issue #82 — grafo padrão (fluxo planejado, issue #21) pode concluir JÁ
  // na 1ª chamada, sem interrupt nenhum — sem esse branch, esse caso ficava
  // logado como "pergunta enviada" com tudo vazio, escondendo a conclusão
  // das métricas de negócio (handoff por motivo, tokens gastos).
  //
  // Issue #90 — `evento` (valor fixo) em vez de só confiar no texto livre
  // da mensagem pra filtrar/agrupar métrica. Issue #92 — `tokensGastos`
  // como objeto único; `status`/`destino` NO LOG (não confundir com o
  // campo `status` da resposta HTTP, que continua igual pra Tykhe) —
  // "concluido" aqui cobre handoff_humano também (a conversa terminou dos
  // 2 jeitos), `destino` diz o que aconteceu de fato.
  if (interrupt) {
    const { perguntaAtualViaIA: viaIA, perguntaAtualTokensTotal: tokensGastosTotal } = resultado as {
      perguntaAtualViaIA?: boolean;
      perguntaAtualTokensTotal?: number;
    };
    log.info({ fluxoId, chatId, evento: "pergunta_enviada", status: "em_andamento", tipoResposta: interrupt.tipo, viaIA: viaIA ?? false, tokensGastosTotal }, "pergunta enviada");
  } else {
    const { statusFinal, motivoHandoff, tokensGastos } = resultado as ValoresAtendimento;
    const destino = destinoDoLog(fluxoId, statusFinal);
    log.info({ fluxoId, chatId, evento: "atendimento_finalizado", status: "concluido", destino, motivoHandoff, tokensGastos }, "atendimento finalizado");
    // Issue #83 — mesmo dado do log, gravado estruturado (colunas) pra
    // consulta SQL direta via datasource Postgres no Grafana.
    if (statusFinal) {
      await store.concluir(chatId, { statusFinal: statusFinal as "concluido" | "handoff_humano", destino, motivoHandoff: motivoHandoff as string | undefined, tokensGastos });
    }
  }

  return {
    statusCode: 200,
    location: `/atendimentos/${chatId}`,
    corpo: montarRespostaAtendimento(fluxo, fluxoId, chatId, interrupt, resultado as ValoresAtendimento),
  };
}

// Nível 3 de Richardson (HATEOAS): toda resposta carrega `_links` com as
// próximas ações válidas dado o estado ATUAL — não fixo por rota. Enquanto
// `em_andamento`, existe "responder"; concluído/handoff, só sobra "self".
//
// Rota é a MESMA pra qualquer fluxo — /atendimentos/... — flowId (uuid, ver
// fluxos/index.ts) escolhe o grafo. Só é OBRIGATÓRIO na criação (é o único
// momento em que o servidor não tem como saber sozinho qual fluxo é); GET e
// POST /respostas resolvem flowId a partir do chatId via a tabela
// `atendimentos` (shared/atendimentosDb.ts) — decisão de design 2026-09-02,
// depois de identificar que o checkpointer do LangGraph indexa só por
// thread_id=chatId, sem separar por fluxo: sem essa tabela, o mesmo chatId
// usado em 2 flowIds diferentes colidiria no mesmo checkpoint. A chave
// primária chat_id da tabela bloqueia esse caso na criação (ver 409 abaixo).
export function registrarRotasAtendimento(app: FastifyInstance): void {
  // POST /atendimentos — cria um atendimento novo (1ª pergunta do fluxo).
  // chatId vem no corpo (é a Tykhe quem atribui esse id, não nós) — SEMPRE
  // obrigatório (produção E desenvolvimento); só NODE_ENV=test relaxa (gera
  // UUID), pra facilitar teste sem inventar chatId toda hora. flowId é
  // sempre obrigatório, em qualquer ambiente.
  app.post(
    "/atendimentos",
    {
      schema: {
        tags: ["atendimentos"],
        security: [{ bearerAuth: [] }],
        summary: "Cria um atendimento novo (1ª pergunta do fluxo)",
        body: {
          type: "object",
          properties: {
            chatId: { type: "string", description: "Id atribuído pela Tykhe — obrigatório fora de NODE_ENV=test" },
            flowId: flowIdSchema,
            dadosConhecidos: {
              type: "object",
              additionalProperties: true,
              description:
                "Campos que a Tykhe já sabe sobre quem está conversando (ex: cpf, idPessoa, nome, email) — pré-preenche o state inicial do grafo pra evitar perguntar de novo o que já é conhecido. Cada fluxo só lê os campos que declara no próprio state (fluxos/<nome>/state.ts); os demais são ignorados.",
            },
          },
        },
        response: { 200: respostaAtendimentoSchema, 400: erroSchema, 404: erroSchema, 409: erroSchema },
      },
    },
    async (req, reply) => {
      const body = req.body as
        | { chatId?: string; flowId?: string; dadosConhecidos?: Record<string, unknown> }
        | undefined;

      const fluxoId = body?.flowId;
      if (!fluxoId) return reply.code(400).send({ erro: "flowId obrigatório" });
      const fluxo = await buscarFluxo(fluxoId);
      if (!fluxo) return reply.code(404).send({ erro: "fluxo não encontrado — ver GET /fluxos" });

      const resultado = await criarAtendimento(fluxo, fluxoId, body?.chatId, body?.dadosConhecidos, req.log);
      if (resultado.statusCode !== 200) return reply.code(resultado.statusCode).send(resultado.corpo);
      // 200, não 201 — a Tykhe só reconhece 200 como padrão de sucesso
      // (pedido explícito, evita trabalho extra do lado deles). Abre mão do
      // 201/Location "correto" do REST nível 3 em troca de compatibilidade
      // com o consumidor real.
      return reply.code(200).header("Location", resultado.location).send(resultado.corpo);
    }
  );

  // GET /atendimentos/:chatId — consulta o estado ATUAL, sem avançar nada
  // (não chama invoke, só lê o checkpoint). flowId vem da tabela
  // `atendimentos` a partir do chatId — 404 se esse chatId nunca foi criado.
  app.get(
    "/atendimentos/:chatId",
    {
      schema: {
        tags: ["atendimentos"],
        security: [{ bearerAuth: [] }],
        summary: "Consulta o estado atual (sem avançar o fluxo)",
        params: paramsComChatIdSchema,
        response: { 200: respostaAtendimentoSchema, 404: erroSchema },
      },
    },
    async (req, reply) => {
      const { chatId } = req.params as { chatId: string };
      const store = await obterAtendimentosStore();
      const fluxoId = await store.buscarFlowId(chatId);
      if (!fluxoId) return reply.code(404).send({ erro: "atendimento não encontrado" });
      const fluxo = await buscarFluxo(fluxoId);
      if (!fluxo) return reply.code(404).send({ erro: "fluxo não encontrado — ver GET /fluxos" });

      // fluxoId vai junto no configurable — é isso que deixa contextoAtual()
      // (shared/contexto.ts) correlacionar os logs de dentro dos nós do
      // grafo (verde.ts/reescrever.ts/extrair.ts) com o fluxo certo, além
      // do chatId (thread_id).
      const config = { configurable: { thread_id: chatId, fluxoId } };
      const estado = await fluxo.grafo.getState(config);
      const interrupt = estado.tasks?.[0]?.interrupts?.[0]?.value;
      const valores = (estado.values ?? {}) as ValoresAtendimento;
      const existe = !!interrupt || Object.keys(valores).length > 0;
      if (!existe) return reply.code(404).send({ erro: "atendimento não encontrado" });
      return montarRespostaAtendimento(fluxo, fluxoId, chatId, interrupt, valores);
    }
  );

  // POST /atendimentos/respostas — envia uma resposta, avança o fluxo.
  // chatId vai no BODY (não na URL); flowId vem da tabela `atendimentos` a
  // partir do chatId, não precisa mandar de novo. 404 se o chatId nunca foi
  // criado (nunca passou pela tabela); 409 se já existe mas não tem pergunta
  // pendente (já concluiu) — status certo em vez de só um campo `status` no
  // corpo, é a diferença entre nível 2 e nível 3 do REST.
  app.post(
    "/atendimentos/respostas",
    {
      schema: {
        tags: ["atendimentos"],
        security: [{ bearerAuth: [] }],
        summary: "Envia uma resposta, avança o fluxo pra próxima pergunta (ou conclui)",
        body: {
          type: "object",
          properties: {
            chatId: { type: "string" },
            resposta: { type: "string", description: "\"true\"/\"false\" pra sim_nao, texto livre pras demais" },
          },
        },
        response: { 200: respostaAtendimentoSchema, 400: erroSchema, 404: erroSchema, 409: erroSchema },
      },
    },
    async (req, reply) => {
      const body = req.body as { chatId?: string; resposta?: string } | undefined;

      const chatId = body?.chatId;
      if (!chatId) return reply.code(400).send({ erro: "chatId obrigatório" });
      // Issue #185 — achado ao vivo: resposta ausente/vazia virava
      // `new Command({ resume: "" })` lá embaixo (processarResposta) —
      // string vazia é falsy, LangGraph trata igual "sem resume" (mesmo bug
      // de valor falsy já documentado pro caso resume:false em
      // pessoaPresa/graph.ts) e explode um 500 cru ("Received empty Command
      // input") em vez de um 400 de validação normal.
      if (!body?.resposta) return reply.code(400).send({ erro: "resposta obrigatório" });

      const store = await obterAtendimentosStore();
      const fluxoId = await store.buscarFlowId(chatId);
      if (!fluxoId) return reply.code(404).send({ erro: "atendimento não encontrado" });
      const fluxo = await buscarFluxo(fluxoId);
      if (!fluxo) return reply.code(404).send({ erro: "fluxo não encontrado — ver GET /fluxos" });

      // fluxoId vai junto no configurable — é isso que deixa contextoAtual()
      // (shared/contexto.ts) correlacionar os logs de dentro dos nós do
      // grafo (verde.ts/reescrever.ts/extrair.ts) com o fluxo certo, além
      // do chatId (thread_id).
      const config = { configurable: { thread_id: chatId, fluxoId } };
      const estadoAnterior = await fluxo.grafo.getState(config);
      const isResuming = (estadoAnterior.next?.length ?? 0) > 0;
      const valoresAtuais = (estadoAnterior.values ?? {}) as ValoresAtendimento;

      // Issue #166 — TTL de inatividade, checado ANTES de tocar no grafo
      // (o checkpoint do LangGraph em si nunca sabe de "expirado" — isso é
      // só um controle nosso, na tabela atendimentos).
      const atividade = await store.buscarAtividade(chatId);
      if (atividade?.statusFinal === "expirado") {
        const respostaFinal = montarRespostaAtendimento(fluxo, fluxoId, chatId, undefined, { ...valoresAtuais, statusFinal: "expirado", mensagemFinal: MENSAGEM_EXPIRADO });
        return reply.code(409).send({ erro: "atendimento expirado por inatividade — inicie um novo atendimento", ...respostaFinal });
      }

      // Resposta a uma pergunta de confirmação de TTL ("quer continuar?"),
      // não a pergunta original de negócio.
      if (atividade?.aguardandoConfirmacaoTtl) {
        const quisContinuar = body?.resposta === "true";
        if (!quisContinuar) {
          await store.concluir(chatId, { statusFinal: "expirado", destino: destinoDoLog(fluxoId, "expirado") });
          req.log.info({ fluxoId, chatId, evento: "atendimento_expirado" }, "atendimento marcado como expirado — pessoa optou por recomeçar");
          const respostaFinal = montarRespostaAtendimento(fluxo, fluxoId, chatId, undefined, { ...valoresAtuais, statusFinal: "expirado", mensagemFinal: MENSAGEM_EXPIRADO });
          return respostaFinal;
        }
        // Continuar: processa a resposta ORIGINAL que ficou pendente —
        // interceptada quando a gente perguntou "quer continuar?" em vez de
        // já processar. resolverConfirmacaoTtlContinuar já limpa a flag e
        // bump atualizado_em.
        const respostaOriginal = (await store.resolverConfirmacaoTtlContinuar(chatId)) ?? "";
        req.log.info({ fluxoId, chatId, evento: "resposta_recebida" }, "resposta recebida (retomada após confirmação de TTL)");
        return processarResposta(respostaOriginal, fluxo, fluxoId, chatId);
      }

      if (!isResuming) {
        // Já concluiu — não avança nada, mas devolve os dados coletados
        // igual a um GET, pra quem bateu nesse 409 não precisar de uma 2ª
        // chamada só pra recuperar metadados/dadosColetados que já tinha.
        const respostaFinal = montarRespostaAtendimento(fluxo, fluxoId, chatId, undefined, valoresAtuais);
        return reply.code(409).send({ erro: "atendimento já foi concluído — nada esperando resposta", ...respostaFinal });
      }

      // Passou o TTL desde a última atividade de verdade — pergunta antes
      // de processar, sem perder a resposta que a pessoa mandou agora (fica
      // guardada até ela confirmar).
      const horasInativo = atividade ? (Date.now() - atividade.atualizadoEm.getTime()) / 3_600_000 : 0;
      if (horasInativo > ttlInatividadeHoras()) {
        await store.marcarAguardandoConfirmacaoTtl(chatId, body?.resposta ?? "");
        req.log.info({ fluxoId, chatId, evento: "ttl_confirmacao_solicitada", horasInativo: Math.round(horasInativo) }, "TTL de inatividade excedido — perguntando se quer continuar");
        return montarRespostaAtendimento(fluxo, fluxoId, chatId, { pergunta: TEXTO_CONFIRMACAO_TTL, tipo: "sim_nao" }, valoresAtuais);
      }

      req.log.info({ fluxoId, chatId, evento: "resposta_recebida" }, "resposta recebida");
      return processarResposta(body?.resposta ?? "", fluxo, fluxoId, chatId);

      // resume sempre como string crua — pras perguntas sim_nao, a Tykhe
      // manda literalmente "true"/"false" (não texto em português), e o nó
      // compara === "true"/normaliza. Nada de resume:boolean aqui —
      // Command({resume:false}) quebra no LangGraph. Recebe fluxo/fluxoId/
      // chatId por parâmetro (não por closure) — narrowing de "fluxo !==
      // undefined" feito mais acima não é preservado dentro de function
      // declaration aninhada pelo TS. Extraído em função porque tanto o
      // fluxo normal quanto o "confirmou continuar depois do TTL" (acima)
      // terminam no mesmo processamento, só a origem da resposta muda.
      async function processarResposta(resposta: string, fluxo: FluxoConfig, fluxoId: string, chatId: string) {
        const resultado = await fluxo.grafo.invoke(new Command({ resume: resposta }), config);
        await store.marcarAtividade(chatId);

        const interrupt = extrairInterruptDoInvoke(resultado);
        // Issue #90 — `evento` fixo. Issue #92 — `tokensGastos` como objeto
        // único; `status`/`destino` NO LOG (não confundir com o campo
        // `status` da resposta HTTP, que continua igual pra Tykhe).
        if (interrupt) {
          const { perguntaAtualViaIA: viaIA, perguntaAtualTokensTotal: tokensGastosTotal } = resultado as {
            perguntaAtualViaIA?: boolean;
            perguntaAtualTokensTotal?: number;
          };
          req.log.info(
            { fluxoId, chatId, evento: "pergunta_enviada", status: "em_andamento", tipoResposta: interrupt.tipo, viaIA: viaIA ?? false, tokensGastosTotal },
            "pergunta enviada"
          );
        } else {
          // Issue #82 — motivoHandoff/tokensGastos agora vão pro log, sem
          // isso não tinha como montar métrica de "handoff por motivo" nem
          // "tokens gastos por dia" via CloudWatch Logs Insights.
          const { statusFinal, motivoHandoff, tokensGastos } = resultado as ValoresAtendimento;
          const destino = destinoDoLog(fluxoId, statusFinal);
          req.log.info({ fluxoId, chatId, evento: "atendimento_finalizado", status: "concluido", destino, motivoHandoff, tokensGastos }, "atendimento finalizado");
          // Issue #83 — mesmo dado do log, gravado estruturado (colunas) pra
          // consulta SQL direta via datasource Postgres no Grafana.
          if (statusFinal) {
            await store.concluir(chatId, { statusFinal: statusFinal as "concluido" | "handoff_humano", destino, motivoHandoff: motivoHandoff as string | undefined, tokensGastos });
          }
        }
        return montarRespostaAtendimento(fluxo, fluxoId, chatId, interrupt, resultado as ValoresAtendimento);
      }
    }
  );
}
