import { test } from "node:test";
import assert from "node:assert/strict";
import { montarApp } from "../src/app.js";
import { ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA } from "../src/fluxos/index.js";
import { adicionarPlanejadoDeTeste, removerPlanejadoDeTeste } from "../src/shared/fluxosPlanejadosDb.js";
import { obterPerguntasStore, type PerguntaArvore } from "../src/shared/perguntasDb.js";
import { randomUUID } from "node:crypto";

// Testa só a MECÂNICA da rota do orquestrador (rotas/orquestrador.ts) —
// resolve fluxo por classificação em vez de flowId explícito. Classificação
// em si é mockada via MOCK_CLASSIFICACAO_FLOWID/FLOWIDS (ver
// ia/classificarFluxos.ts) — NODE_ENV=test nunca chama Bedrock de verdade.
// MOCK_CLASSIFICACAO_FLOWIDS (plural, separado por vírgula) simula vários
// candidatos plausíveis — issue #28, desambiguação.

let contador = 0;
function novoChatId() {
  contador += 1;
  return `teste-orq-${contador}`;
}

const AUTH = { authorization: `Bearer ${process.env.API_KEY}` };
const BASE = "/atendimentos/orquestrador";

test("sem mensagem → 400", async () => {
  const app = await montarApp();
  const res = await app.inject({ method: "POST", url: BASE, payload: {}, headers: AUTH });
  assert.equal(res.statusCode, 400);
});

// Issue #185 — resposta:"" (vazia, não só ausente) precisa barrar aqui
// também: viraria new Command({resume:""}) mais abaixo, que o LangGraph
// trata como "sem resume" (string vazia é falsy) e explode um 500 cru em
// vez de um 400 de validação normal.
test("resposta vazia (\"\") → 400, não 500", async () => {
  const app = await montarApp();
  const res = await app.inject({ method: "POST", url: BASE, payload: { chatId: novoChatId(), resposta: "" }, headers: AUTH });
  assert.equal(res.statusCode, 400);
});

test("sem Authorization → 401 (rota protegida igual às demais)", async () => {
  const app = await montarApp();
  const res = await app.inject({ method: "POST", url: BASE, payload: { mensagem: "qualquer coisa" } });
  assert.equal(res.statusCode, 401);
});

test("classificação não identifica nenhum fluxo → handoff_humano direto, sem flowId", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_FLOWID;
  delete process.env.MOCK_CLASSIFICACAO_FLOWID;
  try {
    const app = await montarApp();
    const res = await app.inject({
      method: "POST",
      url: BASE,
      payload: { chatId: novoChatId(), mensagem: "quero saber sobre meu carnê do IPTU" },
      headers: AUTH,
    });
    const body = res.json();
    assert.equal(res.statusCode, 200);
    assert.equal(body.status, "handoff_humano");
    assert.equal(body.motivoHandoff, "nao_identificado");
    assert.equal(body.flowId, undefined);
    assert.match(body.resposta, /Não consegui identificar/);
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWID = original;
  }
});

// Mede demanda de fluxo ainda não codado (tabela fluxos_planejados, issue #26) — IA
// "reconhece" pelo relato, cai no grafo padrão compartilhado (issue #21),
// conclui de verdade (não é mais handoff especial). flowId aparece na
// resposta/log — é isso que dá a métrica de demanda, sem precisar de campo
// especial.
test("classificação identifica fluxo PLANEJADO (sem código ainda) → grafo padrão, concluido de verdade", async () => {
  const fluxoFalso = {
    id: "00000000-0000-0000-0000-000000000099",
    nome: "fluxo-teste-planejado",
    descricao: "só pra teste",
    idCategoriaAssuntoVerde: 99999,
    palavrasChave: [],
  };
  await adicionarPlanejadoDeTeste(fluxoFalso);
  const original = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWID = fluxoFalso.id;
  try {
    const app = await montarApp();
    const res = await app.inject({
      method: "POST",
      url: BASE,
      payload: { chatId: novoChatId(), mensagem: "preciso de um fluxo que ainda não existe" },
      headers: AUTH,
    });
    const body = res.json();
    assert.equal(res.statusCode, 200);
    assert.equal(body.status, "concluido");
    assert.equal(body.flowId, fluxoFalso.id, "flowId do planejado deve aparecer — atendimento rodou de verdade (grafo padrão)");
    assert.match(body.resposta, /sendo construíd/i);
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWID = original;
    await removerPlanejadoDeTeste(fluxoFalso.id);
  }
});

