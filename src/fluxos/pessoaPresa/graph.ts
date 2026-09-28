import { interrupt, StateGraph, START, END } from "@langchain/langgraph";
import { z } from "zod";
import { type PessoaPresaStateType, PessoaPresaState } from "./state.js";
import type { Pergunta } from "../../shared/types.js";
import { consultarApenadoPorRg, consultarProcesso as consultarProcessoVerde } from "../../integracoes/verde.js";
import { prepararPergunta } from "../../ia/reescrever.js";
import { extrairCamposLivre } from "../../ia/extrair.js";
import { classificarEntreOpcoes } from "../../ia/classificar.js";
import { criarCheckpointer } from "../../shared/checkpointer.js";
import { MENSAGEM_HANDOFF_SEM_NUMERO_PROCESSO, MENSAGEM_HANDOFF_ORIGEM_NAO_SUPORTADA, MENSAGEM_FALHA_CADASTRO } from "./api.js";
import { grafo as subgrafoIdentificarAssistido } from "../../subgrafos/identificarAssistido/graph.js";
import { grafo as subgrafoCadastroPessoa } from "../../subgrafos/cadastroPessoa/graph.js";

const ORIGEM_PROCESSO_SUPORTADA = "SEEU";

// Issue #57 — só um subconjunto de situação/tipo de preso/regime permite
// considerar o atendimento resolvido pela Maria (ticket original do
// sistema de origem, SIPEN). Valores SEM o prefixo "EM" — normalizarSituacao
// remove esse prefixo antes de comparar.
const SITUACOES_PERMITIDAS = new Set([
  "ATIVO",
  "RESDOM",
  "TRABALHO EXTRAMURO",
  "BAIXA HOSPITALAR",
  "VPF",
  "VPF/TRABALHO EXTRAMURO",
  "VPF/ATIVIDADE EDUCACIONAL",
  "ABERTO/DOMICÍLIO COVID-19",
]);
const TIPO_PRESO_PERMITIDO = "CONDENADO";
const REGIMES_PERMITIDOS = new Set(["FECHADO", "SEMIABERTO"]);

// Achado ao vivo (issue #57): o Verde é inconsistente no prefixo "EM" entre
// valores de situação ("ATIVO" sem prefixo, "EM RESDOM" com prefixo) —
// remove o token solto "EM " de cada parte (situações compostas usam "/",
// ex: "Em VPF/Em Trabalho Extramuro") em vez de tentar acertar a grafia
// exata de cada valor.
function normalizarSituacao(situacao: string): string {
  return situacao
    .toUpperCase()
    .split("/")
    .map((parte) => parte.trim().replace(/^EM\s+/, ""))
    .join("/");
}

function dadosApenadoAtendidos(state: PessoaPresaStateType): boolean {
  const { situacao, tipoPreso, regime } = state.dadosApenado ?? {};
  if (situacao === undefined || tipoPreso === undefined || regime === undefined) return false;
  return (
    SITUACOES_PERMITIDAS.has(normalizarSituacao(situacao)) &&
    tipoPreso.toUpperCase() === TIPO_PRESO_PERMITIDO &&
    REGIMES_PERMITIDOS.has(regime.toUpperCase())
  );
}

// Guard da extração livre — desligada por padrão, liga só com a env var
// explícita. Esse guard decide se o grafo ENTRA no ramo de extração no
// START (roteamentoInicial); com ele false, comportamento idêntico a antes
// dessa feature existir. Só checa EXTRACAO_LIVRE_IA, NÃO NODE_ENV — o guard
// de "não gastar Bedrock de verdade em teste" já mora dentro de
// extrairCamposLivre (ia/extrair.ts), mesmo padrão de reescreverPergunta.
// Duplicar o check de NODE_ENV aqui faria a flag nunca funcionar durante
// `pnpm test` (que roda com NODE_ENV=test sempre) — bug real, achado pelos
// testes de roteamento abaixo.
function extracaoLivreHabilitada(): boolean {
  return process.env.EXTRACAO_LIVRE_IA === "true";
}

