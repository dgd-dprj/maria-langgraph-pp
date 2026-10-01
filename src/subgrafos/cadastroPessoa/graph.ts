import { interrupt, StateGraph, START, END } from "@langchain/langgraph";
import { type CadastroPessoaStateType, CadastroPessoaState } from "./state.js";
import type { Pergunta } from "../../shared/types.js";
import { cadastrarPessoa as cadastrarPessoaVerde } from "../../integracoes/verde.js";
import { prepararPergunta } from "../../ia/reescrever.js";
import { grafo as subgrafoColetarEndereco } from "../coletarEndereco/graph.js";

// Issue #171 — subgrafo reaproveitável: cadastra a pessoa no Verde
// (POST /integra/pessoa) quando o CPF informado não tem cadastro ainda.
// Só pede o que falta pro cadastro (nome, data de nascimento) — CPF já foi
// coletado antes pelo fluxo pai (subgrafo identificarAssistido), nunca
// perguntado de novo aqui. Escopo restrito aos 3 campos obrigatórios do
// CadastrarPessoaDTO por decisão registrada na issue — endereço/telefone/
// email/gênero/representante ficam pra melhoria futura.

async function prepararPerguntaNome(): Promise<Partial<CadastroPessoaStateType>> {
  return prepararPergunta("nome", "Não encontrei seu cadastro no sistema. Pra criar um novo, qual o seu nome completo?");
}

async function pedirNome(state: CadastroPessoaStateType): Promise<Partial<CadastroPessoaStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Não encontrei seu cadastro no sistema. Pra criar um novo, qual o seu nome completo?",
    tipo: "texto",
  });
  return { nome: resposta };
}

async function prepararPerguntaDataNascimento(): Promise<Partial<CadastroPessoaStateType>> {
  return prepararPergunta("dataNascimento", "Qual a sua data de nascimento? (dd/mm/aaaa)");
}

async function pedirDataNascimento(state: CadastroPessoaStateType): Promise<Partial<CadastroPessoaStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Qual a sua data de nascimento? (dd/mm/aaaa)",
    tipo: "texto",
  });
  return { dataNascimento: resposta };
}

function respostaEhSim(resposta: string): boolean {
  const normalizado = resposta
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim()
    .toLowerCase();
  return normalizado === "true" || normalizado === "sim" || normalizado === "s" || normalizado === "yes";
}

async function cadastrarPessoa(state: CadastroPessoaStateType): Promise<Partial<CadastroPessoaStateType>> {
  const resultado = await cadastrarPessoaVerde({
    nome: state.nome ?? "",
    cpf: state.cpf ?? "",
    dataNascimento: state.dataNascimento ?? "",
    // Issue #176 — coletado pelo subgrafo coletarEndereco (embutido abaixo)
    // antes de chegar aqui. Sem endereço, a pessoa cadastrada pode não ter
    // órgão disponível na consulta de violência doméstica mesmo em casos
    // que teriam fallback com endereço presente (achado ao vivo, issue #171).
    endereco: state.endereco,
  });
  if (!resultado.sucesso) return { cadastroErro: resultado.erro ?? "erro desconhecido" };
  // Mesmo campo/shape que identificarAssistido já preenche quando encontra
  // de primeira — o fluxo pai não precisa saber se a pessoa já existia ou
  // acabou de ser cadastrada, o resto do fluxo é idêntico nos 2 casos.
  return { dadosPessoa: { encontrado: true, idPessoa: resultado.idPessoa, nome: state.nome } };
}

function depoisDeCadastrar(state: CadastroPessoaStateType): "sucesso" | "falhou" {
  return state.cadastroErro !== undefined ? "falhou" : "sucesso";
}

// Issue #189 — cadastro com sucesso não sai direto: confirma os dados
// antes de devolver pro fluxo pai (mesmo racional de identificarAssistido).
// Issue #191 — só pergunta quando veio do orquestrador (mesmo racional de
// identificarAssistido/graph.ts).
async function prepararPerguntaConfirmaAssistido(state: CadastroPessoaStateType): Promise<Partial<CadastroPessoaStateType>> {
  if (!state.viaOrquestrador) return {};
  const nome = state.dadosPessoa?.nome ?? "você";
  return prepararPergunta("confirmaAssistido", `Confirma que seus dados são: ${nome}?`);
}

async function pedirConfirmaAssistido(state: CadastroPessoaStateType): Promise<Partial<CadastroPessoaStateType>> {
  if (!state.viaOrquestrador) return {};
  const nome = state.dadosPessoa?.nome ?? "você";
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? `Confirma que seus dados são: ${nome}?`,
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  return { confirmaAssistido: respostaEhSim(resposta) };
}

const grafo = new StateGraph(CadastroPessoaState)
  .addNode("prepararPerguntaNome", prepararPerguntaNome)
  .addNode("pedirNome", pedirNome)
  .addNode("prepararPerguntaDataNascimento", prepararPerguntaDataNascimento)
  .addNode("pedirDataNascimento", pedirDataNascimento)
  // Issue #176 — subgrafo aninhado (subgrafo dentro de subgrafo, LangGraph
  // suporta níveis arbitrários). Sem ele, cadastro ficava sem endereço —
  // achado ao vivo que pessoa recém-cadastrada sem endereço não acha órgão
  // de violência doméstica mesmo em casos que teriam fallback.
  .addNode("coletarEndereco", subgrafoColetarEndereco)
  .addNode("cadastrarPessoa", cadastrarPessoa)
  .addNode("prepararPerguntaConfirmaAssistido", prepararPerguntaConfirmaAssistido)
  .addNode("pedirConfirmaAssistido", pedirConfirmaAssistido)
  .addEdge(START, "prepararPerguntaNome")
  .addEdge("prepararPerguntaNome", "pedirNome")
  .addEdge("pedirNome", "prepararPerguntaDataNascimento")
  .addEdge("prepararPerguntaDataNascimento", "pedirDataNascimento")
  .addEdge("pedirDataNascimento", "coletarEndereco")
  .addEdge("coletarEndereco", "cadastrarPessoa")
  .addConditionalEdges("cadastrarPessoa", depoisDeCadastrar, {
    sucesso: "prepararPerguntaConfirmaAssistido",
    falhou: END,
  })
  .addEdge("prepararPerguntaConfirmaAssistido", "pedirConfirmaAssistido")
  .addEdge("pedirConfirmaAssistido", END)
  // Sem checkpointer próprio — mesmo racional de subgrafos/identificarAssistido.
  .compile();

export { grafo };
