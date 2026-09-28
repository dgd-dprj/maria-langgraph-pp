import { interrupt, StateGraph, START, END } from "@langchain/langgraph";
import { type ViolenciaDomesticaStateType, ViolenciaDomesticaState } from "./state.js";
import type { OrgaoAtendimento, Pergunta } from "../../shared/types.js";
import {
  consultarCep as consultarCepVerde,
  consultarOrgaosPlantaoViolenciaDomestica,
  consultarOrgaosViolenciaDomestica,
  consultarPlantaoVigente,
  consultarProcesso as consultarProcessoVerde,
  criarEncaminhamentoViolenciaDomestica,
} from "../../integracoes/verde.js";
import { prepararPergunta } from "../../ia/reescrever.js";
import { criarCheckpointer } from "../../shared/checkpointer.js";
import { grafo as subgrafoIdentificarAssistido } from "../../subgrafos/identificarAssistido/graph.js";
import { grafo as subgrafoCadastroPessoa } from "../../subgrafos/cadastroPessoa/graph.js";
import { MENSAGEM_FALHA_CADASTRO, MENSAGEM_FALHA_ENCAMINHAMENTO, MENSAGEM_NAO_VITIMA, MENSAGEM_SEM_ORGAO_DISPONIVEL } from "./api.js";

// Mesma tolerância de respostas sim_nao de fluxos/pessoaPresa/graph.ts — a
// Tykhe às vezes repassa "Sim"/"Não" literal em vez de "true"/"false" (bug
// real achado ao vivo 2026-08-31, ver respostaEhSim lá). Duplicado aqui (não
// extraído pra shared/) porque é pequeno e específico o bastante — mesmo
// racional de "repo pequeno não justifica abstração" usado em ia/extrair.ts.
function respostaEhSim(resposta: string): boolean {
  const normalizado = resposta
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim()
    .toLowerCase();
  return normalizado === "true" || normalizado === "sim" || normalizado === "s" || normalizado === "yes";
}

// Issue #77 — reconhece processo digitado direto na pergunta "quer tentar
// de novo?" (em vez de "Sim") pelo FORMATO, mesmo padrão de
// rgFormatoValido em pessoaPresa/graph.ts (issue #54). CPF tem o
// equivalente dentro de subgrafos/identificarAssistido/graph.ts agora
// (issue #171).
function numeroProcessoFormatoValido(valor: string): boolean {
  return valor.replace(/\D/g, "").length === 20;
}

// Gate de elegibilidade — primeira pergunta do fluxo (decisão de design:
// perguntar isso ANTES de processo, pra não gastar pergunta à toa quando a
// resposta for "não").
async function prepararPerguntaEhVitima(): Promise<Partial<ViolenciaDomesticaStateType>> {
  return prepararPergunta("ehVitima", "Você é a vítima de violência doméstica?");
}

async function pedirEhVitima(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Você é a vítima de violência doméstica?",
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  return { ehVitima: respostaEhSim(resposta) };
}

function depoisDeEhVitima(state: ViolenciaDomesticaStateType): "temProcesso" | "naoEhVitima" {
  return state.ehVitima ? "temProcesso" : "naoEhVitima";
}

async function naoEhVitima(): Promise<Partial<ViolenciaDomesticaStateType>> {
  return { statusFinal: "handoff_humano", motivoHandoff: "nao_e_vitima", mensagemFinal: MENSAGEM_NAO_VITIMA };
}

// Só informativo — não muda o caminho do fluxo (decisão de design confirmada:
// mesmo padrão non-blocking de consultarProcesso em pessoaPresa/graph.ts).
async function prepararPerguntaTemProcesso(): Promise<Partial<ViolenciaDomesticaStateType>> {
  return prepararPergunta("temProcesso", "Existe algum processo relacionado ao seu caso?");
}

async function pedirTemProcesso(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Existe algum processo relacionado ao seu caso?",
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  // Issue #110 — mesmo racional do retry (issue #77): número de processo
  // digitado direto aqui (sem esperar a pergunta "qual o número?") já é
  // aceito como o valor, pulando pedirNumeroProcesso. Resposta que não é
  // nem sim/não nem processo cai no fallback de sempre (trata como "não").
  if (numeroProcessoFormatoValido(resposta)) {
    return { temProcesso: true, numeroProcesso: resposta, digitouProcessoDireto: true };
  }
  return { temProcesso: respostaEhSim(resposta), digitouProcessoDireto: false };
}

