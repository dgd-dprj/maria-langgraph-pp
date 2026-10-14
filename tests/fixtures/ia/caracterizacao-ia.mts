// Caracterização do módulo ia de develop @ 4e695f2 contra um Bedrock FALSO local.
// Nenhuma chamada sai da máquina: AWS_ENDPOINT_URL_BEDROCK_RUNTIME aponta para
// um servidor HTTP em 127.0.0.1 que grava a requisição e devolve a resposta
// roteirizada de cada caso. Credencial AWS fictícia.
//
// Rodar na raiz de um worktree de develop @ 4e695f2, com node_modules:
//   node --import tsx <caminho>/caracterizacao-ia.mts <pasta-de-saida>
// O BedrockRuntimeClient usa NodeHttp2Handler: o servidor falso fala HTTP/2 em claro (h2c).
import http2 from "node:http2";
import fs from "node:fs";
import path from "node:path";

const SAIDA = process.argv[2] ?? "saida-ia";
fs.mkdirSync(SAIDA, { recursive: true });

type Roteiro = { status: number; headers?: Record<string, string>; corpo: unknown };
let fila: Roteiro[] = [];
let padrao: Roteiro | undefined;
let requisicoes: { metodo: string; caminho: string; headers: Record<string, string>; corpo: unknown; t: number }[] = [];

const srv = http2.createServer((req, res) => {
  let bruto = "";
  req.on("data", (c) => (bruto += c));
  req.on("end", () => {
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(req.headers)) {
      // assinatura SigV4 e datas mudam a cada execução; credencial é fictícia
      if (k.startsWith(":")) continue;
      if (["authorization", "x-amz-date", "x-amz-security-token", "amz-sdk-invocation-id", "amz-sdk-request", "host", "content-length", "x-amz-content-sha256", "user-agent", "x-amz-user-agent"].includes(k)) continue;
      headers[k] = String(v);
    }
    requisicoes.push({ metodo: req.method!, caminho: decodeURIComponent(req.url!), headers, corpo: bruto ? JSON.parse(bruto) : null, t: Date.now() });
    const r = fila.shift() ?? padrao!;
    res.writeHead(r.status, { "content-type": "application/json", ...(r.headers ?? {}) });
    res.end(JSON.stringify(r.corpo));
  });
});
await new Promise<void>((ok) => srv.listen(0, "127.0.0.1", ok));
const porta = (srv.address() as { port: number }).port;

Object.assign(process.env, {
  AWS_ENDPOINT_URL_BEDROCK_RUNTIME: `http://127.0.0.1:${porta}`,
  AWS_ACCESS_KEY_ID: "AKIAFAKEFAKEFAKEFAKE",
  AWS_SECRET_ACCESS_KEY: "fakefakefakefakefakefakefakefakefakefake",
  AWS_REGION: "us-east-1",
  BEDROCK_MODEL_ID: "us.anthropic.claude-haiku-4-5-20251001-v1:0", // valor de infra/terraform/ecs.tf:40 e release.tf:84
  NODE_ENV: "development",
  REESCREVER_IA: "true",
  EXTRACAO_LIVRE_IA: "true",
});
delete process.env.AWS_PROFILE;

const { classificarEntreOpcoes, classificarMultiploEntreOpcoes } = await import("../develop-ts/src/ia/classificar.ts");
const { classificarFluxosPlausiveis } = await import("../develop-ts/src/ia/classificarFluxos.ts");
const { gerarPerguntaDesambiguacao } = await import("../develop-ts/src/ia/desambiguar.ts");
const { extrairCamposLivre } = await import("../develop-ts/src/ia/extrair.ts");
const { reescreverPergunta, prepararPergunta } = await import("../develop-ts/src/ia/reescrever.ts");
const { sumarizarRelato } = await import("../develop-ts/src/ia/sumarizar.ts");

const USO = { inputTokens: 11, outputTokens: 7, totalTokens: 18 };
const ferramenta = (input: unknown, uso: unknown = USO): Roteiro => ({
  status: 200,
  corpo: {
    output: { message: { role: "assistant", content: [{ toolUse: { toolUseId: "tooluse_1", name: "extract", input } }] } },
    stopReason: "tool_use",
    ...(uso ? { usage: uso } : {}),
    metrics: { latencyMs: 5 },
  },
});
const soTexto: Roteiro = { status: 200, corpo: { output: { message: { role: "assistant", content: [{ text: "não sei" }] } }, stopReason: "end_turn", usage: USO, metrics: { latencyMs: 5 } } };
const throttle: Roteiro = { status: 429, headers: { "x-amzn-errortype": "ThrottlingException:http://internal.amazon.com/coral/com.amazon.bedrock/" }, corpo: { message: "Too many requests, please wait before trying again." } };
const erro500: Roteiro = { status: 500, headers: { "x-amzn-errortype": "InternalServerException:http://internal.amazon.com/coral/com.amazon.bedrock/" }, corpo: { message: "Internal error" } };
const validacao400: Roteiro = { status: 400, headers: { "x-amzn-errortype": "ValidationException:http://internal.amazon.com/coral/com.amazon.bedrock/" }, corpo: { message: "Malformed input request" } };

