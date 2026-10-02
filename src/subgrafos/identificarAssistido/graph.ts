import { interrupt, StateGraph, START, END } from "@langchain/langgraph";
import { type IdentificarAssistidoStateType, IdentificarAssistidoState } from "./state.js";
import type { Pergunta } from "../../shared/types.js";
import { consultarPessoaPorCpf } from "../../integracoes/verde.js";
import { prepararPergunta } from "../../ia/reescrever.js";

// Issue #171 — subgrafo reaproveitável: pergunta CPF, consulta o Verde, dá
// até 3 tentativas antes de desistir. Termina em 3 desfechos possíveis (o
// grafo pai decide o que fazer com cada um, olhando `dadosPessoa.encontrado`
// e `confirmaAssistido` depois que esse subgrafo retornar):
// - encontrado e confirmado: dadosPessoa.encontrado === true, confirmaAssistido === true
// - encontrado mas NÃO confirmado (issue #189): dadosPessoa.encontrado === true, confirmaAssistido === false
// - esgotado: dadosPessoa.encontrado === false, 3 tentativas usadas (confirmaAssistido nunca chega a ser perguntado)
// Nenhum dos três vira handoff AQUI — isso é responsabilidade de quem
// embute este subgrafo (cada fluxo pai decide, ex: violenciaDomestica manda
// pro subgrafo cadastroPessoa quando esgota, e pro handoff direto quando
// não confirmado).

function cpfFormatoValido(valor: string): boolean {
  return valor.replace(/\D/g, "").length === 11;
}

function respostaEhSim(resposta: string): boolean {
  const normalizado = resposta
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim()
    .toLowerCase();
  return normalizado === "true" || normalizado === "sim" || normalizado === "s" || normalizado === "yes";
}

// Bypass só vale na tentativa 0 (mesmo racional de rgVeioDaExtracao em
// pessoaPresa/graph.ts) — sem o check de tentativasCpf, um retry reusaria o
// CPF da tentativa anterior (que FALHOU) em vez de perguntar de novo.
function cpfVeioDeDadosConhecidos(state: IdentificarAssistidoStateType): boolean {
  return state.cpf !== undefined && (state.tentativasCpf ?? 0) === 0;
}

async function prepararPerguntaCpf(state: IdentificarAssistidoStateType): Promise<Partial<IdentificarAssistidoStateType>> {
  if (cpfVeioDeDadosConhecidos(state)) return {};
  return prepararPergunta("cpf", "Qual o seu CPF? Informe apenas os números.");
}

async function pedirCpf(state: IdentificarAssistidoStateType): Promise<Partial<IdentificarAssistidoStateType>> {
  if (cpfVeioDeDadosConhecidos(state)) return {};
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Qual o seu CPF? Informe apenas os números.",
    tipo: "texto",
  });
  return { cpf: resposta };
}

async function consultarPessoa(state: IdentificarAssistidoStateType): Promise<Partial<IdentificarAssistidoStateType>> {
  const dados = await consultarPessoaPorCpf(state.cpf ?? "");
  return { dadosPessoa: dados, tentativasCpf: (state.tentativasCpf ?? 0) + 1 };
}

// Issue #172 — falhaInfra (401/403/5xx esgotado, retry automático já
// tentado dentro de consultarPessoaPorCpf) sai direto, SEM passar pelo
// retry de negócio "quer tentar de novo?" — o grafo pai distingue esse
// desfecho de "esgotado de verdade" olhando dadosPessoa.falhaInfra, e NÃO
// tenta cadastroPessoa em cima disso (não é "pessoa sem cadastro", é "não
// consegui nem verificar").
function depoisDeConsultarPessoa(state: IdentificarAssistidoStateType): "encontrado" | "tentarNovamente" | "esgotado" {
  if (state.dadosPessoa?.encontrado) return "encontrado";
  if (state.dadosPessoa?.falhaInfra) return "esgotado";
  return (state.tentativasCpf ?? 0) >= 3 ? "esgotado" : "tentarNovamente";
}

async function prepararPerguntaTentarNovamenteCpf(state: IdentificarAssistidoStateType): Promise<Partial<IdentificarAssistidoStateType>> {
  return prepararPergunta("tentarNovamenteCpf", `Não encontrei ninguém com esse CPF (tentativa ${state.tentativasCpf ?? 1} de 3). Quer tentar de novo?`);
}