function depoisDeTemProcesso(state: ViolenciaDomesticaStateType): "pedirNumeroProcesso" | "pedirTemRO" | "consultarProcesso" {
  if (state.digitouProcessoDireto) return "consultarProcesso";
  return state.temProcesso ? "pedirNumeroProcesso" : "pedirTemRO";
}

async function prepararPerguntaNumeroProcesso(): Promise<Partial<ViolenciaDomesticaStateType>> {
  return prepararPergunta("numeroProcesso", "Qual o número do processo? Informe apenas os números.");
}

async function pedirNumeroProcesso(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Qual o número do processo? Informe apenas os números.",
    tipo: "texto",
  });
  return { numeroProcesso: resposta };
}

async function consultarProcesso(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const dados = await consultarProcessoVerde(state.numeroProcesso ?? "");
  return { dadosProcesso: dados, tentativasProcesso: (state.tentativasProcesso ?? 0) + 1 };
}

// Issue #75 — diferente do RG/CPF, processo é só informativo: esgotar as
// tentativas (ou desistir) NUNCA vira handoff, só segue o fluxo sem o
// número confirmado. "temRO" nos 2 casos de desistência (silenciosa na 3ª
// falha, ou depois de responder "não" quer tentar de novo).
function depoisDeConsultarProcesso(state: ViolenciaDomesticaStateType): "temRO" | "tentarNovamente" {
  if (state.dadosProcesso?.encontrado) return "temRO";
  return (state.tentativasProcesso ?? 0) >= 3 ? "temRO" : "tentarNovamente";
}

async function prepararPerguntaTentarNovamenteProcesso(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  return prepararPergunta(
    "tentarNovamenteProcesso",
    `Não encontrei esse número de processo (tentativa ${state.tentativasProcesso ?? 1} de 3). Quer tentar de novo?`
  );
}

async function perguntaTentarNovamenteProcesso(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta:
      state.perguntaAtualTexto ??
      `Não encontrei esse número de processo (tentativa ${state.tentativasProcesso ?? 1} de 3). Quer tentar de novo?`,
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  // Issue #77 — número de processo digitado direto em vez de "Sim" já é
  // aceito como o novo valor, pulando pedirNumeroProcesso (vai direto pra
  // consultarProcesso).
  if (numeroProcessoFormatoValido(resposta)) {
    return { querTentarNovamenteProcesso: true, numeroProcesso: resposta, digitouProcessoDireto: true };
  }
  return { querTentarNovamenteProcesso: respostaEhSim(resposta), digitouProcessoDireto: false };
}

function depoisDePerguntaTentarProcesso(state: ViolenciaDomesticaStateType): "pedirNumeroProcesso" | "temRO" | "consultarProcesso" {
  if (!state.querTentarNovamenteProcesso) return "temRO";
  return state.digitouProcessoDireto ? "consultarProcesso" : "pedirNumeroProcesso";
}

async function prepararPerguntaTemRO(): Promise<Partial<ViolenciaDomesticaStateType>> {
  return prepararPergunta("temRegistroOcorrencia", "Você já registrou o Boletim de Ocorrência (RO) na delegacia?");
}

async function pedirTemRO(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const resposta = interrupt<Pergunta, string>({
    pergunta: state.perguntaAtualTexto ?? "Você já registrou o Boletim de Ocorrência (RO) na delegacia?",
    tipo: "sim_nao",
    opcoes: ["Sim", "Não"],
  });
  return { temRegistroOcorrencia: respostaEhSim(resposta) };
}

// Issue #171 — pedir/consultar CPF (com retry) morava aqui, extraído pro
// subgrafo subgrafos/identificarAssistido/graph.ts (reaproveitável). Esse
// subgrafo é embutido como nó abaixo (ver `grafo` no fim do arquivo) —
// depoisDeIdentificarAssistido decide o que fazer com o resultado dele.
//
// Issue #189 — confirmaAssistido:false checado ANTES de dadosPessoa.encontrado:
// achou a pessoa mas ela negou que os dados são dela — handoff direto, não
// tenta cadastro novo (seria tratar "não confirmo" igual a "não achei").
function depoisDeIdentificarAssistido(state: ViolenciaDomesticaStateType): "encontrado" | "cadastrar" | "naoConfirmado" {
  if (state.confirmaAssistido === false) return "naoConfirmado";
  return state.dadosPessoa?.encontrado ? "encontrado" : "cadastrar";
}