// Normaliza a resposta de uma pergunta sim_nao. O contrato original previa
// só "true"/"false" crus (a Tykhe manda isso) — mas na prática o fluxo dela
// às vezes repassa o texto literal que o usuário digitou/clicou ("Sim"/
// "Não", com acento/maiúscula variável), sem traduzir pra "true"/"false".
// Achado ao vivo 2026-08-31: "Sim" literal caindo em `resposta === "true"`
// vira false, confirmação de nome nega errado, manda pro handoff sem
// motivo. Aceita as duas formas — tolerante ao cliente real, não só ao
// contrato "correto" no papel.
function respostaEhSim(resposta: string): boolean {
  const normalizado = resposta
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "") // remove acentos (ã→a, ó→o...)
    .trim()
    .toLowerCase();
  return normalizado === "true" || normalizado === "sim" || normalizado === "s" || normalizado === "yes";
}

// Pergunta livre no início do fluxo (opcional, ver extracaoLivreHabilitada)
// — deixa a pessoa contar a situação com as próprias palavras. A extração
// roda DEPOIS do interrupt() resolver, no mesmo nó que pausa (mesmo padrão
// dos outros "pedir": pós-processar a resposta depois de retomar é seguro,
// só o código ANTES do interrupt() reexecuta em todo resume — ver
// prepararPergunta() em ia/reescrever.ts). Por isso não precisa de um nó
// "preparar" + "extrair" separados feito as outras perguntas: a chamada de
// extração já é o pós-processamento, roda só 1x.
async function prepararPerguntaLivre(): Promise<Partial<PessoaPresaStateType>> {
  return prepararPergunta(
    "relatoLivre",
    "Pode me contar a situação com suas palavras? Se já souber, pode falar o número do processo, o RG da pessoa presa e seu parentesco com ela — tudo de uma vez."
  );
}

async function pedirLivre(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta:
      state.perguntaAtualTexto ??
      "Pode me contar a situação com suas palavras? Se já souber, pode falar o número do processo, o RG da pessoa presa e seu parentesco com ela — tudo de uma vez.",
    tipo: "texto",
  });
  const extraido = await extrairCamposLivre(resposta);
  return {
    ...(extraido.temProcesso !== undefined ? { temProcesso: extraido.temProcesso } : {}),
    ...(extraido.numeroProcesso !== undefined ? { numeroProcesso: extraido.numeroProcesso } : {}),
    ...(extraido.rg !== undefined ? { rg: extraido.rg } : {}),
    ...(extraido.parentesco !== undefined ? { parentesco: extraido.parentesco } : {}),
    // único nó deste fluxo que chama IA fora de prepararPergunta() — soma o
    // delta manualmente (issue #35, entrada/saída discriminados na #69,
    // agrupados num objeto único na #92).
    tokensGastos: { input: extraido.tokensEntrada ?? 0, output: extraido.tokensSaida ?? 0, total: extraido.tokensTotal ?? 0 },
  };
}

function roteamentoInicial(): "comExtracao" | "semExtracao" {
  return extracaoLivreHabilitada() ? "comExtracao" : "semExtracao";
}

// temProcesso já pode vir preenchido da extração livre (pedirLivre, acima)
// — bypass evita perguntar de novo o que a pessoa já contou. Com a extração
// desligada (padrão), state.temProcesso nunca chega aqui definido antes da
// hora, então esse `if` nunca dispara — comportamento idêntico a antes da
// extração livre existir.
async function prepararPerguntaTemProcesso(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  if (state.temProcesso !== undefined) return {};
  return prepararPergunta("temProcesso", "Você tem o número do processo da pessoa que está presa?");
}

async function pedirTemProcesso(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  if (state.temProcesso !== undefined) return {};
  // resume:boolean quebra no LangGraph quando o valor é `false` (bug real:
  // graph.invoke() trata resume falsy como "nenhum resume" — Command({resume:
  // false}) explode com "Received empty Command input"). Resume como string
  // "true"/"false" (a Tykhe manda literal isso, não texto em português).
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Você tem o número do processo da pessoa que está presa?",
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  return { temProcesso: respostaEhSim(resposta) };
}

async function prepararPerguntaNumeroProcesso(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  if (state.numeroProcesso !== undefined) return {};
  return prepararPergunta("numeroProcesso", "Qual o número do processo? Informe apenas os números.");
}

async function pedirNumeroProcesso(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  if (state.numeroProcesso !== undefined) return {};
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Qual o número do processo? Informe apenas os números.",
    tipo: "texto",
  });
  return { numeroProcesso: resposta };
}

