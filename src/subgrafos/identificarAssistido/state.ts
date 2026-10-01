import { Annotation } from "@langchain/langgraph";
import type { DadosPessoa } from "../../shared/types.js";
import { AnnotationTokensGastos } from "../../shared/tokensAcumulados.js";

export type IdentificarAssistidoStateType = typeof IdentificarAssistidoState.State;

// Issue #171 — extraído de fluxos/violenciaDomestica/graph.ts (era pedirCpf
// + consultarPessoa + retry, direto no grafo do fluxo). Mesmos nomes de
// campo do state de violência doméstica de propósito — LangGraph compartilha
// canal automaticamente entre grafo pai e subgrafo quando o nome bate, sem
// precisar de nó de "tradução" no meio.
export const IdentificarAssistidoState = Annotation.Root({
  // vem pronto no `dadosConhecidos` do POST /atendimentos (contrato Tykhe)
  // quando o fluxo pai já sabe o CPF — bypass evita perguntar de novo.
  cpf: Annotation<string | undefined>,
  dadosPessoa: Annotation<DadosPessoa | undefined>,
  tentativasCpf: Annotation<number | undefined>,
  querTentarNovamenteCpf: Annotation<boolean | undefined>,
  digitouCpfDireto: Annotation<boolean | undefined>,
  // Issue #189 — depois de achar a pessoa por CPF, confirma que os dados
  // são dela antes de devolver pro fluxo pai. false (não confirmado) é um
  // desfecho DIFERENTE de "esgotado" (CPF não encontrado) — o pai não deve
  // tentar cadastro novo aqui, é handoff direto. Mesmo campo compartilhado
  // com cadastroPessoa (issue #189 cobre os 2 subgrafos) e os fluxos pai.
  confirmaAssistido: Annotation<boolean | undefined>,
  // Issue #191 — setado pelo orquestrador (rotas/orquestrador.ts) ao criar
  // o atendimento; NUNCA setado por quem chama POST /atendimentos com
  // flowId direto (contrato da Tykhe). A pergunta de confirmação acima só
  // acontece quando isso é true — sem ele, a Tykhe não pode ganhar NENHUMA
  // pergunta nova que não existia antes das issues #171/#183/#189.
  viaOrquestrador: Annotation<boolean | undefined>,
  perguntaAtualTexto: Annotation<string | undefined>,
  perguntaAtualViaIA: Annotation<boolean | undefined>,
  perguntaAtualTokensTotal: Annotation<number | undefined>,
  tokensGastos: AnnotationTokensGastos(),
});