// Issue #21: várias categorias planejadas diferentes compartilham a MESMA
// instância de grafo padrão (fluxos/index.ts::FLUXO_PADRAO) — isolamento de
// conversa é por chatId/thread_id, não por qual flowId planejado apontou pra
// cá. Esse teste garante que 2 flowId diferentes não misturam estado.
test("2 categorias planejadas diferentes usam o mesmo grafo padrão sem misturar estado entre si", async () => {
  const planejadoA = {
    id: "00000000-0000-0000-0000-0000000000a1",
    nome: "planejado-a",
    descricao: "a",
    idCategoriaAssuntoVerde: 88881,
    palavrasChave: [],
  };
  const planejadoB = {
    id: "00000000-0000-0000-0000-0000000000b2",
    nome: "planejado-b",
    descricao: "b",
    idCategoriaAssuntoVerde: 88882,
    palavrasChave: [],
  };
  await adicionarPlanejadoDeTeste(planejadoA);
  await adicionarPlanejadoDeTeste(planejadoB);
  const original = process.env.MOCK_CLASSIFICACAO_FLOWID;
  try {
    const app = await montarApp();
    const chatA = novoChatId();
    const chatB = novoChatId();

    process.env.MOCK_CLASSIFICACAO_FLOWID = planejadoA.id;
    const resA = await app.inject({ method: "POST", url: BASE, payload: { chatId: chatA, mensagem: "relato A" }, headers: AUTH });

    process.env.MOCK_CLASSIFICACAO_FLOWID = planejadoB.id;
    const resB = await app.inject({ method: "POST", url: BASE, payload: { chatId: chatB, mensagem: "relato B" }, headers: AUTH });

    assert.equal(resA.json().flowId, planejadoA.id);
    assert.equal(resB.json().flowId, planejadoB.id);
    assert.equal(resA.json().status, "concluido");
    assert.equal(resB.json().status, "concluido");

    const getA = await app.inject({ method: "GET", url: `/atendimentos/${chatA}`, headers: AUTH });
    const getB = await app.inject({ method: "GET", url: `/atendimentos/${chatB}`, headers: AUTH });
    assert.equal(getA.json().flowId, planejadoA.id, "GET do chatId A não deveria vazar o flowId de B");
    assert.equal(getB.json().flowId, planejadoB.id, "GET do chatId B não deveria vazar o flowId de A");
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWID = original;
    await removerPlanejadoDeTeste(planejadoA.id);
    await removerPlanejadoDeTeste(planejadoB.id);
  }
});

test("classificação identifica pessoa-presa → cria atendimento normalmente, corpo inclui flowId", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWID = ID_PESSOA_PRESA;
  try {
    const app = await montarApp();
    const chatId = novoChatId();
    const res = await app.inject({
      method: "POST",
      url: BASE,
      payload: { chatId, mensagem: "meu marido foi preso, queria saber do processo dele" },
      headers: AUTH,
    });
    const body = res.json();
    assert.equal(res.statusCode, 200);
    assert.equal(body.status, "em_andamento");
    assert.equal(body.flowId, ID_PESSOA_PRESA);
    assert.match(body.resposta, /número do processo/);

    // dali em diante é o MESMO atendimento de sempre — GET resolve pela
    // tabela chatId→flowId sem precisar mandar flowId de novo.
    const get = await app.inject({ method: "GET", url: `/atendimentos/${chatId}`, headers: AUTH });
    assert.equal(get.statusCode, 200);
    assert.equal(get.json().resposta, body.resposta);
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWID = original;
  }
});

test("chatId já existe em outro flowId → 409, mesma proteção da criação manual", async () => {
  const chatId = novoChatId();
  const original = process.env.MOCK_CLASSIFICACAO_FLOWID;
  try {
    const app = await montarApp();
    // cria manualmente num fluxo
    await app.inject({
      method: "POST",
      url: "/atendimentos",
      payload: { chatId, flowId: ID_PESSOA_PRESA },
      headers: AUTH,
    });
    // orquestrador tenta criar o MESMO chatId classificando pra outro flowId
    process.env.MOCK_CLASSIFICACAO_FLOWID = "cabb2495-4e12-4f4a-9956-3d20649059bc";
    const res = await app.inject({
      method: "POST",
      url: BASE,
      payload: { chatId, mensagem: "sou vítima de violência doméstica" },
      headers: AUTH,
    });
    assert.equal(res.statusCode, 409);
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWID = original;
  }
});

