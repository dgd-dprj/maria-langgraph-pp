// Tabela-verdade da serialização de resposta do Fastify de develop @ 1157a6d, com os
// schemas das rotas. Cada valor sai de uma rota real, por inject.
// Rodar a partir do worktree: node --import tsx fjs-tabela.mts
import Fastify from "fastify";

const linksSchema = {
  type: "object",
  properties: {
    self: { type: "object", properties: { href: { type: "string" } } },
    responder: { type: "object", properties: { href: { type: "string" }, method: { type: "string", enum: ["POST"] } } },
  },
};
const tokens = { type: "object", properties: { input: { type: "number" }, output: { type: "number" }, total: { type: "number" } } };
const atendimento = {
  type: "object",
  properties: {
    resposta: { type: "string" },
    tipoResposta: { type: "string", enum: ["texto", "sim_nao", "opcoes"] },
    opcoes: { type: "array", items: { type: "string" } },
    status: { type: "string" },
    flowId: { type: "string", format: "uuid" },
    metadados: { type: "object", additionalProperties: true },
    dadosColetados: { type: "object", properties: { cpf: { type: "string" } } },
    tokensGastos: tokens,
    _links: linksSchema,
  },
};
const erro = { type: "object", properties: { erro: { type: "string" } }, additionalProperties: true };
const erroSem = { type: "object", properties: { erro: { type: "string" } } };
const fluxos = { type: "array", items: { type: "object", properties: { id: { type: "string", format: "uuid" }, nome: { type: "string" } } } };

const valores: Record<string, unknown> = {
  string: "x", vazia: "", numero_int: 7, numero_float: 1.5, exp_pequeno: 1e-7, exp_grande: 1e21, zero_neg: -0,
  nan: NaN, infinito: Infinity, true: true, false: false, null: null, undefined: undefined,
  objeto: { a: 1 }, lista: ["a", null, 2], lista_vazia: [], data: new Date(0), aninhado_undef: { a: undefined, b: [undefined] },
};

const casos: Record<string, (v: unknown) => { schema: "a" | "e" | "es" | "f"; corpo: unknown }> = {
  "resposta": (v) => ({ schema: "a", corpo: { resposta: v } }),
  "tokens.input": (v) => ({ schema: "a", corpo: { tokensGastos: { input: v, output: 1, total: 2 } } }),
  "opcoes[0]": (v) => ({ schema: "a", corpo: { opcoes: [v] } }),
  "opcoes": (v) => ({ schema: "a", corpo: { opcoes: v } }),
  "metadados.k": (v) => ({ schema: "a", corpo: { metadados: { k: v } } }),
  "metadados": (v) => ({ schema: "a", corpo: { metadados: v } }),
  "dadosColetados": (v) => ({ schema: "a", corpo: { dadosColetados: v } }),
  "dadosColetados.cpf": (v) => ({ schema: "a", corpo: { dadosColetados: { cpf: v } } }),
  "_links.self": (v) => ({ schema: "a", corpo: { _links: { self: v } } }),
  "_links.self.href": (v) => ({ schema: "a", corpo: { _links: { self: { href: v } } } }),
  "erro.erro": (v) => ({ schema: "e", corpo: { erro: v } }),
  "erro.extra": (v) => ({ schema: "e", corpo: { erro: "e", extra: v } }),
  "fluxos[0].id": (v) => ({ schema: "f", corpo: [{ id: v, nome: "n" }] }),
  "raiz atendimento": (v) => ({ schema: "a", corpo: v }),
};

const app = Fastify({ logger: false });
let atual: { schema: string; corpo: unknown } = { schema: "a", corpo: {} };
app.get("/a", { schema: { response: { 200: atendimento } } }, async () => atual.corpo);
app.get("/e", { schema: { response: { 409: erro } } }, async (_q, r) => r.code(409).send(atual.corpo));
app.get("/es", { schema: { response: { 409: erroSem } } }, async (_q, r) => r.code(409).send(atual.corpo));
app.get("/f", { schema: { response: { 200: fluxos } } }, async () => atual.corpo);
await app.ready();

const saida: Record<string, string> = {};
for (const [nomeCaso, f] of Object.entries(casos)) {
  for (const [nomeValor, v] of Object.entries(valores)) {
    atual = f(v);
    const r = await app.inject({ method: "GET", url: `/${atual.schema}` });
    saida[`${nomeCaso} = ${nomeValor}`] = `${r.statusCode} ${r.body}`;
  }
}
// Extras: ordem, campos não declarados, erro sem additionalProperties.
atual = { schema: "a", corpo: { _links: { self: { href: "/a" } }, extra: 1, status: "s", resposta: "r" } };
saida["ordem e extra"] = (await app.inject({ method: "GET", url: "/a" })).body;
atual = { schema: "es", corpo: { erro: "e", status: "concluido" } };
saida["erro sem additionalProperties com extra"] = (await app.inject({ method: "GET", url: "/es" })).body;
atual = { schema: "e", corpo: { erro: "e", status: "concluido", z: undefined, n: null } };
saida["erro com additionalProperties: undefined e null"] = (await app.inject({ method: "GET", url: "/e" })).body;
console.log(JSON.stringify(saida, null, 1));
await app.close();
