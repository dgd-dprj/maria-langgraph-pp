import { Annotation } from "@langchain/langgraph";
import { AnnotationTokensGastos } from "../../shared/tokensAcumulados.js";

// Issue #176 — mesmo shape do campo `endereco` de CadastrarPessoaDTO
// (POST /integra/pessoa) — quem embutir este subgrafo manda esse objeto
// direto pra API do Verde, sem tradução.
export interface EnderecoCadastro {
  logradouro?: string;
  numero?: string;
  complemento?: string;
  cep?: string;
  bairro?: string;
  municipio?: string;
  uf?: string;
}

export type ColetarEnderecoStateType = typeof ColetarEnderecoState.State;

// Campos crus (cep/logradouro/numero/...) ficam só INTERNOS a este subgrafo
// — quem embute (ex: subgrafos/cadastroPessoa/) só precisa compartilhar o
// canal `endereco` (resultado final), não cada campo cru individualmente.
export const ColetarEnderecoState = Annotation.Root({
  cep: Annotation<string | undefined>,
  logradouro: Annotation<string | undefined>,
  numero: Annotation<string | undefined>,
  complemento: Annotation<string | undefined>,
  bairro: Annotation<string | undefined>,
  municipio: Annotation<string | undefined>,
  uf: Annotation<string | undefined>,
  endereco: Annotation<EnderecoCadastro | undefined>,
  perguntaAtualTexto: Annotation<string | undefined>,
  perguntaAtualViaIA: Annotation<boolean | undefined>,
  perguntaAtualTokensTotal: Annotation<number | undefined>,
  tokensGastos: AnnotationTokensGastos(),
});
