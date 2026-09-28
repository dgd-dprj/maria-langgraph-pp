import { test } from "node:test";
import assert from "node:assert/strict";
import { montarApp } from "../src/app.js";
import { ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA } from "../src/fluxos/index.js";

// Issue #117 — a Tykhe consome o fluxo JSON dela própria (fora deste repo)
// decidindo o que fazer a partir de `status`/`tipoResposta`/`opcoes`/
// `resposta`/`_links`. Testes de cada fluxo (graph.test.ts/http.test.ts)
// cobrem a LÓGICA de negócio, mas nada garantia que esses campos
// específicos continuassem existindo com o shape certo — uma renomeação
// de campo passaria no resto do CI e só quebraria a Tykhe em produção
// (quase aconteceu investigando a issue #108: o bug real era outro, mas
// evidenciou que ninguém tinha um teste olhando pro contrato em si).
// Cobre só o "envelope" comum aos dois fluxos — schema de `metadados` (que
// difere por fluxo) já é testado nos http.test.ts de cada um.

let contador = 0;
function novoChatId(prefixo: string) {
  contador += 1;
  return `teste-contrato-${prefixo}-${contador}`;
}

const AUTH = { authorization: `Bearer ${process.env.API_KEY}` };
const BASE = "/atendimentos";

function assertContratoTykhe(body: Record<string, unknown>, contexto: string) {
  assert.equal(typeof body.status, "string", `${contexto}: status deveria ser string`);
  assert.ok(
    ["em_andamento", "concluido", "handoff_humano"].includes(body.status as string),
    `${contexto}: status "${body.status}" fora do contrato conhecido pela Tykhe`
  );
  assert.equal(typeof body.flowId, "string", `${contexto}: flowId deveria ser string`);
  assert.equal(typeof body.metadados, "object", `${contexto}: metadados deveria existir (mesmo vazio)`);
  assert.equal(typeof body.dadosColetados, "object", `${contexto}: dadosColetados deveria existir (mesmo vazio)`);
  assert.equal(typeof body._links, "object", `${contexto}: _links deveria existir (HATEOAS)`);
  const links = body._links as Record<string, unknown>;
  assert.equal(typeof links.self, "object", `${contexto}: _links.self deveria existir`);
  assert.equal(typeof (links.self as Record<string, unknown>).href, "string", `${contexto}: _links.self.href deveria ser string`);

  if (body.status === "em_andamento") {
    assert.equal(typeof body.resposta, "string", `${contexto}: resposta (texto da pergunta) deveria ser string`);
    assert.ok(
      ["sim_nao", "texto"].includes(body.tipoResposta as string),
      `${contexto}: tipoResposta "${body.tipoResposta}" fora do contrato conhecido pela Tykhe`
    );
    assert.equal(typeof links.responder, "object", `${contexto}: em_andamento deveria ter _links.responder`);
    assert.equal((links.responder as Record<string, unknown>).method, "POST", `${contexto}: _links.responder.method deveria ser POST`);
    if (body.tipoResposta === "sim_nao") {
      assert.ok(Array.isArray(body.opcoes), `${contexto}: tipoResposta sim_nao deveria vir com opcoes (array)`);
      for (const opcao of body.opcoes as unknown[]) {
        assert.equal(typeof opcao, "string", `${contexto}: cada opção deveria ser string`);
      }
    }
  } else {
    assert.equal(links.responder, undefined, `${contexto}: atendimento concluído/handoff não deveria ter _links.responder`);
  }
}

test("contrato Tykhe — pessoa presa, 1ª pergunta (em_andamento, sim_nao)", async () => {
  const app = await montarApp();
  const chatId = novoChatId("pp");
  const res = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: ID_PESSOA_PRESA }, headers: AUTH });
  assert.equal(res.statusCode, 200);
  assertContratoTykhe(res.json(), "pessoa presa, 1ª pergunta");
});

test("contrato Tykhe — pessoa presa, concluído (handoff sem processo)", async () => {
  const app = await montarApp();
  const chatId = novoChatId("pp-fim");
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: ID_PESSOA_PRESA }, headers: AUTH });
  await app.inject({ method: "POST", url: "/atendimentos/respostas", payload: { chatId, resposta: "false" }, headers: AUTH }); // sem processo
  await app.inject({ method: "POST", url: "/atendimentos/respostas", payload: { chatId, resposta: "11111111111" }, headers: AUTH }); // rg (mock acha)
  await app.inject({ method: "POST", url: "/atendimentos/respostas", payload: { chatId, resposta: "true" }, headers: AUTH }); // confirma nome
  await app.inject({ method: "POST", url: "/atendimentos/respostas", payload: { chatId, resposta: "mae" }, headers: AUTH }); // parentesco → pausa pra CPF (issue #183)
  const res = await app.inject({ method: "POST", url: "/atendimentos/respostas", payload: { chatId, resposta: "11111111111" }, headers: AUTH }); // cpf (mock acha)
  assert.equal(res.statusCode, 200);
  const body = res.json();
  assert.equal(body.status, "handoff_humano");
  assertContratoTykhe(body, "pessoa presa, concluído");
});

test("contrato Tykhe — violência doméstica, 1ª pergunta (em_andamento, sim_nao)", async () => {
  const app = await montarApp();
  const chatId = novoChatId("vd");
  const res = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: ID_VIOLENCIA_DOMESTICA }, headers: AUTH });
  assert.equal(res.statusCode, 200);
  assertContratoTykhe(res.json(), "violência doméstica, 1ª pergunta");
});

test("contrato Tykhe — violência doméstica, concluído (handoff não é vítima)", async () => {
  const app = await montarApp();
  const chatId = novoChatId("vd-fim");
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: ID_VIOLENCIA_DOMESTICA }, headers: AUTH });
  const res = await app.inject({ method: "POST", url: "/atendimentos/respostas", payload: { chatId, resposta: "false" }, headers: AUTH }); // não é vítima
  assert.equal(res.statusCode, 200);
  const body = res.json();
  assert.equal(body.status, "handoff_humano");
  assertContratoTykhe(body, "violência doméstica, concluído");
});
