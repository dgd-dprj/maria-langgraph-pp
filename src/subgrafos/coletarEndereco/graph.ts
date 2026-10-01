import { interrupt, StateGraph, START, END } from "@langchain/langgraph";
import { type ColetarEnderecoStateType, ColetarEnderecoState } from "./state.js";
import type { Pergunta } from "../../shared/types.js";
import { consultarCep as consultarCepVerde } from "../../integracoes/verde.js";
import { prepararPergunta } from "../../ia/reescrever.js";

// Issue #176 — subgrafo reaproveitável: coleta os campos de endereço do
// CadastrarPessoaDTO (POST /integra/pessoa) — logradouro, número,
// complemento, CEP, bairro, município, UF.
//
// GET /cep/{cep} (verde.ts::consultarCep) devolve logradouro/bairro/
// município/UF em TEXTO quando a Verde tem cadastrado pra aquele CEP — não
// é garantido pra todo CEP (achado ao vivo, issue #127: alguns CEPs vêm
// incompletos, só uf populado), mas quando vem, evita perguntar de novo
// (mesmo racional de bypass usado em identificarAssistido pro CPF vindo de
// dadosConhecidos). `numero` nunca vem do CEP (é específico do imóvel, CEP é
// da rua toda) — sempre perguntado. `complemento` é sempre perguntado e
// sempre opcional (nem todo endereço tem).

async function prepararPerguntaCep(): Promise<Partial<ColetarEnderecoStateType>> {
  return prepararPergunta("cep", "Qual o CEP do seu endereço?");
}

async function pedirCep(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  const resposta = interrupt<Pergunta, string>({ pergunta: state.perguntaAtualTexto ?? "Qual o CEP do seu endereço?", tipo: "texto" });
  return { cep: resposta };
}

async function consultarCep(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  const dados = await consultarCepVerde(state.cep ?? "");
  if (!dados.encontrado) return {};
  return {
    logradouro: dados.logradouro,
    bairro: dados.bairro,
    municipio: dados.municipio,
    uf: dados.uf,
  };
}

// Bypass: só pergunta o que o CEP não trouxe — mesmo padrão de
// cpfVeioDeDadosConhecidos em subgrafos/identificarAssistido/graph.ts.
async function prepararPerguntaLogradouro(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  if (state.logradouro !== undefined) return {};
  return prepararPergunta("logradouro", "Qual o nome da rua/avenida?");
}

async function pedirLogradouro(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  if (state.logradouro !== undefined) return {};
  const resposta = interrupt<Pergunta, string>({ pergunta: state.perguntaAtualTexto ?? "Qual o nome da rua/avenida?", tipo: "texto" });
  return { logradouro: resposta };
}

async function prepararPerguntaNumero(): Promise<Partial<ColetarEnderecoStateType>> {
  return prepararPergunta("numero", "Qual o número?");
}

async function pedirNumero(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  const resposta = interrupt<Pergunta, string>({ pergunta: state.perguntaAtualTexto ?? "Qual o número?", tipo: "texto" });
  return { numero: resposta };
}

async function prepararPerguntaComplemento(): Promise<Partial<ColetarEnderecoStateType>> {
  return prepararPergunta("complemento", "Tem complemento (apartamento, bloco, etc)? Se não tiver, pode responder \"não\".");
}

async function pedirComplemento(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Tem complemento (apartamento, bloco, etc)? Se não tiver, pode responder \"não\".",
    tipo: "texto",
  });
  const normalizado = resposta.trim().toLowerCase();
  const semComplemento = normalizado === "não" || normalizado === "nao" || normalizado === "n" || normalizado === "";
  return { complemento: semComplemento ? undefined : resposta };
}

async function prepararPerguntaBairro(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  if (state.bairro !== undefined) return {};
  return prepararPergunta("bairro", "Qual o bairro?");
}

async function pedirBairro(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  if (state.bairro !== undefined) return {};
  const resposta = interrupt<Pergunta, string>({ pergunta: state.perguntaAtualTexto ?? "Qual o bairro?", tipo: "texto" });
  return { bairro: resposta };
}

async function prepararPerguntaMunicipio(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  if (state.municipio !== undefined) return {};
  return prepararPergunta("municipio", "Qual o município?");
}

async function pedirMunicipio(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  if (state.municipio !== undefined) return {};
  const resposta = interrupt<Pergunta, string>({ pergunta: state.perguntaAtualTexto ?? "Qual o município?", tipo: "texto" });
  return { municipio: resposta };
}

async function prepararPerguntaUf(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  if (state.uf !== undefined) return {};
  return prepararPergunta("uf", "Qual o estado (UF, ex: RJ)?");
}

async function pedirUf(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  if (state.uf !== undefined) return {};
  const resposta = interrupt<Pergunta, string>({ pergunta: state.perguntaAtualTexto ?? "Qual o estado (UF, ex: RJ)?", tipo: "texto" });
  return { uf: resposta.trim().toUpperCase() };
}

async function montarEndereco(state: ColetarEnderecoStateType): Promise<Partial<ColetarEnderecoStateType>> {
  return {
    endereco: {
      cep: state.cep,
      logradouro: state.logradouro,
      numero: state.numero,
      complemento: state.complemento,
      bairro: state.bairro,
      municipio: state.municipio,
      uf: state.uf,
    },
  };
}

const grafo = new StateGraph(ColetarEnderecoState)
  .addNode("prepararPerguntaCep", prepararPerguntaCep)
  .addNode("pedirCep", pedirCep)
  .addNode("consultarCep", consultarCep)
  .addNode("prepararPerguntaLogradouro", prepararPerguntaLogradouro)
  .addNode("pedirLogradouro", pedirLogradouro)
  .addNode("prepararPerguntaNumero", prepararPerguntaNumero)
  .addNode("pedirNumero", pedirNumero)
  .addNode("prepararPerguntaComplemento", prepararPerguntaComplemento)
  .addNode("pedirComplemento", pedirComplemento)
  .addNode("prepararPerguntaBairro", prepararPerguntaBairro)
  .addNode("pedirBairro", pedirBairro)
  .addNode("prepararPerguntaMunicipio", prepararPerguntaMunicipio)
  .addNode("pedirMunicipio", pedirMunicipio)
  .addNode("prepararPerguntaUf", prepararPerguntaUf)
  .addNode("pedirUf", pedirUf)
  .addNode("montarEndereco", montarEndereco)
  .addEdge(START, "prepararPerguntaCep")
  .addEdge("prepararPerguntaCep", "pedirCep")
  .addEdge("pedirCep", "consultarCep")
  .addEdge("consultarCep", "prepararPerguntaLogradouro")
  .addEdge("prepararPerguntaLogradouro", "pedirLogradouro")
  .addEdge("pedirLogradouro", "prepararPerguntaNumero")
  .addEdge("prepararPerguntaNumero", "pedirNumero")
  .addEdge("pedirNumero", "prepararPerguntaComplemento")
  .addEdge("prepararPerguntaComplemento", "pedirComplemento")
  .addEdge("pedirComplemento", "prepararPerguntaBairro")
  .addEdge("prepararPerguntaBairro", "pedirBairro")
  .addEdge("pedirBairro", "prepararPerguntaMunicipio")
  .addEdge("prepararPerguntaMunicipio", "pedirMunicipio")
  .addEdge("pedirMunicipio", "prepararPerguntaUf")
  .addEdge("prepararPerguntaUf", "pedirUf")
  .addEdge("pedirUf", "montarEndereco")
  .addEdge("montarEndereco", END)
  // Sem checkpointer próprio — mesmo racional dos outros subgrafos (issue #171).
  .compile();

export { grafo };
