import { test } from "node:test";
import assert from "node:assert/strict";
import { montarApp } from "../src/app.js";
import { extrairMensagemWhatsapp } from "../src/integracoes/whatsapp.js";
import { ID_PESSOA_PRESA } from "../src/fluxos/index.js";
import { _chatIdAtivoDeTeste, _limparConversasAtivasDeTeste } from "../src/rotas/webhookWhatsapp.js";

// Issue #198 — bridge WhatsApp (Meta Cloud API) pro orquestrador, separado
// da Tykhe. extrairMensagemWhatsapp é lógica pura (payload real do Cloud
// API); as rotas usam MOCK_CLASSIFICACAO_FLOWID (mesmo mecanismo de
// test/orquestrador.test.ts) pra não depender de Bedrock de verdade.

function payloadTexto(de: string, texto: string) {
  return {
    object: "whatsapp_business_account",
    entry: [{ id: "x", changes: [{ value: { messages: [{ from: de, id: "wamid.teste", type: "text", text: { body: texto } }] }, field: "messages" }] }],
  };
}

function payloadStatus() {
  return {
    object: "whatsapp_business_account",
    entry: [{ id: "x", changes: [{ value: { statuses: [{ id: "wamid.x", status: "delivered" }] }, field: "messages" }] }],
  };
}

test("extrairMensagemWhatsapp: mensagem de texto válida", () => {
  const resultado = extrairMensagemWhatsapp(payloadTexto("5521999990000", "oi"));
  assert.deepEqual(resultado, { de: "5521999990000", texto: "oi" });
});

test("extrairMensagemWhatsapp: payload de status (entregue/lido) → undefined", () => {
  assert.equal(extrairMensagemWhatsapp(payloadStatus()), undefined);
});

test("extrairMensagemWhatsapp: payload sem entry/changes → undefined", () => {
  assert.equal(extrairMensagemWhatsapp({}), undefined);
  assert.equal(extrairMensagemWhatsapp(null), undefined);
});

test("GET /webhook/whatsapp: verify_token correto → 200 com o challenge de volta", async () => {
  const original = process.env.WHATSAPP_VERIFY_TOKEN;
  process.env.WHATSAPP_VERIFY_TOKEN = "segredo-teste";
  try {
    const app = await montarApp();
    const res = await app.inject({ method: "GET", url: "/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=segredo-teste&hub.challenge=abc123" });
    assert.equal(res.statusCode, 200);
    assert.equal(res.body, "abc123");
  } finally {
    process.env.WHATSAPP_VERIFY_TOKEN = original;
  }
});

test("GET /webhook/whatsapp: verify_token errado → 403", async () => {
  const original = process.env.WHATSAPP_VERIFY_TOKEN;
  process.env.WHATSAPP_VERIFY_TOKEN = "segredo-teste";
  try {
    const app = await montarApp();
    const res = await app.inject({ method: "GET", url: "/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=errado&hub.challenge=abc123" });
    assert.equal(res.statusCode, 403);
  } finally {
    process.env.WHATSAPP_VERIFY_TOKEN = original;
  }
});

test("POST /webhook/whatsapp: 1ª mensagem de um número cai no orquestrador e abre atendimento novo", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWID = ID_PESSOA_PRESA;
  const numero = `test-wpp-${Date.now()}`;
  _limparConversasAtivasDeTeste();
  try {
    const app = await montarApp();
    const res = await app.inject({ method: "POST", url: "/webhook/whatsapp", payload: payloadTexto(numero, "quero saber de um parente preso") });
    assert.equal(res.statusCode, 200);
    const chatId = _chatIdAtivoDeTeste(numero);
    assert.ok(chatId?.startsWith(`whatsapp:${numero}:`), `chatId deveria ter sido registrado, veio: ${chatId}`);
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWID = original;
  }
});

test("POST /webhook/whatsapp: payload sem mensagem reconhecível (status) → 200 sem criar conversa", async () => {
  const numero = `test-wpp-status-${Date.now()}`;
  _limparConversasAtivasDeTeste();
  const app = await montarApp();
  const res = await app.inject({ method: "POST", url: "/webhook/whatsapp", payload: payloadStatus() });
  assert.equal(res.statusCode, 200);
  assert.equal(_chatIdAtivoDeTeste(numero), undefined);
});

// Achado #1 do code review: chatId fixo por número travava pra sempre
// depois de 1 atendimento concluído (409 eterno em /atendimentos/respostas).
// Aqui confirma que a 2ª mensagem, enquanto o atendimento AINDA está em
// andamento, reaproveita o MESMO chatId (não deveria reclassificar do zero).
test("POST /webhook/whatsapp: 2ª mensagem do mesmo número (atendimento ainda em andamento) reaproveita o chatId", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWID = ID_PESSOA_PRESA;
  const numero = `test-wpp-continua-${Date.now()}`;
  _limparConversasAtivasDeTeste();
  try {
    const app = await montarApp();
    const res1 = await app.inject({ method: "POST", url: "/webhook/whatsapp", payload: payloadTexto(numero, "quero saber de um parente preso") });
    assert.equal(res1.statusCode, 200);
    const chatIdAntes = _chatIdAtivoDeTeste(numero);

    const res2 = await app.inject({ method: "POST", url: "/webhook/whatsapp", payload: payloadTexto(numero, "Amigo(a)") });
    assert.equal(res2.statusCode, 200);
    const chatIdDepois = _chatIdAtivoDeTeste(numero);

    assert.equal(chatIdAntes, chatIdDepois, "chatId deveria ter sido reaproveitado — não deveria ter aberto atendimento novo nem reclassificado");
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWID = original;
  }
});

// Achado #2 do code review: 2 mensagens quase simultâneas do mesmo número
// não podem processar em paralelo (invocariam o grafo do orquestrador em
// dobro). executarSerializado garante que a 2ª só começa depois que a 1ª
// termina de gravar o chatId.
test("POST /webhook/whatsapp: 2 mensagens concorrentes do mesmo número são serializadas (só 1 chatId ativo no final)", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWID = ID_PESSOA_PRESA;
  const numero = `test-wpp-concorrente-${Date.now()}`;
  _limparConversasAtivasDeTeste();
  try {
    const app = await montarApp();
    const [resA, resB] = await Promise.all([
      app.inject({ method: "POST", url: "/webhook/whatsapp", payload: payloadTexto(numero, "quero saber de um parente preso") }),
      app.inject({ method: "POST", url: "/webhook/whatsapp", payload: payloadTexto(numero, "quero saber de um parente preso") }),
    ]);
    assert.equal(resA.statusCode, 200);
    assert.equal(resB.statusCode, 200);
    assert.ok(_chatIdAtivoDeTeste(numero), "deveria ter exatamente 1 chatId ativo pro número, sem corrida criando 2");
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWID = original;
  }
});
