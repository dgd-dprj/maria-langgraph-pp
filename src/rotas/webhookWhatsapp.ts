import type { FastifyInstance } from "fastify";
import { grafo as grafoOrquestrador } from "../orquestrador/graph.js";
import { obterAtendimentosStore } from "../shared/atendimentosDb.js";
import { enviarMensagemWhatsapp, extrairMensagemWhatsapp } from "../integracoes/whatsapp.js";

const WHATSAPP_VERIFY_TOKEN = process.env.WHATSAPP_VERIFY_TOKEN ?? "";

interface CorpoRespostaAtendimento {
  resposta?: string;
  tipoResposta?: string;
  opcoes?: string[];
  erro?: string;
}

function montarTextoResposta(corpo: CorpoRespostaAtendimento | undefined): string {
  if (!corpo?.resposta) return "Desculpa, tive um problema pra processar sua mensagem. Tenta de novo em instantes.";
  if ((corpo.tipoResposta === "opcoes" || corpo.tipoResposta === "sim_nao") && corpo.opcoes?.length) {
    return `${corpo.resposta}\n\n${corpo.opcoes.map((opcao) => `- ${opcao}`).join("\n")}`;
  }
  return corpo.resposta;
}

// Issue #198 — bridge WhatsApp (Meta Cloud API) pro orquestrador, integração
// SEPARADA da Tykhe: fala só com POST /atendimentos/orquestrador e
// POST /atendimentos/respostas (via app.inject — mesmo processo, sem HTTP de
// verdade), nunca reaproveitando nem alterando o caminho que a Tykhe usa.
// Público (fora do bloco protegido por Bearer em app.ts) porque é a Meta
// quem chama, não um cliente autenticado nosso — a autenticação aqui é o
// próprio verify_token na verificação inicial do webhook.
export function registrarRotaWebhookWhatsapp(app: FastifyInstance, apiKey: string): void {
  app.get("/webhook/whatsapp", { schema: { hide: true } }, async (req, reply) => {
    const query = req.query as Record<string, string | undefined>;
    const modo = query["hub.mode"];
    const token = query["hub.verify_token"];
    const challenge = query["hub.challenge"];

    if (WHATSAPP_VERIFY_TOKEN && modo === "subscribe" && token === WHATSAPP_VERIFY_TOKEN) {
      return reply.code(200).type("text/plain").send(challenge ?? "");
    }
    return reply.code(403).send();
  });

  app.post("/webhook/whatsapp", { schema: { hide: true } }, async (req, reply) => {
    const mensagem = extrairMensagemWhatsapp(req.body);
    if (!mensagem) {
      // Status de entrega/leitura ou tipo não suportado (áudio, imagem) —
      // fora de escopo da v1 (issue #198). Meta só precisa de 200 pra não
      // reenviar o mesmo webhook.
      return reply.code(200).send({ ok: true });
    }

    const chatId = `whatsapp:${mensagem.de}`;
    const store = await obterAtendimentosStore();
    const flowIdExistente = await store.buscarFlowId(chatId);
    const authHeader = { authorization: `Bearer ${apiKey}` };

    const respostaInjetada = flowIdExistente
      ? await app.inject({ method: "POST", url: "/atendimentos/respostas", headers: authHeader, payload: { chatId, resposta: mensagem.texto } })
      : await (async () => {
          // Sem atendimento registrado ainda — pode ser a 1ª mensagem OU uma
          // resposta a uma pergunta de desambiguação do orquestrador em si
          // (que ainda não convergiu pra um flowId). O estado do PRÓPRIO
          // grafo do orquestrador (thread_id `orquestrador:${chatId}`)
          // resolve isso sem precisar de tabela própria — mesma técnica já
          // usada em POST /atendimentos/respostas (rotas/atendimentos.ts)
          // pra saber se um fluxo está esperando resume.
          const estado = await grafoOrquestrador.getState({ configurable: { thread_id: `orquestrador:${chatId}` } });
          const aguardandoDesambiguacao = (estado.next?.length ?? 0) > 0;
          const payload = aguardandoDesambiguacao ? { chatId, resposta: mensagem.texto } : { chatId, mensagem: mensagem.texto };
          return app.inject({ method: "POST", url: "/atendimentos/orquestrador", headers: authHeader, payload });
        })();

    if (respostaInjetada.statusCode !== 200) {
      req.log.error({ chatId, status: respostaInjetada.statusCode, evento: "whatsapp_bridge_erro" }, "[whatsapp] chamada interna ao atendimento falhou");
    }

    const corpo = respostaInjetada.json<CorpoRespostaAtendimento>();
    await enviarMensagemWhatsapp(mensagem.de, montarTextoResposta(corpo), chatId);

    return reply.code(200).send({ ok: true });
  });
}
