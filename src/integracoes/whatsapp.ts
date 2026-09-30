import { logger } from "../shared/logger.js";

// Issue #198 — bridge WhatsApp (Meta Cloud API) pro orquestrador, número de
// teste provisório do app Meta for Developers. Mesmo padrão de fallback dos
// outros integracoes/* (ver verde.ts): sem credencial, cai em modo mock
// (dev local) em vez de quebrar.
const WHATSAPP_API_URL = process.env.WHATSAPP_API_URL ?? "https://graph.facebook.com/v21.0";
const WHATSAPP_PHONE_NUMBER_ID = process.env.WHATSAPP_PHONE_NUMBER_ID ?? "";
const WHATSAPP_ACCESS_TOKEN = process.env.WHATSAPP_ACCESS_TOKEN ?? "";
const TIMEOUT_WHATSAPP_MS = 10_000;

// Nunca loga `texto` (pode conter nome/dado pessoal vindo do Verde) nem o
// número de destino em claro — só chatId, que já é o padrão de correlação
// do resto do sistema (CLAUDE.md: nunca logar dado sensível em texto plano).
export async function enviarMensagemWhatsapp(para: string, texto: string, chatId: string): Promise<void> {
  if (!WHATSAPP_ACCESS_TOKEN || !WHATSAPP_PHONE_NUMBER_ID) {
    logger.warn({ chatId, evento: "whatsapp_envio_mock" }, "[whatsapp] WHATSAPP_ACCESS_TOKEN/WHATSAPP_PHONE_NUMBER_ID ausente — modo mock (dev local), mensagem não enviada de verdade");
    return;
  }

  const inicio = Date.now();
  try {
    const res = await fetch(`${WHATSAPP_API_URL}/${WHATSAPP_PHONE_NUMBER_ID}/messages`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${WHATSAPP_ACCESS_TOKEN}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ messaging_product: "whatsapp", to: para, type: "text", text: { body: texto } }),
      signal: AbortSignal.timeout(TIMEOUT_WHATSAPP_MS),
    });
    const duracaoMs = Date.now() - inicio;

    if (!res.ok) {
      const corpo = await res.text();
      logger.error({ chatId, status: res.status, duracaoMs, evento: "whatsapp_envio_falhou", corpo }, "[whatsapp] envio falhou");
      return;
    }
    logger.info({ chatId, duracaoMs, evento: "whatsapp_envio_ok" }, "[whatsapp] mensagem enviada");
  } catch (erro) {
    const duracaoMs = Date.now() - inicio;
    logger.error({ chatId, duracaoMs, evento: "whatsapp_envio_erro", erro: erro instanceof Error ? erro.message : String(erro) }, "[whatsapp] erro ao enviar mensagem");
  }
}

interface MensagemRecebidaWhatsapp {
  de: string;
  texto: string;
}

// Payload real do Cloud API (webhook de mensagem) — só extrai o que
// interessa (1ª mensagem de texto do 1º entry/change). Payloads de
// status (entregue/lido) ou tipos não-texto (áudio, imagem) voltam
// undefined — bridge ignora silenciosamente (fora de escopo da v1, issue
// #198).
export function extrairMensagemWhatsapp(payload: unknown): MensagemRecebidaWhatsapp | undefined {
  const entry = (payload as { entry?: unknown[] })?.entry;
  if (!Array.isArray(entry)) return undefined;

  for (const item of entry) {
    const changes = (item as { changes?: unknown[] })?.changes;
    if (!Array.isArray(changes)) continue;

    for (const change of changes) {
      const mensagens = (change as { value?: { messages?: unknown[] } })?.value?.messages;
      if (!Array.isArray(mensagens) || mensagens.length === 0) continue;

      const mensagem = mensagens[0] as { from?: string; type?: string; text?: { body?: string } };
      if (mensagem.type !== "text" || !mensagem.from || !mensagem.text?.body) continue;

      return { de: mensagem.from, texto: mensagem.text.body };
    }
  }

  return undefined;
}
