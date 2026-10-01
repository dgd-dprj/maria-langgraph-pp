import { test } from "node:test";
import assert from "node:assert/strict";
import { montarApp } from "../src/app.js";
import { ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA } from "../src/fluxos/index.js";

// Testa a MECÂNICA genérica das rotas (rotas/atendimentos.ts + rotas/fluxos.ts)
// — auth, health, idempotência, status codes, HATEOAS — sem acoplar em texto
// de negócio de nenhum fluxo específico. Teste de conteúdo/pergunta de cada
// fluxo mora em fluxos/<nome>/http.test.ts.
//
// violência doméstica é o fluxo mais simples de terminar (1 resposta já
// encerra pelo caminho "não é vítima") — usado aqui como fixture, só pra ter
// ALGUM grafo real rodando por trás.
//
// flowId só é obrigatório na CRIAÇÃO (POST /atendimentos) — GET e POST
// /atendimentos/respostas resolvem flowId a partir do chatId sozinhos, via a
// tabela `atendimentos` (shared/atendimentosDb.ts). Ver decisão de design em
// rotas/atendimentos.ts.

let contador = 0;
function novoChatId() {
  contador += 1;
  return `teste-app-${contador}`;
}

const AUTH = { authorization: `Bearer ${process.env.API_KEY}` };
const BASE = "/atendimentos";
const FLOW_ID = ID_VIOLENCIA_DOMESTICA;

test("POST /atendimentos sem Authorization → 401", async () => {
  const app = await montarApp();
  const res = await app.inject({ method: "POST", url: BASE, payload: { flowId: FLOW_ID } });
  assert.equal(res.statusCode, 401);
});

test("POST /atendimentos com chave errada → 401", async () => {
  const app = await montarApp();
  const res = await app.inject({
    method: "POST",
    url: BASE,
    payload: { flowId: FLOW_ID },
    headers: { authorization: "Bearer chave-errada" },
  });
  assert.equal(res.statusCode, 401);
});

test("GET /health não exige Authorization (health check do ALB não manda header)", async () => {
  const app = await montarApp();
  const res = await app.inject({ method: "GET", url: "/health" });
  assert.equal(res.statusCode, 200);
});

test("GET /fluxos lista pessoa-presa e violencia-domestica com seus ids", async () => {
  const app = await montarApp();
  const res = await app.inject({ method: "GET", url: "/fluxos", headers: AUTH });
  assert.equal(res.statusCode, 200);
  const body = res.json() as Array<{ id: string; nome: string }>;
  assert.deepEqual(
    body.map((f) => f.id).sort(),
    [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA].sort()
  );
  assert.ok(body.find((f) => f.id === ID_PESSOA_PRESA)?.nome === "pessoa-presa");
});

test("POST /atendimentos sem flowId → 400", async () => {
  const app = await montarApp();
  const res = await app.inject({ method: "POST", url: BASE, payload: { chatId: novoChatId() }, headers: AUTH });
  assert.equal(res.statusCode, 400);
});

test("POST /atendimentos com flowId desconhecido → 404", async () => {
  const app = await montarApp();
  const res = await app.inject({
    method: "POST",
    url: BASE,
    payload: { chatId: novoChatId(), flowId: "00000000-0000-0000-0000-000000000000" },
    headers: AUTH,
  });
  assert.equal(res.statusCode, 404);
});

// chatId é obrigatório SEMPRE (produção e desenvolvimento) — só NODE_ENV=test
// relaxa isso (gera UUID), pra facilitar teste sem precisar inventar chatId
// toda hora. Rodando via `pnpm test`, NODE_ENV já vem "test" (ver package.json).
test("POST /atendimentos sem chatId, NODE_ENV=test → 200 com UUID gerado, não rejeita com 400", async () => {
  const app = await montarApp();
  const res = await app.inject({ method: "POST", url: BASE, payload: { flowId: FLOW_ID }, headers: AUTH });
  assert.equal(res.statusCode, 200);
  assert.equal(res.json().status, "em_andamento");
});

test("POST /atendimentos sem chatId, FORA de NODE_ENV=test → 400 (obrigatório de verdade)", async () => {
  const original = process.env.NODE_ENV;
  process.env.NODE_ENV = "development";
  try {
    const app = await montarApp();
    const res = await app.inject({ method: "POST", url: BASE, payload: { flowId: FLOW_ID }, headers: AUTH });
    assert.equal(res.statusCode, 400);
  } finally {
    process.env.NODE_ENV = original;
  }
});

