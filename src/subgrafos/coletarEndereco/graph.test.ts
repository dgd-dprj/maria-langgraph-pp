import { test } from "node:test";
import assert from "node:assert/strict";
import { Command, StateGraph, START, END, MemorySaver } from "@langchain/langgraph";
import { grafo as coletarEndereco } from "./graph.js";
import { ColetarEnderecoState } from "./state.js";

// coletarEndereco é compilado SEM checkpointer próprio (issue #171/#176 —
// herda persistência de quem chama, não roda sozinho em produção). Pra
// testar isolado, embuti num grafo-envelope só pro teste, com checkpointer
// próprio — mesmo racional de qualquer subgrafo desta pasta.
const grafo = new StateGraph(ColetarEnderecoState)
  .addNode("coletarEndereco", coletarEndereco)
  .addEdge(START, "coletarEndereco")
  .addEdge("coletarEndereco", END)
  .compile({ checkpointer: new MemorySaver() });

let contador = 0;
function novoConfig() {
  contador += 1;
  return { configurable: { thread_id: `teste-grafo-coletar-endereco-${contador}` } };
}

function pergunta(resultado: unknown): { pergunta: string; tipo: string } | undefined {
  return (resultado as { __interrupt__?: Array<{ value: { pergunta: string; tipo: string } }> }).__interrupt__?.[0]?.value;
}

// Issue #176 — CEP completo (mock padrão de verde.ts::consultarCep) traz
// logradouro/bairro/município/UF prontos: só número e complemento (nunca
// vêm do CEP) devem pausar de verdade.
test("CEP completo (mock padrão) → pula logradouro/bairro/município/UF, só pergunta número e complemento", async () => {
  const config = novoConfig();
  const r1 = await grafo.invoke({}, config);
  assert.match(pergunta(r1)?.pergunta ?? "", /CEP/);

  const r2 = await grafo.invoke(new Command({ resume: "20000-000" }), config);
  assert.match(pergunta(r2)?.pergunta ?? "", /número/, "deveria pular logradouro (CEP já trouxe) e pausar em número");

  const r3 = await grafo.invoke(new Command({ resume: "123" }), config);
  assert.match(pergunta(r3)?.pergunta ?? "", /complemento/);

  const r4 = await grafo.invoke(new Command({ resume: "não" }), config);
  assert.equal(pergunta(r4), undefined, "deveria concluir direto — bairro/município/UF já vieram do CEP");
  const endereco = (r4 as { endereco?: Record<string, unknown> }).endereco;
  assert.equal(endereco?.logradouro, "Rua de Teste (mock)");
  assert.equal(endereco?.bairro, "Bairro de Teste (mock)");
  assert.equal(endereco?.municipio, "Rio de Janeiro (mock)");
  assert.equal(endereco?.uf, "RJ");
  assert.equal(endereco?.numero, "123");
  assert.equal(endereco?.complemento, undefined);
});

// Issue #178 — pessoa não sabe o CEP: consultarCep não acha nada
// (encontrado:false), sem nenhum campo pré-preenchido — deveria voltar a
// perguntar tudo, igual ao comportamento de antes da #176.
test("CEP não encontrado (não sabe o CEP) → pergunta todos os campos normalmente", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  const r1 = await grafo.invoke(new Command({ resume: "00000000" }), config); // sentinela "não encontrado"
  assert.match(pergunta(r1)?.pergunta ?? "", /rua\/avenida/, "nada veio do CEP — deveria perguntar logradouro");

  const r2 = await grafo.invoke(new Command({ resume: "Rua Sem CEP" }), config);
  assert.match(pergunta(r2)?.pergunta ?? "", /número/);

  const r3 = await grafo.invoke(new Command({ resume: "10" }), config);
  assert.match(pergunta(r3)?.pergunta ?? "", /complemento/);

  const r4 = await grafo.invoke(new Command({ resume: "não" }), config);
  assert.match(pergunta(r4)?.pergunta ?? "", /bairro/);

  const r5 = await grafo.invoke(new Command({ resume: "Bairro Sem CEP" }), config);
  assert.match(pergunta(r5)?.pergunta ?? "", /município/);

  const r6 = await grafo.invoke(new Command({ resume: "Cidade Sem CEP" }), config);
  assert.match(pergunta(r6)?.pergunta ?? "", /estado/);

  const r7 = await grafo.invoke(new Command({ resume: "rj" }), config);
  assert.equal(pergunta(r7), undefined);
  const endereco = (r7 as { endereco?: Record<string, unknown> }).endereco;
  assert.equal(endereco?.uf, "RJ");
  assert.equal(endereco?.logradouro, "Rua Sem CEP");
  assert.equal(endereco?.municipio, "Cidade Sem CEP");
});

// Issue #176 — CEP incompleto (achado ao vivo, issue #127: alguns CEPs só
// trazem uf) precisa cair de volta a perguntar o que faltou.
test("CEP incompleto (MOCK_CEP_INCOMPLETO) → pergunta logradouro, bairro e município (UF já veio)", async () => {
  const original = process.env.MOCK_CEP_INCOMPLETO;
  process.env.MOCK_CEP_INCOMPLETO = "true";
  try {
    const config = novoConfig();
    await grafo.invoke({}, config);
    const r1 = await grafo.invoke(new Command({ resume: "20000-000" }), config);
    assert.match(pergunta(r1)?.pergunta ?? "", /rua\/avenida/, "uf veio do CEP mas logradouro não — deveria perguntar logradouro");

    const r2 = await grafo.invoke(new Command({ resume: "Rua Nova" }), config);
    assert.match(pergunta(r2)?.pergunta ?? "", /número/);

    const r3 = await grafo.invoke(new Command({ resume: "45" }), config);
    assert.match(pergunta(r3)?.pergunta ?? "", /complemento/);

    const r4 = await grafo.invoke(new Command({ resume: "não" }), config);
    assert.match(pergunta(r4)?.pergunta ?? "", /bairro/);

    const r5 = await grafo.invoke(new Command({ resume: "Centro" }), config);
    assert.match(pergunta(r5)?.pergunta ?? "", /município/);

    const r6 = await grafo.invoke(new Command({ resume: "Rio de Janeiro" }), config);
    assert.equal(pergunta(r6), undefined, "UF já veio do CEP incompleto — não deveria pausar de novo");
    const endereco = (r6 as { endereco?: Record<string, unknown> }).endereco;
    assert.equal(endereco?.uf, "RJ");
    assert.equal(endereco?.logradouro, "Rua Nova");
    assert.equal(endereco?.bairro, "Centro");
    assert.equal(endereco?.municipio, "Rio de Janeiro");
  } finally {
    process.env.MOCK_CEP_INCOMPLETO = original;
  }
});