// Issue #171 — subgrafo cadastroPessoa (embutido abaixo) preenche
// dadosPessoa (sucesso, mesmo campo de quem já tinha cadastro) ou
// cadastroErro (falha) — nunca os dois. Issue #189 — mesmo racional do
// comentário acima, agora também depois de cadastrar (não só depois de achar).
function depoisDeCadastrarPessoa(state: ViolenciaDomesticaStateType): "continuar" | "falhou" | "naoConfirmado" {
  if (state.cadastroErro !== undefined) return "falhou";
  if (state.confirmaAssistido === false) return "naoConfirmado";
  return "continuar";
}

async function falhaCadastro(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  return {
    statusFinal: "handoff_humano",
    motivoHandoff: "falha_cadastro",
    mensagemFinal: state.cadastroErro ? `${MENSAGEM_FALHA_CADASTRO} (${state.cadastroErro})` : MENSAGEM_FALHA_CADASTRO,
  };
}

// Issue #189 — dead-end compartilhado pelos 2 caminhos que embutem
// identificarAssistido/cadastroPessoa (achou por CPF ou acabou de
// cadastrar), quando a pessoa nega que os dados achados/cadastrados são
// dela. Sem mensagem fixa de propósito — mesmo padrão de
// dados_pessoa_nao_atendidos em pessoaPresa/graph.ts, só o status importa.
async function assistidoNaoConfirmado(): Promise<Partial<ViolenciaDomesticaStateType>> {
  return { statusFinal: "handoff_humano", motivoHandoff: "assistido_nao_confirmado" };
}

// Issue #127 — roda sempre depois de identificar a pessoa (encontrada ou
// recém-cadastrada), mesmo sem CPF
// encontrado, se enderecoDetalhado.cep não existir consultarCepVerde
// devolve encontrado:false e só não preenche os ids — não bloqueia nada,
// mesmo racional non-blocking de consultarPlantao/consultarProcesso).
async function consultarCep(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const cep = state.dadosPessoa?.enderecoDetalhado?.cep;
  if (!cep) return {};
  const dadosCep = await consultarCepVerde(cep);
  if (!dadosCep.encontrado || !state.dadosPessoa) return {};
  return {
    dadosPessoa: {
      ...state.dadosPessoa,
      enderecoDetalhado: {
        ...state.dadosPessoa.enderecoDetalhado,
        idUf: dadosCep.idUf,
        idBairro: dadosCep.idBairro,
        idMunicipio: dadosCep.idMunicipio,
      },
    },
  };
}

// Sem parâmetro nenhum — dá pra rodar em qualquer ponto do fluxo, roda logo
// depois de saber idPessoa pra já decidir qual consulta de órgão usar em
// seguida. Vazio = fora de horário de plantão, segue fluxo normal.
async function consultarPlantao(): Promise<Partial<ViolenciaDomesticaStateType>> {
  const plantoes = await consultarPlantaoVigente();
  return { plantaoIds: plantoes.map((p) => p.id) };
}

// O Verde resolve TUDO pelo idPessoa+RO (endereço cadastrado, regra de
// negócio deles) — ver consultarOrgaosViolenciaDomestica em
// integracoes/verde.ts. Substitui a heurística antiga de comparar município
// contra "Rio de Janeiro" — o Verde já sabe capital x outras cidades, DP x
// Juizado x NUDEM, tudo. Em horário de plantão (plantaoIds não vazio), a
// regra de órgão é outra — usa o endpoint de plantão em vez do normal,
// RO deixa de importar nesse caso (endpoint de plantão nem recebe RO).
async function consultarOrgaos(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const idPessoa = state.dadosPessoa?.idPessoa ?? 0;
  const plantaoIds = state.plantaoIds ?? [];
  const resultado =
    plantaoIds.length > 0
      ? await consultarOrgaosPlantaoViolenciaDomestica(plantaoIds, idPessoa)
      : await consultarOrgaosViolenciaDomestica(state.temRegistroOcorrencia ?? false, idPessoa);
  return { orgaosViolenciaDomestica: resultado };
}

// Issue #171 — só chega aqui depois de identificarAssistido/cadastroPessoa
// já terem garantido que a pessoa existe (dadosPessoa.encontrado:true) —
// "sem órgão" agora só tem 1 causa possível (pessoa encontrada, genuinamente
// sem órgão disponível pra ela). O caso "CPF não encontrado" foi resolvido
// (encontrado ou cadastrado) ANTES de chegar em consultarOrgaos.
function depoisDeConsultarOrgaos(state: ViolenciaDomesticaStateType): "semOrgao" | "prosseguir" {
  const semOrgao = state.orgaosViolenciaDomestica?.contactarCrc || !state.orgaosViolenciaDomestica?.orgaos.length;
  return semOrgao ? "semOrgao" : "prosseguir";
}

