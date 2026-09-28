import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { Command } from "@langchain/langgraph";
import { buscarFluxo } from "../fluxos/index.js";
import { grafo as grafoOrquestrador } from "../orquestrador/graph.js";
import { criarAtendimento, extrairInterruptDoInvoke } from "./atendimentos.js";

const erroSchema = { type: "object", properties: { erro: { type: "string" } } } as const;

const respostaOrquestradorSchema = {
  type: "object",
  properties: {
    resposta: { type: "string" },
    tipoResposta: { type: "string", enum: ["texto", "sim_nao", "opcoes"] },
    opcoes: { type: "array", items: { type: "string" } },
    status: { type: "string", enum: ["em_andamento", "concluido", "handoff_humano"] },
    motivoHandoff: {
      type: "string",
      enum: ["nao_identificado"],
      description: "Só presente quando status:handoff_humano — relato não bateu com nenhum fluxo do catálogo (implementado ou planejado)",
    },
    metadados: { type: "object", additionalProperties: true },
    // dadosColetados e tokensGastosTotal também vêm no corpo (mesmo
    // montarRespostaAtendimento de rotas/atendimentos.ts) quando o
    // orquestrador entrega pra criarAtendimento — sem declarar aqui, o
    // fast-json-stringify do Fastify DESCARTA silenciosamente os campos
    // (achado ao vivo 2026-09-11, testando a issue #35: tokensGastosTotal
    // sumia da resposta só nesta rota, dadosColetados já sumia antes disso
    // também, bug pré-existente na mesma causa).
    dadosColetados: { type: "object", additionalProperties: true },
    // Mesmo motivo do comentário acima sobre dadosColetados — precisa
    // declarar aqui ou o fast-json-stringify descarta silenciosamente
    // (issue #69/#92).
    tokensGastos: {
      type: "object",
      properties: { input: { type: "number" }, output: { type: "number" }, total: { type: "number" } },
      description:
        "Tokens de IA gastos nesta conversa (classificação + desambiguação + fluxo final), discriminados — só presente quando status:concluido/handoff_humano",
    },
    flowId: {
      type: "string",
      description:
        "Fluxo escolhido — presente quando o orquestrador convergiu pra exatamente 1 fluxo (implementado de verdade ou grafo padrão de planejado, ver issue #21). AUSENTE enquanto status:em_andamento for uma pergunta de desambiguação (issue #28, ainda decidindo qual fluxo).",
    },
    _links: { type: "object", additionalProperties: true },
  },
} as const;

const MENSAGEM_NAO_IDENTIFICADO =
  "Não consegui identificar como te ajudar a partir do que você escreveu. Vou encaminhar seu atendimento pra um atendente humano confirmar.";

function respostaHandoffSemFluxo(chatId: string, motivo: "nao_identificado") {
  return {
    resposta: MENSAGEM_NAO_IDENTIFICADO,
    tipoResposta: "texto",
    status: "handoff_humano",
    motivoHandoff: motivo,
    _links: { self: { href: `/atendimentos/${chatId}` } },
  };
}

