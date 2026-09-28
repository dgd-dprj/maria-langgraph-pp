import { test } from "node:test";
import assert from "node:assert/strict";
import { montarApp } from "../../app.js";
import { ID_PESSOA_PRESA } from "../index.js";

// Mecânica genérica da rota (auth, idempotência, HATEOAS, status codes) já
// está coberta em test/app.test.ts. Aqui só o que é ESPECÍFICO desse fluxo
// rodando através da camada HTTP (texto das perguntas, ordem de negócio,
// shape de metadados) — lógica pura do grafo (sem HTTP) mora em graph.test.ts
// deste mesmo diretório.

let contador = 0;
function novoChatId() {
  contador += 1;
  return `teste-pp-http-${contador}`;
}

const AUTH = { authorization: `Bearer ${process.env.API_KEY}` };
const BASE = "/atendimentos";
const FLOW_ID = ID_PESSOA_PRESA;

test("POST cria atendimento → 1ª pergunta é sim_nao sobre número do processo", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  const res = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const body = res.json();
  assert.equal(res.statusCode, 200);
  assert.equal(body.tipoResposta, "sim_nao");
  assert.deepEqual(body.opcoes, ["Sim", "Não"]);
  assert.match(body.resposta, /número do processo/);
});

// Regressão — bug real achado ao vivo 2026-08-31: a Tykhe chamando POST
// /atendimentos de novo no MESMO chatId (retry/reconexão) reiniciava a
// conversa do zero. Aqui além de idempotente (coberto genericamente em
// app.test.ts), confere que continua na pergunta CERTA pro fluxo (não só
// "não muda de status").
test("POST 2x no MESMO chatId não reinicia — continua na pergunta do RG, não volta pro início", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  await app.inject({
    method: "POST",
    url: `${BASE}/respostas`,
    payload: { chatId, resposta: "false" }, // sem processo → pula pro RG
    headers: AUTH,
  });

  const res = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const body = res.json();
  assert.equal(res.statusCode, 200);
  assert.match(body.resposta, /RG da pessoa presa/, "deveria continuar na pergunta do RG, não voltar pro início");
});

// Sem número do processo, o desfecho é handoff_humano (issue #49) — mesmo
// assim os metadados (dadosApenado/parentesco) continuam preenchidos
// normalmente, é só o status final que muda.
test("fluxo completo SEM processo: termina handoff_humano (issue #49), metadados com dadosApenado/parentesco preenchidos", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  const responder = (resposta: string) =>
    app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta }, headers: AUTH });

  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  await responder("false"); // sem processo
  await responder("11111111111"); // RG
  await responder("true"); // confirma nome
  process.env.MOCK_CLASSIFICACAO_PARENTESCO = "Amigo(a)"; // issue #17 — resposta livre classificada contra lista fechada
  await responder("amigo"); // parentesco → pausa pra CPF do assistido (issue #183)
  delete process.env.MOCK_CLASSIFICACAO_PARENTESCO;
  const res = await responder("11111111111"); // CPF (mock acha a pessoa)
  const body = res.json();

  assert.equal(res.statusCode, 200);
  assert.equal(body.status, "handoff_humano");
  assert.equal(body.metadados.motivoHandoff, "sem_numero_processo");
  assert.equal(body.metadados.parentesco, "Amigo(a)");
  // dadosApenado/dadosProcesso em metadados são um RECORTE (decisão
  // 2026-09-09) — só os campos que a outra API vai consumir, sem o
  // `encontrado`/`movimentos`/etc que sobrava exposto sem necessidade (ver
  // fluxos/pessoaPresa/api.ts::resumirDadosApenado/resumirDadosProcesso).
  assert.equal(body.metadados.dadosApenado.idPessoa, 999999, "achou a pessoa (idPessoa presente é o sinal, não tem mais `encontrado`)");
  assert.equal(body.metadados.dadosApenado.encontrado, undefined, "encontrado não deveria mais estar em metadados (só no state interno)");
  assert.equal(body.metadados.dadosApenado.tipoPreso, "CONDENADO");
  assert.equal(body.metadados.dadosApenado.regime, "SEMIABERTO");
});
