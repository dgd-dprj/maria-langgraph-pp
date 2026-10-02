import { test } from "node:test";
import assert from "node:assert/strict";
import { chamarVerdeComRetry, TENTATIVAS_RETRY_VERDE } from "./verde.js";

// Issue #172 — chamarVerdeComRetry não depende de VERDE_JWT_TOKEN/rede real
// (montarRequisicao é injetado), então testa a lógica de retry/classificação
// isolada, com um fake — sem mock mode nem HTTP de verdade.
function respostaFake(status: number): Response {
  return { ok: status >= 200 && status < 300, status } as Response;
}

test("sucesso de primeira — não retenta", async () => {
  let chamadas = 0;
  const resultado = await chamarVerdeComRetry("teste", async () => {
    chamadas += 1;
    return respostaFake(200);
  });
  assert.equal(chamadas, 1);
  assert.equal(resultado.ok, true);
});

test("404 (negócio) não retenta — sai na 1ª tentativa", async () => {
  let chamadas = 0;
  const resultado = await chamarVerdeComRetry("teste", async () => {
    chamadas += 1;
    return respostaFake(404);
  });
  assert.equal(chamadas, 1, "404 é resposta de negócio válida, não deveria retentar");
  assert.equal(resultado.ok, false);
  if (!resultado.ok) assert.equal(resultado.falhaInfra, false);
});

test("422 (negócio) não retenta", async () => {
  let chamadas = 0;
  const resultado = await chamarVerdeComRetry("teste", async () => {
    chamadas += 1;
    return respostaFake(422);
  });
  assert.equal(chamadas, 1);
  assert.equal(resultado.ok, false);
  if (!resultado.ok) assert.equal(resultado.falhaInfra, false);
});

test("500 (infra) retenta até TENTATIVAS_RETRY_VERDE vezes, depois esgota", async () => {
  let chamadas = 0;
  const resultado = await chamarVerdeComRetry("teste", async () => {
    chamadas += 1;
    return respostaFake(500);
  });
  assert.equal(chamadas, TENTATIVAS_RETRY_VERDE);
  assert.equal(resultado.ok, false);
  if (!resultado.ok) assert.equal(resultado.falhaInfra, true);
});

test("401 (infra) retenta, mas sucede numa tentativa posterior", async () => {
  let chamadas = 0;
  const resultado = await chamarVerdeComRetry("teste", async () => {
    chamadas += 1;
    return respostaFake(chamadas < 2 ? 401 : 200);
  });
  assert.equal(chamadas, 2);
  assert.equal(resultado.ok, true);
});

test("403 (infra) retenta igual 401/500", async () => {
  let chamadas = 0;
  const resultado = await chamarVerdeComRetry("teste", async () => {
    chamadas += 1;
    return respostaFake(403);
  });
  assert.equal(chamadas, TENTATIVAS_RETRY_VERDE);
  if (!resultado.ok) assert.equal(resultado.falhaInfra, true);
});

test("exceção de rede/timeout retenta igual falha de infra por status, esgota depois de TENTATIVAS_RETRY_VERDE", async () => {
  let chamadas = 0;
  const resultado = await chamarVerdeComRetry("teste", async () => {
    chamadas += 1;
    throw new Error("timeout simulado");
  });
  assert.equal(chamadas, TENTATIVAS_RETRY_VERDE);
  assert.equal(resultado.ok, false);
  if (!resultado.ok) assert.equal(resultado.falhaInfra, true);
});

test("exceção na 1ª tentativa, sucesso na 2ª", async () => {
  let chamadas = 0;
  const resultado = await chamarVerdeComRetry("teste", async () => {
    chamadas += 1;
    if (chamadas === 1) throw new Error("timeout simulado");
    return respostaFake(200);
  });
  assert.equal(chamadas, 2);
  assert.equal(resultado.ok, true);
});
