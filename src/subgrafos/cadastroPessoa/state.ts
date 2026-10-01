import { Annotation } from "@langchain/langgraph";
import type { DadosPessoa } from "../../shared/types.js";
import type { EnderecoCadastro } from "../coletarEndereco/state.js";
import { AnnotationTokensGastos } from "../../shared/tokensAcumulados.js";

export type CadastroPessoaStateType = typeof CadastroPessoaState.State;

// Issue #171 — roda quando o fluxo pai não encontrou a pessoa no Verde
// (ex: subgrafo identificarAssistido esgotou tentativas). `cpf` é
// compartilhado com o pai (mesmo nome de canal) — NUNCA perguntado de novo
// aqui, já foi coletado antes. `dadosPessoa` também é o mesmo campo que o
// pai já usa pra saber se a pessoa foi encontrada — depois de um cadastro
// com sucesso, o pai lê esse MESMO campo pra continuar o fluxo normalmente
// (idêntico ao caminho de "encontrado de primeira"), sem nó de tradução.
export const CadastroPessoaState = Annotation.Root({
  cpf: Annotation<string | undefined>,
  nome: Annotation<string | undefined>,
  dataNascimento: Annotation<string | undefined>,
  // Issue #176 — compartilhado com o subgrafo coletarEndereco, embutido
  // como nó aqui dentro. Endereço ausente = pessoa cadastrada sem endereço
  // (comportamento de antes da issue #176) — o subgrafo sempre roda, mas
  // cada campo individual pode vir undefined se a pessoa não informar.
  endereco: Annotation<EnderecoCadastro | undefined>,
  dadosPessoa: Annotation<DadosPessoa | undefined>,
  // preenchido só se o POST /integra/pessoa falhar — pai decide o que fazer
  // (ver falhaCadastro em fluxos/violenciaDomestica/graph.ts).
  cadastroErro: Annotation<string | undefined>,
  // Issue #189 — depois de cadastrar com sucesso, confirma os dados antes
  // de devolver pro fluxo pai. Mesmo campo compartilhado com
  // identificarAssistido (issue #189 cobre os 2 subgrafos) e os fluxos pai.
  confirmaAssistido: Annotation<boolean | undefined>,
  // Issue #191 — mesmo campo/racional de identificarAssistido/state.ts:
  // confirmação só acontece quando veio do orquestrador.
  viaOrquestrador: Annotation<boolean | undefined>,
  perguntaAtualTexto: Annotation<string | undefined>,
  perguntaAtualViaIA: Annotation<boolean | undefined>,
  perguntaAtualTokensTotal: Annotation<number | undefined>,
  tokensGastos: AnnotationTokensGastos(),
});
