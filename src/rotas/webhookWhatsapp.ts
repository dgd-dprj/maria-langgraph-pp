import type { FastifyInstance } from "fastify";
import { grafo as grafoOrquestrador } from "../orquestrador/graph.js";
import { obterAtendimentosStore } from "../shared/atendimentosDb.js";
import { enviarMensagemWhatsapp, extrairMensagemWhatsapp, extrairStatusWhatsapp } from "../integracoes/whatsapp.js";

const PALAVRA_CHAVE_SAIR = "#sair";
const MENSAGEM_SAIU = "Conversa encerrada. Pode mandar uma mensagem nova quando quiser.";
const MENSAGEM_NADA_PARA_SAIR = "Você não tem nenhuma conversa em andamento. Pode mandar uma mensagem pra começar.";

interface CorpoRespostaAtendimento {
  resposta?: string;
  tipoResposta?: string;
  opcoes?: string[];
  status?: string;
  erro?: string;
}

function montarTextoResposta(corpo: CorpoRespostaAtendimento | undefined): string {
  if (!corpo?.resposta) return "Desculpa, tive um problema pra processar sua mensagem. Tenta de novo em instantes.";
  if ((corpo.tipoResposta === "opcoes" || corpo.tipoResposta === "sim_nao") && corpo.opcoes?.length) {
    return `${corpo.resposta}\n\n${corpo.opcoes.map((opcao) => `- ${opcao}`).join("\n")}`;
  }
  return corpo.resposta;
}

// Achado no code review da própria #198: chatId fixo (`whatsapp:${numero}`)
// deixava o número travado pra sempre depois de 1 atendimento concluído —
// /atendimentos/respostas devolve 409 pra sempre em atendimento já
// concluido/handoff_humano/expirado (rotas/atendimentos.ts), sem caminho de
// recuperação (diferente da Tykhe, que abre um chatId novo por conta
// própria). `conversasAtivas` guarda, por número, qual chatId (com sufixo
// de timestamp) está em aberto — invalidado assim que o atendimento
// conclui/faz handoff, pra próxima mensagem do mesmo número abrir uma
// conversa nova automaticamente. Em memória de propósito (é só bookkeeping
// de roteamento do bridge, não dado de negócio — reset no restart é
// aceitável: mensagem seguinte simplesmente abre atendimento novo).
const conversasAtivas = new Map<string, string>();

function obterChatIdAtivo(numero: string): string {
  const existente = conversasAtivas.get(numero);
  if (existente) return existente;
  const novo = `whatsapp:${numero}:${Date.now()}`;
  conversasAtivas.set(numero, novo);
  return novo;
}

// Mesmo code review — 2 mensagens quase simultâneas do mesmo número (comum
// em retry de webhook da própria Meta) podiam ler o MESMO estado do grafo
// do orquestrador antes da 1ª terminar de gravar, invocando o grafo em
// dobro e mandando a mesma pergunta 2x pro WhatsApp. Serializa por número —
// cada mensagem só começa a ser processada depois que a anterior do MESMO
// número terminou.
const filaPorNumero = new Map<string, Promise<unknown>>();

function executarSerializado<T>(numero: string, tarefa: () => Promise<T>): Promise<T> {
  const anterior = filaPorNumero.get(numero) ?? Promise.resolve();
  const atual = anterior.then(tarefa, tarefa);
  filaPorNumero.set(numero, atual.then(
    () => {},
    () => {}
  ));
  return atual;
}