// Consulta o processo no Verde logo depois de coletar o número — informativo,
// não trava o fluxo (diferente do RG/apenado, que tem retry e gate de
// confirmação). Erro ou não encontrado só fica em dadosProcesso.encontrado,
// segue pra pergunta do RG normalmente de qualquer jeito.
async function consultarProcesso(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  const dados = await consultarProcessoVerde(state.numeroProcesso ?? "");
  return { dadosProcesso: dados };
}

// rg é reescrito a cada volta do retry loop (pedirRg roda de novo quando
// tentativasRg>=1, ver perguntaTentarNovamente/depoisDePerguntaTentar) — um
// bypass ingênuo tipo "if state.rg definido, pula" quebraria o retry (rg da
// tentativa anterior, que FALHOU, faria pular a próxima pergunta). Bypass só
// vale na tentativa 0 (RG ainda não tentado nenhuma vez) — é o único caso
// em que "rg definido" significa "veio da extração", não "tentativa anterior".
function rgVeioDaExtracao(state: PessoaPresaStateType): boolean {
  return state.rg !== undefined && (state.tentativasRg ?? 0) === 0;
}

async function prepararPerguntaRg(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  if (rgVeioDaExtracao(state)) return {};
  return prepararPergunta("rg", "Qual o RG da pessoa presa? Informe apenas os números.");
}

async function pedirRg(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  if (rgVeioDaExtracao(state)) return {};
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Qual o RG da pessoa presa? Informe apenas os números.",
    tipo: "texto",
  });
  return { rg: resposta };
}

function depoisDeTemProcesso(state: PessoaPresaStateType): "pedirNumeroProcesso" | "pedirRg" {
  return state.temProcesso ? "pedirNumeroProcesso" : "pedirRg";
}

// Valida o FORMATO do RG antes de gastar uma chamada no Verde — só dígitos
// (o mesmo texto da pergunta já pede "apenas os números"). Diferente do
// retry de "RG não encontrado" (tentativasRg/perguntaTentarNovamente,
// abaixo): aqui nunca chegou a consultar nada, é rejeição local.
const RgSchema = z.string().trim().regex(/^\d+$/);

function rgFormatoValido(rg: string): boolean {
  return RgSchema.safeParse(rg).success;
}

function depoisDePedirRg(state: PessoaPresaStateType): "valido" | "invalido" {
  return rgFormatoValido(state.rg ?? "") ? "valido" : "invalido";
}

// Limpa `rg` de volta pra undefined antes de perguntar de novo — sem isso,
// rgVeioDaExtracao (acima) veria rg definido (o valor inválido) na tentativa
// 0 e pularia a pergunta de novo, achando que "veio da extração".
async function prepararPerguntaRgInvalido(): Promise<Partial<PessoaPresaStateType>> {
  const preparado = await prepararPergunta(
    "rgInvalido",
    "O RG deve conter apenas números. Qual o RG da pessoa presa? Informe apenas os números."
  );
  return { ...preparado, rg: undefined };
}

async function consultarApenado(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  const dados = await consultarApenadoPorRg(state.rg ?? "");
  return { dadosApenado: dados, tentativasRg: (state.tentativasRg ?? 0) + 1 };
}

// 3 tentativas de RG no total. Não encontrado com tentativa < 3: pergunta se
// quer tentar de novo (perguntaTentarNovamente). Na 3ª falha, esgotou —
// direto pro atendente, sem perguntar de novo (não sobra tentativa).
function depoisDeConsultarApenado(state: PessoaPresaStateType): "pedirConfirmaNome" | "perguntaTentarNovamente" | "naoConfirmado" {
  if (state.dadosApenado?.encontrado) return "pedirConfirmaNome";
  if ((state.tentativasRg ?? 0) >= 3) return "naoConfirmado";
  return "perguntaTentarNovamente";
}

async function prepararPerguntaTentarNovamente(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  return prepararPergunta(
    "tentarNovamenteRg",
    `Não encontrei ninguém com esse RG (tentativa ${state.tentativasRg ?? 1} de 3). Quer tentar de novo?`
  );
}

