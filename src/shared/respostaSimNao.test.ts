import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizarResposta, respostaEhNao, respostaEhSim } from "./respostaSimNao.js";

test("normalizarResposta tira acento, espaço das pontas e caixa", () => {
  assert.equal(normalizarResposta("  NÃO "), "nao");
  assert.equal(normalizarResposta("Recomeçar"), "recomecar");
});

test("respostaEhSim aceita o contrato (\"true\") e o texto que a pessoa digita", () => {
  for (const r of ["true", "sim", "Sim", "SIM", " s ", "S", "yes"]) assert.equal(respostaEhSim(r), true, r);
  for (const r of ["false", "não", "talvez", "", "simples"]) assert.equal(respostaEhSim(r), false, r);
});

test("respostaEhNao aceita o contrato (\"false\") e o texto que a pessoa digita", () => {
  for (const r of ["false", "não", "Não", "NAO", "nao", " n ", "no"]) assert.equal(respostaEhNao(r), true, r);
  for (const r of ["true", "sim", "nada", ""]) assert.equal(respostaEhNao(r), false, r);
});