// Issue #28 — desambiguação. Relato bate com 2+ candidatos plausíveis: o
// orquestrador pergunta em vez de chutar 1, e a resposta reduz pra 1 só.
test("relato ambíguo entre 2 fluxos → pergunta de desambiguação → resposta resolve pra 1 só", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_FLOWIDS;
  const originalSingular = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWIDS = `${ID_PESSOA_PRESA},${ID_VIOLENCIA_DOMESTICA}`;
  delete process.env.MOCK_CLASSIFICACAO_FLOWID;
  try {
    const app = await montarApp();
    const chatId = novoChatId();

    const r1 = await app.inject({
      method: "POST",
      url: BASE,
      payload: { chatId, mensagem: "relato que bate com 2 fluxos" },
      headers: AUTH,
    });
    const body1 = r1.json();
    assert.equal(r1.statusCode, 200);
    assert.equal(body1.status, "em_andamento");
    assert.equal(body1.flowId, undefined, "não deveria ter flowId enquanto ainda está desambiguando");
    assert.equal(body1.tipoResposta, "texto", "pergunta de desambiguação é texto livre, não menu de opções (decisão 2026-09-11)");

    // resposta de desambiguação escolhe/reduz pra 1 candidato só
    process.env.MOCK_CLASSIFICACAO_FLOWIDS = ID_PESSOA_PRESA;
    const r2 = await app.inject({
      method: "POST",
      url: BASE,
      payload: { chatId, resposta: "pessoa-presa" },
      headers: AUTH,
    });
    const body2 = r2.json();
    assert.equal(r2.statusCode, 200);
    assert.equal(body2.flowId, ID_PESSOA_PRESA);
    assert.equal(body2.status, "em_andamento", "agora é o fluxo real perguntando, não mais desambiguação");
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWIDS = original;
    process.env.MOCK_CLASSIFICACAO_FLOWID = originalSingular;
  }
});

function perguntaRaiz(flowId: string, overrides: Partial<PerguntaArvore> = {}): PerguntaArvore {
  return {
    id: randomUUID(),
    flowId,
    idItemCategoria: null,
    veioDaRespostaId: null,
    textoPergunta: "pergunta raiz de teste",
    tipo: "sim_nao",
    opcoes: [{ id: 1, resposta: "SIM" }, { id: 2, resposta: "NÃO" }],
    ordem: 0,
    ...overrides,
  };
}

// Issue #32 — quando os 2 candidatos ambíguos compartilham literalmente a
// mesma pergunta raiz do Verde (mesmo texto + mesmas opções), usa esse
// texto real em vez de gerar pergunta genérica por IA.
test("desambiguação com pergunta raiz IDÊNTICA nos 2 candidatos → usa texto real do banco, não a IA", async () => {
  const store = await obterPerguntasStore();
  const original = process.env.MOCK_CLASSIFICACAO_FLOWIDS;
  const originalSingular = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWIDS = `${ID_PESSOA_PRESA},${ID_VIOLENCIA_DOMESTICA}`;
  delete process.env.MOCK_CLASSIFICACAO_FLOWID;
  await store.inserirPergunta(perguntaRaiz(ID_PESSOA_PRESA, { textoPergunta: "JÁ TEM PROCESSO JUDICIAL?" }));
  await store.inserirPergunta(perguntaRaiz(ID_VIOLENCIA_DOMESTICA, { textoPergunta: "JÁ TEM PROCESSO JUDICIAL?" }));
  try {
    const app = await montarApp();
    const res = await app.inject({ method: "POST", url: BASE, payload: { chatId: novoChatId(), mensagem: "relato ambíguo" }, headers: AUTH });
    assert.equal(res.json().resposta, "JÁ TEM PROCESSO JUDICIAL?", "deveria usar o texto real do banco, não a pergunta genérica de IA");
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWIDS = original;
    process.env.MOCK_CLASSIFICACAO_FLOWID = originalSingular;
    await store.limparFlow(ID_PESSOA_PRESA);
    await store.limparFlow(ID_VIOLENCIA_DOMESTICA);
  }
});