// Issue #54 — achado ao vivo (relato real via WhatsApp/Tykhe): a pessoa às
// vezes pula a confirmação "quer tentar de novo?" e já manda o RG novo
// direto. Reconhece isso pelo FORMATO (mesma validação de pedirRg, só
// dígitos) — trata como "sim" e já usa o valor como RG, sem perguntar "qual
// o RG?" de novo (depoisDePerguntaTentar pula direto pra consultarApenado).
async function perguntaTentarNovamente(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta:
      state.perguntaAtualTexto ??
      `Não encontrei ninguém com esse RG (tentativa ${state.tentativasRg ?? 1} de 3). Quer tentar de novo?`,
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  if (rgFormatoValido(resposta)) {
    return { querTentarNovamente: true, rg: resposta, digitouRgDireto: true };
  }
  return { querTentarNovamente: respostaEhSim(resposta), digitouRgDireto: false };
}

function depoisDePerguntaTentar(state: PessoaPresaStateType): "pedirRg" | "naoConfirmado" | "consultarApenado" {
  if (!state.querTentarNovamente) return "naoConfirmado";
  return state.digitouRgDireto ? "consultarApenado" : "pedirRg";
}

async function prepararPerguntaConfirmaNome(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  const nome = state.dadosApenado?.nome ?? "essa pessoa";
  return prepararPergunta("confirmaNome", `Confirma que a pessoa presa é ${nome}?`);
}

async function pedirConfirmaNome(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  const nome = state.dadosApenado?.nome ?? "essa pessoa";
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? `Confirma que a pessoa presa é ${nome}?`,
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  return { confirmaNome: respostaEhSim(resposta) };
}

async function prepararPerguntaParentesco(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  if (state.parentesco !== undefined) return {};
  return prepararPergunta("parentesco", "Qual seu parentesco com a pessoa presa?");
}

// Issue #17 — lista fechada de parentescos, validada com o negócio.
const PARENTESCOS_PERMITIDOS = [
  "Mãe",
  "Pai",
  "Irmão(a)",
  "Esposo(a)",
  "Ex-esposo(a)",
  "Companheiro(a)",
  "Filho(a)",
  "Amigo(a)",
  "Primo(a)",
  "Tio(a)",
  "Sobrinho(a)",
  "Avô/Avó",
  "Cunhado(a)",
  "Sogro(a)",
  "Outro",
];

interface ResultadoClassificarParentesco {
  parentesco: string;
  // ausentes quando viaIA:false (NODE_ENV=test) — mesma convenção do resto
  // do repo (issue #34/#35/#69), sem isso tokensGastosTotal não contabiliza
  // o custo real dessa chamada.
  tokensTotal?: number;
  tokensEntrada?: number;
  tokensSaida?: number;
}

// Classifica o relato livre contra a lista fechada acima — mesmo módulo
// reaproveitável do orquestrador (issue #8/#17). Sem match com confiança
// suficiente, cai em "Outro" (nunca guarda o texto cru em metadados.parentesco).
// Guard de teste próprio (mesmo padrão de ia/classificarFluxos.ts) — ia/classificar.ts
// não tem guard embutido, cada chamador cuida do próprio mock.
async function classificarParentesco(respostaLivre: string): Promise<ResultadoClassificarParentesco> {
  if (process.env.NODE_ENV === "test") {
    return { parentesco: process.env.MOCK_CLASSIFICACAO_PARENTESCO ?? "Outro" };
  }
  const sistema = `Você classifica o parentesco de quem busca informação sobre uma pessoa presa, na Defensoria Pública do RJ, a partir de um relato livre.
Parentescos possíveis: ${PARENTESCOS_PERMITIDOS.join(", ")}.
Regras: escolha o que melhor descreve a relação, mesmo que o relato seja indireto (ex: "fui casada com ele mas já nos divorciamos" → "Ex-esposo(a)"). Se não bater com confiança em nenhum, responda "nenhum".`;
  const { escolhaId, tokensTotal, tokensEntrada, tokensSaida } = await classificarEntreOpcoes(respostaLivre, sistema, PARENTESCOS_PERMITIDOS);
  return { parentesco: escolhaId ?? "Outro", tokensTotal, tokensEntrada, tokensSaida };
}

export async function pedirParentesco(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  if (state.parentesco !== undefined) return {};
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Qual seu parentesco com a pessoa presa?",
    tipo: "texto",
  });
  const { parentesco, tokensTotal, tokensEntrada, tokensSaida } = await classificarParentesco(resposta);
  return {
    parentesco,
    tokensGastos: { input: tokensEntrada ?? 0, output: tokensSaida ?? 0, total: tokensTotal ?? 0 },
  };
}