// POST /atendimentos/orquestrador — alternativa a POST /atendimentos pra
// quem NÃO sabe de antemão qual flowId usar: manda um relato livre
// (`mensagem`) em vez de `flowId`, a Maria classifica com IA qual fluxo
// atende o caso e cria o atendimento normalmente nele — dali em diante é o
// MESMO atendimento de sempre (GET/POST /atendimentos/respostas funcionam
// igual, já registrado na tabela chatId→flowId).
//
// Desde a issue #28, a classificação pode precisar de 1+ rodadas de
// desambiguação ANTES de chegar num flowId só — o orquestrador em si agora
// é um grafo com estado próprio (src/orquestrador/graph.ts), pausando com
// interrupt() igual qualquer outro fluxo. thread_id usa um prefixo
// (`orquestrador:${chatId}`) — namespace de checkpoint SEPARADO do fluxo
// real que for escolhido no final (que usa o chatId puro), pra não colidir
// checkpoint de 2 grafos diferentes no mesmo thread_id.
//
// Enquanto está desambiguando: manda `resposta` (não `mensagem`) de novo
// pra ESTA MESMA rota, com o mesmo chatId — só depois que resolve pra 1
// fluxo (ou pra "nenhum") é que aparece flowId/status concluido/handoff.
export function registrarRotaOrquestrador(app: FastifyInstance): void {
  app.post(
    "/atendimentos/orquestrador",
    {
      schema: {
        tags: ["atendimentos"],
        security: [{ bearerAuth: [] }],
        summary: "Cria um atendimento identificando o fluxo automaticamente a partir de um relato livre (com possíveis perguntas de desambiguação antes)",
        body: {
          type: "object",
          properties: {
            chatId: { type: "string", description: "Id atribuído pela Tykhe — obrigatório fora de NODE_ENV=test" },
            mensagem: { type: "string", description: "Relato livre — só na 1ª chamada, usado pra identificar qual fluxo atende o caso" },
            resposta: {
              type: "string",
              description: "Resposta a uma pergunta de desambiguação anterior — manda isso (não mensagem) enquanto status:em_andamento sem flowId",
            },
            dadosConhecidos: {
              type: "object",
              additionalProperties: true,
              description: "Mesmo campo de POST /atendimentos — só é usado se/quando um fluxo for identificado de verdade.",
            },
          },
        },
        response: { 200: respostaOrquestradorSchema, 400: erroSchema, 409: erroSchema },
      },
    },
    async (req, reply) => {
      const body = req.body as
        | { chatId?: string; mensagem?: string; resposta?: string; dadosConhecidos?: Record<string, unknown> }
        | undefined;

      // Issue #185 — resposta:"" (vazia, não só ausente) precisa barrar
      // ANTES da checagem de "algum dos dois preenchido" abaixo — senão
      // {mensagem:"x", resposta:""} passaria (mensagem preenchido) e ainda
      // cairia no branch de Command({resume:""}) mais abaixo, que o
      // LangGraph trata como "sem resume" (string vazia é falsy) e explode
      // um 500 cru em vez de um 400 de validação normal. mensagem:"" não
      // tem esse risco — vai pra um invoke() normal, não resume.
      if (body?.resposta !== undefined && body.resposta === "") {
        return reply.code(400).send({ erro: "resposta não pode ser vazia" });
      }
      if (body?.mensagem === undefined && body?.resposta === undefined) {
        return reply.code(400).send({ erro: "mensagem (1ª chamada) ou resposta (continuação de desambiguação) obrigatório" });
      }

      const chatIdBody = body?.chatId;
      if (!chatIdBody && process.env.NODE_ENV !== "test") return reply.code(400).send({ erro: "chatId obrigatório" });
      const chatId = chatIdBody || randomUUID();

      const config = { configurable: { thread_id: `orquestrador:${chatId}` } };

      const resultado =
        body?.resposta !== undefined
          ? await grafoOrquestrador.invoke(new Command({ resume: body.resposta }), config)
          : await grafoOrquestrador.invoke({ mensagem: body?.mensagem ?? "" }, config);

      const { tokensGastosRodada, tokensGastosConversa, rodada } = resultado as {
        tokensGastosRodada?: number;
        tokensGastosConversa?: { input: number; output: number; total: number };
        rodada?: number;
      };

      // Issue #90 — `evento` fixo (não só texto livre da mensagem). Issue
      // #89 — `rodada` agora vai pro log (faltava pra montar o painel de
      // rodadas de desambiguação até resolver). Issue #92 — `status`/
      // `destino` NO LOG (não confundir com o campo `status` da resposta
      // HTTP, que continua igual pra Tykhe) — "concluido" cobre qualquer
      // desfecho que termina a conversa com o bot, "atendimento_humano" é
      // o único destino conhecido nesta rota (nunca cria agendamento aqui,
      // isso só acontece dentro de um fluxo já identificado).
      const interrupt = extrairInterruptDoInvoke(resultado);
      if (interrupt) {
        req.log.info(
          { chatId, evento: "orquestrador_pergunta_enviada", status: "em_andamento", tipoResposta: interrupt.tipo, tokensGastosTotal: tokensGastosRodada, rodada },
          "orquestrador: pergunta de desambiguação enviada"
        );
        return reply.code(200).send({
          resposta: interrupt.pergunta,
          tipoResposta: interrupt.tipo,
          opcoes: interrupt.opcoes,
          status: "em_andamento",
          _links: { self: { href: `/atendimentos/${chatId}` }, responder: { href: "/atendimentos/orquestrador", method: "POST" } },
        });
      }

      const { statusFinal, flowIdEscolhido } = resultado as { statusFinal?: string; flowIdEscolhido?: string };

      if (statusFinal !== "identificado" || !flowIdEscolhido) {
        req.log.info(
          { chatId, evento: "orquestrador_finalizado_sem_fluxo", status: "concluido", destino: "atendimento_humano", tokensGastosTotal: tokensGastosRodada, rodada },
          "orquestrador: fluxo não identificado, handoff_humano direto"
        );
        return reply.code(200).send(respostaHandoffSemFluxo(chatId, "nao_identificado"));
      }

      const fluxo = await buscarFluxo(flowIdEscolhido);
      if (!fluxo) {
        // Não deveria acontecer — flowIdEscolhido só vem de candidatos do
        // catálogo (catalogoParaClassificacao, via orquestrador/graph.ts), e
        // buscarFluxo() resolve os dois casos (implementado de verdade ou
        // grafo padrão, issue #21). Cair aqui é inconsistência real entre os
        // catálogos, não um caminho esperado.
        req.log.error(
          { chatId, flowId: flowIdEscolhido, evento: "orquestrador_inconsistencia", status: "concluido", destino: "atendimento_humano" },
          "orquestrador: flowId identificado não existe em nenhum catálogo (inconsistência)"
        );
        return reply.code(200).send(respostaHandoffSemFluxo(chatId, "nao_identificado"));
      }

      // fluxo pode ser um implementado de verdade OU o grafo padrão
      // compartilhado (fluxo planejado sem código ainda, issue #21) — dali
      // em diante o tratamento é IDÊNTICO nos 2 casos, sem branch especial.
      // Sem status/destino aqui de propósito — isso não é uma CONCLUSÃO,
      // é roteamento; o fluxo escolhido vai gerar seu PRÓPRIO log de
      // "atendimento finalizado" (rotas/atendimentos.ts) quando terminar.
      req.log.info({ chatId, evento: "orquestrador_fluxo_identificado", flowId: flowIdEscolhido, tokensGastosTotal: tokensGastosRodada, rodada }, "orquestrador: fluxo identificado");
      // Repassa o total gasto ANTES de identificar o fluxo (classificação +
      // desambiguação) como ponto de partida do acumulador do fluxo
      // escolhido — sem isso o total final do chat perdia o custo da
      // triagem (issue #35). Mesmo mecanismo de dadosConhecidos já usado
      // pra pré-preencher campo respondido (criarAtendimento passa direto
      // pro state inicial do grafo).
      const dadosConhecidosComTokens = {
        ...(body?.dadosConhecidos ?? {}),
        tokensGastos: tokensGastosConversa ?? { input: 0, output: 0, total: 0 },
      };
      const resultadoAtendimento = await criarAtendimento(fluxo, flowIdEscolhido, chatId, dadosConhecidosComTokens, req.log);
      if (resultadoAtendimento.statusCode !== 200) return reply.code(resultadoAtendimento.statusCode).send(resultadoAtendimento.corpo);
      return reply.code(200).header("Location", resultadoAtendimento.location).send(resultadoAtendimento.corpo);
    }
  );
}