test("POST /atendimentos → 200, Location aponta pro recurso criado, _links.responder presente", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  const res = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const body = res.json();
  assert.equal(res.statusCode, 200);
  assert.equal(res.headers.location, `/atendimentos/${chatId}`);
  assert.equal(body.status, "em_andamento");
  assert.equal(body._links.self.href, `/atendimentos/${chatId}`);
  assert.equal(body._links.responder.href, `/atendimentos/respostas`);
  assert.equal(body._links.responder.method, "POST");
});

// metadados/dadosColetados presentes em TODA resposta, inclusive
// em_andamento (decisão 2026-09-09) — antes só apareciam no fim do fluxo.
test("POST /atendimentos → metadados e dadosColetados presentes mesmo em_andamento", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  const res = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const body = res.json();
  assert.equal(body.status, "em_andamento");
  assert.equal(typeof body.metadados, "object");
  assert.equal(typeof body.dadosColetados, "object");
  assert.equal(body.dadosColetados.cpf, undefined, "cpf ainda não foi coletado nesse ponto");
});

// flowId sempre presente na resposta (decisão 2026-09-09) — sem ele não dá
// pra saber a qual fluxo o `metadados` pertence (schema difere por fluxo),
// principalmente relevante pra quem chega via orquestrador sem saber de
// antemão qual fluxo foi escolhido.
test("flowId presente em toda resposta: criação, GET e respostas", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  const criado = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  assert.equal(criado.json().flowId, FLOW_ID);

  const get = await app.inject({ method: "GET", url: `${BASE}/${chatId}`, headers: AUTH });
  assert.equal(get.json().flowId, FLOW_ID);

  const resposta = await app.inject({
    method: "POST",
    url: `${BASE}/respostas`,
    payload: { chatId, resposta: "false" },
    headers: AUTH,
  });
  assert.equal(resposta.json().flowId, FLOW_ID);
});

// A tabela chatId→flowId (shared/atendimentosDb.ts) é o que existe pra
// bloquear isso — sem ela, o mesmo chatId em 2 flowIds colidiria no mesmo
// checkpoint do LangGraph (indexado só por thread_id).
test("POST /atendimentos com MESMO chatId de outro flowId → 409, não cria nem pisa no estado do outro fluxo", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  const primeiro = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: ID_VIOLENCIA_DOMESTICA }, headers: AUTH });
  assert.equal(primeiro.statusCode, 200);

  const segundo = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: ID_PESSOA_PRESA }, headers: AUTH });
  assert.equal(segundo.statusCode, 409);
});

test("GET /atendimentos/:chatId inexistente → 404", async () => {
  const app = await montarApp();
  const res = await app.inject({ method: "GET", url: `${BASE}/nao-existe-nunca-foi-criado`, headers: AUTH });
  assert.equal(res.statusCode, 404);
});

test("GET /atendimentos/:chatId depois de criado → mesmo estado, sem avançar o fluxo, sem precisar mandar flowId", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  const criado = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const res = await app.inject({ method: "GET", url: `${BASE}/${chatId}`, headers: AUTH });
  const body = res.json();
  assert.equal(res.statusCode, 200);
  assert.equal(body.resposta, criado.json().resposta, "GET não deve avançar o fluxo");
  assert.equal(body.status, "em_andamento");
});

// Regressão — bug real achado ao vivo 2026-08-31: a Tykhe chamando POST
// /atendimentos de novo no MESMO chatId (retry/reconexão) reiniciava a
// conversa do zero, apagando o progresso. POST em chatId existente agora é
// idempotente — comportamento genérico da rota, não de um fluxo específico
// (regressão de negócio equivalente pra pessoa-presa mora em
// fluxos/pessoaPresa/http.test.ts).
test("POST /atendimentos 2x no MESMO chatId não reinicia — devolve o estado atual", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  const primeira = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const segunda = await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  assert.equal(segunda.statusCode, 200);
  assert.equal(segunda.json().resposta, primeira.json().resposta, "não deveria reiniciar o fluxo");
});

