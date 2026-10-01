import { test } from "node:test";
import assert from "node:assert/strict";
import { montarApp } from "../src/app.js";
import { ID_VIOLENCIA_DOMESTICA } from "../src/fluxos/index.js";

// Issue #166 — TTL de inatividade. TTL_INATIVIDADE_HORAS=0 força "sempre
// expirado" (qualquer intervalo > 0h já conta) — jeito determinístico de
// testar sem esperar tempo real nem mockar Date. Setado/restaurado em cada
// teste (afeta só a leitura feita DENTRO do handler, não módulo-level —
// ver rotas/atendimentos.ts).

const AUTH = { authorization: `Bearer ${process.env.API_KEY}` };
const BASE = "/atendimentos";
const FLOW_ID = ID_VIOLENCIA_DOMESTICA;

let contador = 0;
function novoChatId() {
  contador += 1;
  return `teste-ttl-${contador}`;
}

test("resposta dentro do TTL processa normalmente, sem pergunta de confirmação", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });

  const res = await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "true" }, headers: AUTH });
  const body = res.json();
  assert.equal(res.statusCode, 200);
  assert.notEqual(body.resposta, undefined);
  assert.doesNotMatch(body.resposta, /Já faz um tempo/);
});

test("resposta fora do TTL pergunta se quer continuar, sem processar a resposta original ainda", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });

  process.env.TTL_INATIVIDADE_HORAS = "0";
  try {
    const res = await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "true" }, headers: AUTH });
    const body = res.json();
    assert.equal(res.statusCode, 200);
    assert.equal(body.tipoResposta, "sim_nao");
    assert.match(body.resposta, /Já faz um tempo/);
  } finally {
    delete process.env.TTL_INATIVIDADE_HORAS;
  }
});

test("confirma continuar → processa a resposta original pendente, sem perdê-la", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });

  process.env.TTL_INATIVIDADE_HORAS = "0";
  const confirmacao = await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "false" }, headers: AUTH });
  assert.equal(confirmacao.json().tipoResposta, "sim_nao");
  delete process.env.TTL_INATIVIDADE_HORAS;

  // Confirma "sim" (continuar) — deve processar a resposta original
  // ("false" = não é vítima), terminando em handoff, não em outra pergunta.
  const res = await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "true" }, headers: AUTH });
  const body = res.json();
  assert.equal(res.statusCode, 200);
  assert.equal(body.status, "handoff_humano");
  assert.equal(body.metadados.motivoHandoff, "nao_e_vitima");
});

test("confirma recomeçar → status expirado, chatId fica bloqueado (409) depois", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });

  process.env.TTL_INATIVIDADE_HORAS = "0";
  await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "true" }, headers: AUTH });
  delete process.env.TTL_INATIVIDADE_HORAS;

  // Confirma "não" (recomeçar).
  const res = await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "false" }, headers: AUTH });
  const body = res.json();
  assert.equal(res.statusCode, 200);
  assert.equal(body.status, "expirado");
  assert.match(body.resposta, /inicie um novo atendimento/);

  // Qualquer resposta nova nesse mesmo chatId, depois de expirado, é 409.
  const bloqueado = await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "true" }, headers: AUTH });
  assert.equal(bloqueado.statusCode, 409);
  assert.equal(bloqueado.json().erro, "atendimento expirado por inatividade — inicie um novo atendimento");
});