// Issue #49 — sem o número do processo, o atendimento coletou RG/nome/
// parentesco mas não tem como confirmar/acompanhar a situação processual de
// verdade. Marcar como "concluido" nesse caso passava a impressão de que
// resolveu o que a pessoa precisava; vira handoff_humano em vez disso.
//
// Issue #51 — mesma ideia, mas pro caso COM número do processo: só origem
// SEEU é considerada "resolvida" pelo bot. Processo não encontrado na
// consulta (dadosProcesso.origem ausente) cai no mesmo handoff — comparação
// exata contra ORIGEM_PROCESSO_SUPORTADA cobre os 2 casos (origem diferente
// e origem ausente) sem precisar de checagem separada.
async function concluir(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  if (state.temProcesso === false) {
    return { statusFinal: "handoff_humano", motivoHandoff: "sem_numero_processo", mensagemFinal: MENSAGEM_HANDOFF_SEM_NUMERO_PROCESSO };
  }
  if (state.dadosProcesso?.origem !== ORIGEM_PROCESSO_SUPORTADA) {
    return { statusFinal: "handoff_humano", motivoHandoff: "origem_processo_nao_suportada", mensagemFinal: MENSAGEM_HANDOFF_ORIGEM_NAO_SUPORTADA };
  }
  if (!dadosApenadoAtendidos(state)) {
    // Sem mensagem fixa de propósito (decisão 2026-09-16) — só o status
    // importa aqui, usa o texto genérico de handoff que o fluxo já tem.
    return { statusFinal: "handoff_humano", motivoHandoff: "dados_pessoa_nao_atendidos" };
  }
  return { statusFinal: "concluido" };
}

// naoConfirmado é o dead-end compartilhado por 2 caminhos diferentes:
// esgotou as 3 tentativas de RG (dadosApenado nunca encontrado) ou achou a
// pessoa mas não confirmou o nome. O motivo não vem por parâmetro (LangGraph
// não passa argumento extra pro nó, só o state) — dá pra deduzir olhando o
// que já está no estado: se NÃO achou ninguém, é falta de RG; se achou mas
// confirmaNome é false, é nome não confirmado.
async function naoConfirmado(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  const motivoHandoff = state.dadosApenado?.encontrado ? "nome_nao_confirmado" : "rg_nao_encontrado";
  return { statusFinal: "handoff_humano", motivoHandoff };
}

function depoisDeConfirmarNome(state: PessoaPresaStateType): "concluir" | "naoConfirmado" {
  return state.confirmaNome ? "concluir" : "naoConfirmado";
}

// Issue #183 — depois de confirmar o preso e o parentesco, identifica o
// ASSISTIDO (quem está conversando) no Verde via CPF, mesmo racional de
// violenciaDomestica/graph.ts (issue #171). Subgrafo embutido abaixo (ver
// `grafo` no fim do arquivo).
function depoisDeIdentificarAssistido(state: PessoaPresaStateType): "encontrado" | "cadastrar" {
  return state.dadosPessoa?.encontrado ? "encontrado" : "cadastrar";
}

// Issue #183 — subgrafo cadastroPessoa (embutido abaixo) preenche
// dadosPessoa (sucesso, mesmo campo de quem já tinha cadastro) ou
// cadastroErro (falha) — nunca os dois.
function depoisDeCadastrarPessoa(state: PessoaPresaStateType): "continuar" | "falhou" {
  return state.dadosPessoa?.encontrado ? "continuar" : "falhou";
}

async function falhaCadastro(state: PessoaPresaStateType): Promise<Partial<PessoaPresaStateType>> {
  return {
    statusFinal: "handoff_humano",
    motivoHandoff: "falha_cadastro",
    mensagemFinal: state.cadastroErro ? `${MENSAGEM_FALHA_CADASTRO} (${state.cadastroErro})` : MENSAGEM_FALHA_CADASTRO,
  };
}