test("POST /atendimentos/respostas sem chatId → 400", async () => {
  const app = await montarApp();
  const res = await app.inject({
    method: "POST",
    url: `${BASE}/respostas`,
    payload: { resposta: "qualquer coisa" },
    headers: AUTH,
  });
  assert.equal(res.statusCode, 400);
});

// Issue #185 — achado ao vivo: resposta ausente/vazia virava
// `new Command({ resume: "" })` (string vazia é falsy, LangGraph trata
// como "sem resume") e explodia um 500 cru ("Received empty Command
// input") em vez de um 400 de validação normal.
test("POST /atendimentos/respostas sem resposta → 400, não 500", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const res = await app.inject({
    method: "POST",
    url: `${BASE}/respostas`,
    payload: { chatId },
    headers: AUTH,
  });
  assert.equal(res.statusCode, 400);
});

test("POST /atendimentos/respostas com resposta vazia (\"\") → 400, não 500", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const res = await app.inject({
    method: "POST",
    url: `${BASE}/respostas`,
    payload: { chatId, resposta: "" },
    headers: AUTH,
  });
  assert.equal(res.statusCode, 400);
});

test("POST /atendimentos/respostas em chatId inexistente (nunca criado) → 404", async () => {
  const app = await montarApp();
  const res = await app.inject({
    method: "POST",
    url: `${BASE}/respostas`,
    payload: { chatId: "nunca-criado", resposta: "qualquer coisa" },
    headers: AUTH,
  });
  assert.equal(res.statusCode, 404);
});

test("POST /atendimentos/respostas SEM flowId no body (resolve sozinho pelo chatId) → funciona", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const res = await app.inject({
    method: "POST",
    url: `${BASE}/respostas`,
    payload: { chatId, resposta: "false" },
    headers: AUTH,
  });
  assert.equal(res.statusCode, 200);
});

// violenciaDomestica hoje termina mais rápido respondendo "false" (não é
// vítima) — só isso importa aqui: mecânica genérica de desfecho (qualquer
// status terminal, não só "concluido"), não o motivo de negócio.
test("fluxo terminado: sem opcoes, sem _links.responder", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  const res = await app.inject({
    method: "POST",
    url: `${BASE}/respostas`,
    payload: { chatId, resposta: "false" },
    headers: AUTH,
  });
  const body = res.json();
  assert.equal(res.statusCode, 200);
  assert.notEqual(body.status, "em_andamento");
  assert.equal(body.opcoes, undefined);
  assert.equal(body._links.responder, undefined, "atendimento terminado não deve oferecer link pra responder de novo");
  assert.equal(body._links.self.href, `${BASE}/${chatId}`);
  // issue #35/#92 — {0,0,0} (não undefined/ausente), NODE_ENV=test nunca
  // chama IA de verdade, então nenhum token real é gasto nesta conversa.
  assert.deepEqual(body.tokensGastos, { input: 0, output: 0, total: 0 });
});

test("POST /atendimentos/respostas em chatId já concluído → 409", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({ method: "POST", url: BASE, payload: { chatId, flowId: FLOW_ID }, headers: AUTH });
  await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "false" }, headers: AUTH });
  const res = await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "qualquer coisa" }, headers: AUTH });
  assert.equal(res.statusCode, 409);
});

// Achado em uso real 2026-09-09: bater esse 409 não devia jogar fora o que
// já tinha sido coletado — enriquece o erro com o mesmo corpo de um GET.
test("POST /atendimentos/respostas em chatId já concluído → 409 enriquecido com metadados/dadosColetados/flowId", async () => {
  const app = await montarApp();
  const chatId = novoChatId();
  await app.inject({
    method: "POST",
    url: BASE,
    payload: { chatId, flowId: FLOW_ID, dadosConhecidos: { cpf: "11111111111" } },
    headers: AUTH,
  });
  await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "false" }, headers: AUTH });
  const res = await app.inject({ method: "POST", url: `${BASE}/respostas`, payload: { chatId, resposta: "qualquer coisa" }, headers: AUTH });
  const body = res.json();
  assert.equal(res.statusCode, 409);
  assert.match(body.erro, /já foi concluído/);
  assert.equal(body.flowId, FLOW_ID);
  assert.equal(body.status, "handoff_humano");
  assert.equal(body.dadosColetados.cpf, "11111111111", "não deveria perder o cpf já coletado só porque bateu 409");
  assert.equal(typeof body.metadados, "object");
});