// Único desfecho "sem órgão" documentado pelo Verde (RO:true sem nenhum
// órgão encontrado, PESSOA encontrada) — mensagemCrc vem pronta deles
// ("...ligar 129"), cai no texto fixo só se por algum motivo não vier.
async function semOrgaoDisponivel(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  return {
    statusFinal: "handoff_humano",
    motivoHandoff: "sem_orgao_disponivel",
    mensagemFinal: state.orgaosViolenciaDomestica?.mensagemCrc ?? MENSAGEM_SEM_ORGAO_DISPONIVEL,
  };
}

// Executa o encaminhamento de VERDADE (POST no Verde, cria registro real) —
// só roda depois de já saber pra qual órgão vai (consultarOrgaos acima).
// idOrgao/idLocalAtendimento vêm do PRIMEIRO órgão da lista (prioridade do
// Verde); idAssunto não é enviado (confirmado com o time do Verde que não é
// necessário pra esse fluxo).
async function criarEncaminhamento(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const orgao = state.orgaosViolenciaDomestica?.orgaos[0];
  const resultado = await criarEncaminhamentoViolenciaDomestica({
    idPessoa: state.dadosPessoa?.idPessoa ?? 0,
    idOrgao: orgao?.id ?? 0,
    idLocalAtendimento: orgao?.enderecos?.[0]?.idLocalAtendimento,
    urgente: !!state.temRegistroOcorrencia,
  });
  return resultado.sucesso
    ? { encaminhamentoId: resultado.id }
    : { encaminhamentoErro: resultado.erro ?? "erro desconhecido" };
}

function depoisDeCriarEncaminhamento(state: ViolenciaDomesticaStateType): "concluir" | "falhou" {
  return state.encaminhamentoId !== undefined ? "concluir" : "falhou";
}

// Achou o órgão certo, mas o POST de encaminhamento de verdade falhou —
// NÃO diz pro usuário que deu certo (mentira), manda pra atendente confirmar
// manualmente. state.orgaosViolenciaDomestica ainda tem o órgão pretendido,
// útil pro atendente ver nos metadados mesmo sem ter sido criado de fato.
async function falhaEncaminhamento(): Promise<Partial<ViolenciaDomesticaStateType>> {
  return {
    statusFinal: "handoff_humano",
    motivoHandoff: "falha_encaminhamento",
    mensagemFinal: MENSAGEM_FALHA_ENCAMINHAMENTO,
  };
}

function montarMensagemEncaminhamento(orgao: OrgaoAtendimento, urgente: boolean, encaminhamentoId: number | undefined): string {
  const municipio = orgao.enderecos?.[0]?.municipio;
  const localizacao = municipio ? ` (${municipio})` : "";
  const protocolo = encaminhamentoId !== undefined ? ` Protocolo: ${encaminhamentoId}.` : "";
  return urgente
    ? `Como você já tem Boletim de Ocorrência, vou encaminhar seu atendimento com urgência para ${orgao.nome}${localizacao} — sem necessidade de agendamento.${protocolo}`
    : `Vou encaminhar seu caso para ${orgao.nome}${localizacao}.${protocolo}`;
}

// tipoEncaminhamento "urgente" x "padrao" ainda é útil pra Tykhe (prioridade
// de atendimento), mas o ÓRGÃO em si (nome/endereço) já vem certo do Verde —
// não precisamos mais decidir NUDEM x Defensoria da Vítima aqui. Só chega
// aqui depois de criarEncaminhamento ter dado certo de verdade.
async function concluir(state: ViolenciaDomesticaStateType): Promise<Partial<ViolenciaDomesticaStateType>> {
  const orgao = state.orgaosViolenciaDomestica?.orgaos[0];
  const urgente = !!state.temRegistroOcorrencia;
  return {
    statusFinal: "concluido",
    tipoEncaminhamento: urgente ? "urgente" : "padrao",
    mensagemFinal: orgao ? montarMensagemEncaminhamento(orgao, urgente, state.encaminhamentoId) : MENSAGEM_SEM_ORGAO_DISPONIVEL,
  };
}