const grafo = new StateGraph(PessoaPresaState)
  .addNode("prepararPerguntaLivre", prepararPerguntaLivre)
  .addNode("pedirLivre", pedirLivre)
  .addNode("prepararPerguntaTemProcesso", prepararPerguntaTemProcesso)
  .addNode("pedirTemProcesso", pedirTemProcesso)
  .addNode("prepararPerguntaNumeroProcesso", prepararPerguntaNumeroProcesso)
  .addNode("pedirNumeroProcesso", pedirNumeroProcesso)
  .addNode("consultarProcesso", consultarProcesso)
  .addNode("prepararPerguntaRg", prepararPerguntaRg)
  .addNode("pedirRg", pedirRg)
  .addNode("prepararPerguntaRgInvalido", prepararPerguntaRgInvalido)
  .addNode("consultarApenado", consultarApenado)
  .addNode("prepararPerguntaTentarNovamente", prepararPerguntaTentarNovamente)
  .addNode("perguntaTentarNovamente", perguntaTentarNovamente)
  .addNode("prepararPerguntaConfirmaNome", prepararPerguntaConfirmaNome)
  .addNode("pedirConfirmaNome", pedirConfirmaNome)
  .addNode("prepararPerguntaParentesco", prepararPerguntaParentesco)
  .addNode("pedirParentesco", pedirParentesco)
  .addNode("identificarAssistido", subgrafoIdentificarAssistido)
  .addNode("cadastroPessoa", subgrafoCadastroPessoa)
  .addNode("falhaCadastro", falhaCadastro)
  .addNode("concluir", concluir)
  .addNode("naoConfirmado", naoConfirmado)
  // Roteamento condicional (não .addEdge fixo) é o que garante que, com a
  // extração desligada (padrão), o grafo nem entra no ramo novo — vai direto
  // pra prepararPerguntaTemProcesso, exatamente como antes dessa feature.
  .addConditionalEdges(START, roteamentoInicial, {
    comExtracao: "prepararPerguntaLivre",
    semExtracao: "prepararPerguntaTemProcesso",
  })
  .addEdge("prepararPerguntaLivre", "pedirLivre")
  .addEdge("pedirLivre", "prepararPerguntaTemProcesso")
  .addEdge("prepararPerguntaTemProcesso", "pedirTemProcesso")
  .addConditionalEdges("pedirTemProcesso", depoisDeTemProcesso, {
    pedirNumeroProcesso: "prepararPerguntaNumeroProcesso",
    pedirRg: "prepararPerguntaRg",
  })
  .addEdge("prepararPerguntaNumeroProcesso", "pedirNumeroProcesso")
  .addEdge("pedirNumeroProcesso", "consultarProcesso")
  .addEdge("consultarProcesso", "prepararPerguntaRg")
  .addEdge("prepararPerguntaRg", "pedirRg")
  .addConditionalEdges("pedirRg", depoisDePedirRg, {
    valido: "consultarApenado",
    invalido: "prepararPerguntaRgInvalido",
  })
  .addEdge("prepararPerguntaRgInvalido", "pedirRg")
  .addConditionalEdges("consultarApenado", depoisDeConsultarApenado, {
    pedirConfirmaNome: "prepararPerguntaConfirmaNome",
    perguntaTentarNovamente: "prepararPerguntaTentarNovamente",
    naoConfirmado: "naoConfirmado",
  })
  .addEdge("prepararPerguntaTentarNovamente", "perguntaTentarNovamente")
  .addConditionalEdges("perguntaTentarNovamente", depoisDePerguntaTentar, {
    pedirRg: "prepararPerguntaRg",
    naoConfirmado: "naoConfirmado",
    // RG digitado direto na confirmação (issue #54) — pula prepararPerguntaRg
    // (não pergunta "qual o RG?" de novo), vai direto pra consulta no Verde.
    consultarApenado: "consultarApenado",
  })
  .addEdge("prepararPerguntaConfirmaNome", "pedirConfirmaNome")
  .addConditionalEdges("pedirConfirmaNome", depoisDeConfirmarNome, {
    concluir: "prepararPerguntaParentesco",
    naoConfirmado: "naoConfirmado",
  })
  .addEdge("prepararPerguntaParentesco", "pedirParentesco")
  .addEdge("pedirParentesco", "identificarAssistido")
  .addConditionalEdges("identificarAssistido", depoisDeIdentificarAssistido, {
    encontrado: "concluir",
    cadastrar: "cadastroPessoa",
  })
  .addConditionalEdges("cadastroPessoa", depoisDeCadastrarPessoa, {
    continuar: "concluir",
    falhou: "falhaCadastro",
  })
  .addEdge("falhaCadastro", END)
  .addEdge("naoConfirmado", END)
  .addEdge("concluir", END)
  .compile({ checkpointer: await criarCheckpointer() });

export { grafo };
