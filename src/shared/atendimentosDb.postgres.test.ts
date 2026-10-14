import { test } from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { criarStoreEmMemoria, criarStorePostgres, type AtendimentosStore } from "./atendimentosDb.js";

// Issue #217 — o defeito só existia na store Postgres (a em memória guardava
// o valor antes de limpar), por isso este teste roda contra um Postgres de
// verdade. `pnpm test` não tem banco (ver docs/testes.md): sem
// TEST_DATABASE_URL os testes daqui são pulados, não falham. Pra rodar:
//   TEST_DATABASE_URL=postgres://postgres:postgres@localhost:5432/postgres pnpm test
// A store cria a tabela `atendimentos` se não existir (mesmo DDL de
// produção) — usar um banco descartável, nunca o de prod/release.
const URL_TESTE = process.env.TEST_DATABASE_URL;
const semBanco = URL_TESTE ? false : "TEST_DATABASE_URL ausente — teste contra Postgres real pulado";

const FLOW_ID = randomUUID();

async function caminhoConfirmacaoTtl(store: AtendimentosStore, respostaOriginal: string) {
  const chatId = `teste-217-${randomUUID()}`;
  await store.registrar(chatId, FLOW_ID);
  await store.marcarAguardandoConfirmacaoTtl(chatId, respostaOriginal);
  const devolvida = await store.resolverConfirmacaoTtlContinuar(chatId);
  const depois = await store.buscarAtividade(chatId);
  return { devolvida, depois };
}

test("Postgres: resolverConfirmacaoTtlContinuar devolve a resposta guardada e limpa a coluna", { skip: semBanco }, async () => {
  const store = await criarStorePostgres(URL_TESTE!);
  const { devolvida, depois } = await caminhoConfirmacaoTtl(store, "false");

  assert.equal(devolvida, "false");
  assert.equal(depois?.aguardandoConfirmacaoTtl, false);
  assert.equal(depois?.respostaPendente, undefined);
});

test("Postgres e memória devolvem o mesmo valor no caminho de confirmação de TTL", { skip: semBanco }, async () => {
  const postgres = await criarStorePostgres(URL_TESTE!);
  const memoria = criarStoreEmMemoria();

  for (const resposta of ["true", "false", "texto livre da pessoa", ""]) {
    const viaPostgres = await caminhoConfirmacaoTtl(postgres, resposta);
    const viaMemoria = await caminhoConfirmacaoTtl(memoria, resposta);
    assert.equal(viaPostgres.devolvida, viaMemoria.devolvida, `resposta ${JSON.stringify(resposta)}`);
    assert.equal(viaPostgres.depois?.respostaPendente, viaMemoria.depois?.respostaPendente);
    assert.equal(viaPostgres.depois?.aguardandoConfirmacaoTtl, viaMemoria.depois?.aguardandoConfirmacaoTtl);
  }
});

test("Postgres: chatId inexistente devolve undefined, sem erro", { skip: semBanco }, async () => {
  const store = await criarStorePostgres(URL_TESTE!);
  assert.equal(await store.resolverConfirmacaoTtlContinuar(`teste-217-inexistente-${randomUUID()}`), undefined);
});