const resultados: Record<string, unknown> = {};
async function caso(nome: string, roteiros: Roteiro[], fn: () => Promise<unknown>, sempre?: Roteiro) {
  fila = [...roteiros];
  padrao = sempre ?? roteiros[roteiros.length - 1];
  requisicoes = [];
  const t0 = Date.now();
  let resultado: unknown;
  let excecao: string | undefined;
  try {
    resultado = await fn();
  } catch (e) {
    excecao = String(e);
  }
  const reg = {
    resultado: resultado === undefined ? "<undefined>" : resultado,
    ...(excecao ? { excecao } : {}),
    requisicoesHttp: requisicoes.length,
    intervalosMs: requisicoes.map((r, i) => (i === 0 ? r.t - t0 : r.t - requisicoes[i - 1].t)),
    duracaoTotalMs: Date.now() - t0,
  };
  resultados[nome] = reg;
  fs.writeFileSync(path.join(SAIDA, `${nome}.requisicao.json`), JSON.stringify(requisicoes[0] ?? null, null, 2));
  console.log(nome, JSON.stringify(reg));
}

const SIS = "sistema de teste";
// ---- ponto 4: id fora da lista ----
await caso("01-escolha-unica-valida", [ferramenta({ escolhaId: "b" })], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("02-escolha-unica-nenhum", [ferramenta({ escolhaId: "nenhum" })], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("03-escolha-unica-fora-da-lista", [ferramenta({ escolhaId: "inventado" })], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("04-escolha-unica-tipo-errado", [ferramenta({ escolhaId: 7 })], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("05-escolha-unica-sem-chave", [ferramenta({})], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("06-multipla-fora-da-lista", [ferramenta({ idsPlausiveis: ["a", "inventado"] })], () => classificarMultiploEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("07-multipla-nao-lista", [ferramenta({ idsPlausiveis: "a" })], () => classificarMultiploEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("08-sem-tool-use", [soTexto], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
// ---- ponto 5: tokens ----
await caso("09-sem-usage", [ferramenta({ escolhaId: "a" }, null)], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("10-preparar-pergunta-sem-usage", [ferramenta({ pergunta: "Qual o seu RG? 🙂" }, null)], () => prepararPergunta("rg", "Qual o RG?"));
await caso("11-preparar-pergunta-com-usage", [ferramenta({ pergunta: "Qual o seu RG? 🙂" })], () => prepararPergunta("rg", "Qual o RG?"));
// ---- validação ausente em outros esquemas ----
await caso("12-reescrever-sem-chave", [ferramenta({})], () => reescreverPergunta("rg", "Qual o RG?"));
await caso("13-extrair-tipo-errado", [ferramenta({ temProcesso: "sim", rg: 123456, extra: "x" })], () => extrairCamposLivre("meu filho tá preso, rg 123456"));
await caso("14-desambiguar-tipo-errado", [ferramenta({ pergunta: ["a", "b"] })], () => gerarPerguntaDesambiguacao("relato", [{ id: "a", nome: "A", descricao: "da" }, { id: "b", nome: "B", descricao: "db" }]));
await caso("15-sumarizar-ok", [ferramenta({ resumo: "resumo curto" })], () => sumarizarRelato("relato longo"));
// ---- retry ----
await caso("16-throttle-sempre", [throttle], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("17-500-sempre", [erro500], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("18-400-validacao", [validacao400], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
await caso("19-throttle-depois-ok", [throttle, throttle, throttle, ferramenta({ escolhaId: "a" })], () => classificarEntreOpcoes("msg", SIS, ["a", "b"]));
// ---- prompts exatos (bytes do Converse) das seis funções ----
await caso("20-prompt-classificar-fluxos", [ferramenta({ idsPlausiveis: ["f1"] })], () =>
  classificarFluxosPlausiveis("meu marido me bateu", [
    { id: "f1", nome: "Violência doméstica", descricao: "agressão em casa" },
    { id: "f2", nome: "Pessoa presa", descricao: "parente preso" },
  ])
);
await caso("21-prompt-extrair", [ferramenta({ rg: "123" })], () => extrairCamposLivre("rg 123"));
await caso("22-prompt-reescrever", [ferramenta({ pergunta: "Qual é o seu RG? 🙂" })], () => reescreverPergunta("rg", "Qual o RG?"));

fs.writeFileSync(path.join(SAIDA, "resultados.json"), JSON.stringify(resultados, null, 2));
srv.close();
