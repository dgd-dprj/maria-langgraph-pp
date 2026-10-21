// Conferência diferencial do PR 2 do api: lado develop @ 1157a6d, app real por inject.
// Uso (cwd = worktree): node --import tsx executor-develop.mts <cenarios.json> <saida.json> > <logs.ndjson>
// Antes de cada cenário, uma linha `{"marcador": <nome>}` vai pelo mesmo logger do
// app, para separar as linhas de log de cada cenário (inclusive as das chamadas
// internas do bridge do WhatsApp).
import fs from "node:fs";

const [CENARIOS, SAIDA] = process.argv.slice(2);
const cenarios = JSON.parse(fs.readFileSync(CENARIOS, "utf8"));

Object.assign(process.env, { NODE_ENV: "test", API_KEY: "chave-conferencia" });
for (const k of [
  "DATABASE_URL",
  "VERDE_JWT_TOKEN",
  "MOCK_CLASSIFICACAO_FLOWID",
  "MOCK_CLASSIFICACAO_FLOWIDS",
  "ORQUESTRADOR_INCLUIR_PLANEJADOS",
  "TTL_INATIVIDADE_HORAS",
  "WHATSAPP_VERIFY_TOKEN",
  "WHATSAPP_ACCESS_TOKEN",
  "WHATSAPP_PHONE_NUMBER_ID",
  "MOCK_CLASSIFICACAO_PARENTESCO",
  "MOCK_ENCAMINHAMENTO_FALHA",
]) {
  delete process.env[k];
}
const { montarApp } = await import("./src/app.ts");
const app = await montarApp();

const resultados: unknown[] = [];
for (const c of cenarios) {
  app.log.info({ marcador: c.nome });
  const antes: Record<string, string | undefined> = {};
  const env: Record<string, string> = { NODE_ENV: c.env.APP_ENV ?? "test" };
  for (const [k, v] of Object.entries(c.env)) if (k !== "APP_ENV") env[k] = v as string;
  for (const [k, v] of Object.entries(env)) {
    antes[k] = process.env[k];
    process.env[k] = v;
  }
  const payload = c.corpo === null ? {} : { payload: c.corpo };
  const r = await app.inject({ method: c.metodo, url: c.caminho, headers: c.headers, ...payload });
  for (const [k, v] of Object.entries(antes)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  resultados.push({ nome: c.nome, status: r.statusCode, contentType: r.headers["content-type"] ?? null, location: r.headers["location"] ?? null, corpo: r.body });
}
app.log.info({ marcador: "__fim__" });
fs.writeFileSync(SAIDA, JSON.stringify(resultados, null, 1));
await app.close();
// Dá tempo de o pino esvaziar o buffer antes de sair.
await new Promise((ok) => setTimeout(ok, 300));
process.exit(0);