// Só pra teste (test/webhookWhatsapp.test.ts) — mesmo padrão de
// adicionarPlanejadoDeTeste/removerPlanejadoDeTeste (fluxosPlanejadosDb.ts):
// inspecionar/resetar o Map em memória sem expor mutação de produção.
export function _chatIdAtivoDeTeste(numero: string): string | undefined {
  return conversasAtivas.get(numero);
}
export function _limparConversasAtivasDeTeste(): void {
  conversasAtivas.clear();
  filaPorNumero.clear();
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

    // Lido por request (não módulo) de propósito — permite testar com
    // process.env.WHATSAPP_VERIFY_TOKEN diferente por teste
    // (test/webhookWhatsapp.test.ts), sem custo real em produção.
    const verifyToken = process.env.WHATSAPP_VERIFY_TOKEN ?? "";
    if (verifyToken && modo === "subscribe" && token === verifyToken) {
      return reply.code(200).type("text/plain").send(challenge ?? "");
    }
    return reply.code(403).send();
  });

  app.post("/webhook/whatsapp", { schema: { hide: true } }, async (req, reply) => {
    const mensagem = extrairMensagemWhatsapp(req.body);
    if (!mensagem) {
      // Status de entrega/leitura (sent/delivered/read/failed) ou tipo não
      // suportado (áudio, imagem) — fora de escopo da v1 (issue #198), mas
      // logamos o status de entrega mesmo assim (diagnóstico ao vivo
      // 2026-09-30: "whatsapp_envio_ok" só confirma que a Graph API aceitou
      // a chamada, não que a mensagem chegou de verdade no destino).
      const status = extrairStatusWhatsapp(req.body);
      if (status) {
        req.log.info({ evento: "whatsapp_status_entrega", status: status.status, erroCodigo: status.erroCodigo, erroTitulo: status.erroTitulo }, "[whatsapp] status de entrega recebido");
      }
      return reply.code(200).send({ ok: true });
    }

    await executarSerializado(mensagem.de, async () => {
      // Palavra-chave "#sair" — único jeito de encerrar uma conversa no meio
      // (fora isso, encerramento é sempre automático: statusFinal
      // concluido/handoff_humano). Reaproveita statusFinal:"expirado" (mesmo
      // significado do TTL de inatividade, issue #166: "encerrado, próxima
      // mensagem recomeça do zero"), com destino próprio ("saida_manual")
      // pra não misturar com expiração por TTL nos dashboards. Só a bridge
      // tem isso — Tykhe não precisa, ela já controla o próprio chatId.
      if (mensagem.texto.trim().toLowerCase() === PALAVRA_CHAVE_SAIR) {
        const chatIdAtivo = conversasAtivas.get(mensagem.de);
        if (!chatIdAtivo) {
          await enviarMensagemWhatsapp(mensagem.de, MENSAGEM_NADA_PARA_SAIR, "whatsapp:sem-conversa-ativa");
          return;
        }
        const storeSaida = await obterAtendimentosStore();
        const flowIdParaEncerrar = await storeSaida.buscarFlowId(chatIdAtivo);
        // Só existe atendimento de verdade (linha em atendimentosDb) depois
        // que o orquestrador converge pra um flowId — antes disso (ainda
        // desambiguando) não tem o que marcar como concluído, só invalidar
        // a conversa ativa da bridge mesmo.
        if (flowIdParaEncerrar) {
          await storeSaida.concluir(chatIdAtivo, { statusFinal: "expirado", destino: "saida_manual" });
        }
        conversasAtivas.delete(mensagem.de);
        await enviarMensagemWhatsapp(mensagem.de, MENSAGEM_SAIU, chatIdAtivo);
        return;
      }

      const chatId = obterChatIdAtivo(mensagem.de);
      const store = await obterAtendimentosStore();
      const flowIdExistente = await store.buscarFlowId(chatId);
      const authHeader = { authorization: `Bearer ${apiKey}` };

      const respostaInjetada = flowIdExistente
        ? await app.inject({ method: "POST", url: "/atendimentos/respostas", headers: authHeader, payload: { chatId, resposta: mensagem.texto } })
        : await (async () => {
            // Sem atendimento registrado ainda — pode ser a 1ª mensagem OU
            // uma resposta a uma pergunta de desambiguação do orquestrador
            // em si (que ainda não convergiu pra um flowId). O estado do
            // PRÓPRIO grafo do orquestrador (thread_id
            // `orquestrador:${chatId}`) resolve isso sem precisar de tabela
            // própria — mesma técnica já usada em POST /atendimentos/respostas
            // (rotas/atendimentos.ts) pra saber se um fluxo está esperando
            // resume.
            const estado = await grafoOrquestrador.getState({ configurable: { thread_id: `orquestrador:${chatId}` } });
            const aguardandoDesambiguacao = (estado.next?.length ?? 0) > 0;
            const payload = aguardandoDesambiguacao ? { chatId, resposta: mensagem.texto } : { chatId, mensagem: mensagem.texto };
            return app.inject({ method: "POST", url: "/atendimentos/orquestrador", headers: authHeader, payload });
          })();

      if (respostaInjetada.statusCode !== 200) {
        req.log.error({ chatId, status: respostaInjetada.statusCode, evento: "whatsapp_bridge_erro" }, "[whatsapp] chamada interna ao atendimento falhou");
      }

      const corpo = respostaInjetada.json<CorpoRespostaAtendimento>();

      // status !== "em_andamento" (concluido/handoff_humano) — conversa
      // acabou, próxima mensagem do mesmo número deve abrir um atendimento
      // novo (achado #1 do code review da #198), nunca tentar continuar um
      // chatId já fechado (que devolveria 409 pra sempre). Mesma invalidação
      // pra qualquer erro (ex: 409 inesperado) — sempre prefere abrir
      // atendimento novo a deixar o número travado.
      if (respostaInjetada.statusCode !== 200 || corpo.status !== "em_andamento") {
        conversasAtivas.delete(mensagem.de);
      }

      await enviarMensagemWhatsapp(mensagem.de, montarTextoResposta(corpo), chatId);
    });

    return reply.code(200).send({ ok: true });
  });
}