const grafo = new StateGraph(ViolenciaDomesticaState)
  .addNode("prepararPerguntaEhVitima", prepararPerguntaEhVitima)
  .addNode("pedirEhVitima", pedirEhVitima)
  .addNode("naoEhVitima", naoEhVitima)
  .addNode("prepararPerguntaTemProcesso", prepararPerguntaTemProcesso)
  .addNode("pedirTemProcesso", pedirTemProcesso)
  .addNode("prepararPerguntaNumeroProcesso", prepararPerguntaNumeroProcesso)
  .addNode("pedirNumeroProcesso", pedirNumeroProcesso)
  .addNode("consultarProcesso", consultarProcesso)
  .addNode("prepararPerguntaTentarNovamenteProcesso", prepararPerguntaTentarNovamenteProcesso)
  .addNode("perguntaTentarNovamenteProcesso", perguntaTentarNovamenteProcesso)
  .addNode("prepararPerguntaTemRO", prepararPerguntaTemRO)
  .addNode("pedirTemRO", pedirTemRO)
  .addNode("identificarAssistido", subgrafoIdentificarAssistido)
  .addNode("cadastroPessoa", subgrafoCadastroPessoa)
  .addNode("falhaCadastro", falhaCadastro)
  .addNode("assistidoNaoConfirmado", assistidoNaoConfirmado)
  .addNode("consultarCep", consultarCep)
  .addNode("consultarPlantao", consultarPlantao)
  .addNode("consultarOrgaos", consultarOrgaos)
  .addNode("semOrgaoDisponivel", semOrgaoDisponivel)
  .addNode("criarEncaminhamento", criarEncaminhamento)
  .addNode("falhaEncaminhamento", falhaEncaminhamento)
  .addNode("concluir", concluir)
  .addEdge(START, "prepararPerguntaEhVitima")
  .addEdge("prepararPerguntaEhVitima", "pedirEhVitima")
  .addConditionalEdges("pedirEhVitima", depoisDeEhVitima, {
    temProcesso: "prepararPerguntaTemProcesso",
    naoEhVitima: "naoEhVitima",
  })
  .addEdge("naoEhVitima", END)
  .addEdge("prepararPerguntaTemProcesso", "pedirTemProcesso")
  .addConditionalEdges("pedirTemProcesso", depoisDeTemProcesso, {
    pedirNumeroProcesso: "prepararPerguntaNumeroProcesso",
    pedirTemRO: "prepararPerguntaTemRO",
    consultarProcesso: "consultarProcesso",
  })
  .addEdge("prepararPerguntaNumeroProcesso", "pedirNumeroProcesso")
  .addEdge("pedirNumeroProcesso", "consultarProcesso")
  .addConditionalEdges("consultarProcesso", depoisDeConsultarProcesso, {
    temRO: "prepararPerguntaTemRO",
    tentarNovamente: "prepararPerguntaTentarNovamenteProcesso",
  })
  .addEdge("prepararPerguntaTentarNovamenteProcesso", "perguntaTentarNovamenteProcesso")
  .addConditionalEdges("perguntaTentarNovamenteProcesso", depoisDePerguntaTentarProcesso, {
    pedirNumeroProcesso: "prepararPerguntaNumeroProcesso",
    temRO: "prepararPerguntaTemRO",
    // processo digitado direto na pergunta de retry (issue #77) — pula
    // prepararPerguntaNumeroProcesso, consulta o Verde de novo direto.
    consultarProcesso: "consultarProcesso",
  })
  .addEdge("prepararPerguntaTemRO", "pedirTemRO")
  .addEdge("pedirTemRO", "identificarAssistido")
  .addConditionalEdges("identificarAssistido", depoisDeIdentificarAssistido, {
    encontrado: "consultarCep",
    cadastrar: "cadastroPessoa",
    naoConfirmado: "assistidoNaoConfirmado",
  })
  .addConditionalEdges("cadastroPessoa", depoisDeCadastrarPessoa, {
    continuar: "consultarCep",
    falhou: "falhaCadastro",
    naoConfirmado: "assistidoNaoConfirmado",
  })
  .addEdge("falhaCadastro", END)
  .addEdge("assistidoNaoConfirmado", END)
  .addEdge("consultarCep", "consultarPlantao")
  .addEdge("consultarPlantao", "consultarOrgaos")
  .addConditionalEdges("consultarOrgaos", depoisDeConsultarOrgaos, {
    semOrgao: "semOrgaoDisponivel",
    prosseguir: "criarEncaminhamento",
  })
  .addEdge("semOrgaoDisponivel", END)
  .addConditionalEdges("criarEncaminhamento", depoisDeCriarEncaminhamento, {
    concluir: "concluir",
    falhou: "falhaEncaminhamento",
  })
  .addEdge("falhaEncaminhamento", END)
  .addEdge("concluir", END)
  .compile({ checkpointer: await criarCheckpointer() });

export { grafo };