test("desambiguação com pergunta raiz DIFERENTE entre os candidatos → cai no fallback de IA", async () => {
  const store = await obterPerguntasStore();
  const original = process.env.MOCK_CLASSIFICACAO_FLOWIDS;
  const originalSingular = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWIDS = `${ID_PESSOA_PRESA},${ID_VIOLENCIA_DOMESTICA}`;
  delete process.env.MOCK_CLASSIFICACAO_FLOWID;
  await store.inserirPergunta(perguntaRaiz(ID_PESSOA_PRESA, { textoPergunta: "pergunta A" }));
  await store.inserirPergunta(perguntaRaiz(ID_VIOLENCIA_DOMESTICA, { textoPergunta: "pergunta B" }));
  try {
    const app = await montarApp();
    const res = await app.inject({ method: "POST", url: BASE, payload: { chatId: novoChatId(), mensagem: "relato ambíguo" }, headers: AUTH });
    assert.match(res.json().resposta, /qual dessas opções descreve/i, "pergunta raiz diferente entre os 2 não é match — deveria cair no fallback de IA");
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWIDS = original;
    process.env.MOCK_CLASSIFICACAO_FLOWID = originalSingular;
    await store.limparFlow(ID_PESSOA_PRESA);
    await store.limparFlow(ID_VIOLENCIA_DOMESTICA);
  }
});

test("desambiguação com só 1 dos 2 candidatos tendo pergunta no banco → cai no fallback de IA", async () => {
  const store = await obterPerguntasStore();
  const original = process.env.MOCK_CLASSIFICACAO_FLOWIDS;
  const originalSingular = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWIDS = `${ID_PESSOA_PRESA},${ID_VIOLENCIA_DOMESTICA}`;
  delete process.env.MOCK_CLASSIFICACAO_FLOWID;
  await store.inserirPergunta(perguntaRaiz(ID_PESSOA_PRESA, { textoPergunta: "só pessoa presa tem essa pergunta" }));
  try {
    const app = await montarApp();
    const res = await app.inject({ method: "POST", url: BASE, payload: { chatId: novoChatId(), mensagem: "relato ambíguo" }, headers: AUTH });
    assert.match(res.json().resposta, /qual dessas opções descreve/i, "faltando pergunta pra 1 dos candidatos — deveria cair no fallback de IA");
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWIDS = original;
    process.env.MOCK_CLASSIFICACAO_FLOWID = originalSingular;
    await store.limparFlow(ID_PESSOA_PRESA);
  }
});

// Esgota o limite de rodadas de desambiguação (5, issue #43) sem convergir
// pra 1 só → cai em handoff_humano em vez de perguntar pra sempre.
test("ambiguidade que nunca resolve → esgota limite de rodadas → handoff_humano", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_FLOWIDS;
  const originalSingular = process.env.MOCK_CLASSIFICACAO_FLOWID;
  process.env.MOCK_CLASSIFICACAO_FLOWIDS = `${ID_PESSOA_PRESA},${ID_VIOLENCIA_DOMESTICA}`;
  delete process.env.MOCK_CLASSIFICACAO_FLOWID;
  try {
    const app = await montarApp();
    const chatId = novoChatId();

    let res = await app.inject({ method: "POST", url: BASE, payload: { chatId, mensagem: "relato sempre ambíguo" }, headers: AUTH });
    assert.equal(res.json().status, "em_andamento", "pergunta 1");

    res = await app.inject({ method: "POST", url: BASE, payload: { chatId, resposta: "não esclarece" }, headers: AUTH });
    assert.equal(res.json().status, "em_andamento", "pergunta 2");

    res = await app.inject({ method: "POST", url: BASE, payload: { chatId, resposta: "não esclarece" }, headers: AUTH });
    assert.equal(res.json().status, "em_andamento", "pergunta 3");

    res = await app.inject({ method: "POST", url: BASE, payload: { chatId, resposta: "não esclarece" }, headers: AUTH });
    assert.equal(res.json().status, "em_andamento", "pergunta 4");

    res = await app.inject({ method: "POST", url: BASE, payload: { chatId, resposta: "não esclarece" }, headers: AUTH });
    assert.equal(res.json().status, "em_andamento", "pergunta 5");

    res = await app.inject({ method: "POST", url: BASE, payload: { chatId, resposta: "não esclarece" }, headers: AUTH });
    const body = res.json();
    assert.equal(body.status, "handoff_humano", "esgotou as 5 rodadas, ainda ambíguo → desiste");
    assert.equal(body.motivoHandoff, "nao_identificado");
  } finally {
    process.env.MOCK_CLASSIFICACAO_FLOWIDS = original;
    process.env.MOCK_CLASSIFICACAO_FLOWID = originalSingular;
  }
});