async function perguntaTentarNovamenteCpf(state: IdentificarAssistidoStateType): Promise<Partial<IdentificarAssistidoStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? `Não encontrei ninguém com esse CPF (tentativa ${state.tentativasCpf ?? 1} de 3). Quer tentar de novo?`,
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  if (cpfFormatoValido(resposta)) {
    return { querTentarNovamenteCpf: true, cpf: resposta, digitouCpfDireto: true };
  }
  return { querTentarNovamenteCpf: respostaEhSim(resposta), digitouCpfDireto: false };
}

function depoisDePerguntaTentarCpf(state: IdentificarAssistidoStateType): "pedirCpf" | "esgotado" | "consultarPessoa" {
  if (!state.querTentarNovamenteCpf) return "esgotado";
  return state.digitouCpfDireto ? "consultarPessoa" : "pedirCpf";
}

// Issue #189 — CPF encontrado não sai direto: confirma os dados achados
// antes de devolver pro fluxo pai (mesmo racional do "Confirma que a
// pessoa presa é <nome>?" já usado pro RG em pessoaPresa/graph.ts).
// Issue #191 — só pergunta quando veio do orquestrador; chamada direta da
// Tykhe (POST /atendimentos, sem esse flag) nunca ganha essa pergunta.
async function prepararPerguntaConfirmaAssistido(state: IdentificarAssistidoStateType): Promise<Partial<IdentificarAssistidoStateType>> {
  if (!state.viaOrquestrador) return {};
  const nome = state.dadosPessoa?.nome ?? "você";
  return prepararPergunta("confirmaAssistido", `Confirma que seus dados são: ${nome}?`);
}

async function pedirConfirmaAssistido(state: IdentificarAssistidoStateType): Promise<Partial<IdentificarAssistidoStateType>> {
  if (!state.viaOrquestrador) return {};
  const nome = state.dadosPessoa?.nome ?? "você";
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? `Confirma que seus dados são: ${nome}?`,
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  return { confirmaAssistido: respostaEhSim(resposta) };
}

const grafo = new StateGraph(IdentificarAssistidoState)
  .addNode("prepararPerguntaCpf", prepararPerguntaCpf)
  .addNode("pedirCpf", pedirCpf)
  .addNode("consultarPessoa", consultarPessoa)
  .addNode("prepararPerguntaTentarNovamenteCpf", prepararPerguntaTentarNovamenteCpf)
  .addNode("perguntaTentarNovamenteCpf", perguntaTentarNovamenteCpf)
  .addNode("prepararPerguntaConfirmaAssistido", prepararPerguntaConfirmaAssistido)
  .addNode("pedirConfirmaAssistido", pedirConfirmaAssistido)
  .addEdge(START, "prepararPerguntaCpf")
  .addEdge("prepararPerguntaCpf", "pedirCpf")
  .addEdge("pedirCpf", "consultarPessoa")
  .addConditionalEdges("consultarPessoa", depoisDeConsultarPessoa, {
    encontrado: "prepararPerguntaConfirmaAssistido",
    esgotado: END,
    tentarNovamente: "prepararPerguntaTentarNovamenteCpf",
  })
  .addEdge("prepararPerguntaTentarNovamenteCpf", "perguntaTentarNovamenteCpf")
  .addConditionalEdges("perguntaTentarNovamenteCpf", depoisDePerguntaTentarCpf, {
    pedirCpf: "prepararPerguntaCpf",
    esgotado: END,
    // CPF digitado direto na pergunta de retry — pula prepararPerguntaCpf,
    // consulta o Verde de novo direto.
    consultarPessoa: "consultarPessoa",
  })
  .addEdge("prepararPerguntaConfirmaAssistido", "pedirConfirmaAssistido")
  .addEdge("pedirConfirmaAssistido", END)
  // Sem checkpointer próprio — subgrafo embutido como nó num fluxo pai
  // (fluxos/violenciaDomestica/graph.ts) herda a persistência do checkpointer
  // do PAI. Passar um checkpointer aqui criaria uma 2ª camada de persistência
  // desconectada do thread_id real da conversa.
  .compile();

export { grafo };
