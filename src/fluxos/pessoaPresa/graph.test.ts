import { test } from "node:test";
import assert from "node:assert/strict";
import { Command } from "@langchain/langgraph";
import { grafo } from "./graph.js";

// thread_id único por teste — grafo é singleton com MemorySaver compartilhado
// entre todos os testes deste arquivo, thread_id diferente evita um teste
// pisar no estado do outro.
let contador = 0;
function novoConfig() {
  contador += 1;
  return { configurable: { thread_id: `teste-grafo-${contador}` } };
}

function pergunta(resultado: unknown): { pergunta: string; tipo: string; opcoes?: string[] } | undefined {
  return (resultado as { __interrupt__?: Array<{ value: { pergunta: string; tipo: string; opcoes?: string[] } }> }).__interrupt__?.[0]?.value;
}

// Issue #183 — depois do parentesco, identificarAssistido pergunta o CPF do
// ASSISTIDO (quem está conversando, diferente do RG do preso) antes de
// concluir — mesmo racional de violenciaDomestica/graph.ts (issue #171).
// CPF "11111111111" acha a pessoa de teste no mock — caminho de cadastro
// (CPF não encontrado) tem teste próprio, não usado aqui.
async function identificarComCpf(config: { configurable: { thread_id: string } }) {
  return grafo.invoke(new Command({ resume: "11111111111" }), config);
}

test("1ª invocação pausa em pedirTemProcesso (primeira pergunta da ordem atual)", async () => {
  const config = novoConfig();
  const r = await grafo.invoke({}, config);
  const p = pergunta(r);
  assert.equal(p?.tipo, "sim_nao");
  assert.match(p?.pergunta ?? "", /número do processo/);
});

test("temProcesso=true → pergunta número do processo (não pula pro RG)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  const r = await grafo.invoke(new Command({ resume: "true" }), config);
  const p = pergunta(r);
  assert.match(p?.pergunta ?? "", /Qual o número do processo/);
});

test("temProcesso=true → depois de informar o número, consulta o processo (Verde) e segue pro RG normalmente", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // tem processo
  const r = await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config); // número
  const p = pergunta(r);
  assert.match(p?.pergunta ?? "", /RG da pessoa presa/, "consultarProcesso não deve travar o fluxo, mesmo sem achar/com erro");
  const dadosProcesso = (r as { dadosProcesso?: { encontrado: boolean } }).dadosProcesso;
  assert.equal(typeof dadosProcesso?.encontrado, "boolean", "dadosProcesso deveria estar preenchido no state");
});

test("temProcesso=false → pula direto pro RG", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  const r = await grafo.invoke(new Command({ resume: "false" }), config);
  const p = pergunta(r);
  assert.match(p?.pergunta ?? "", /RG da pessoa presa/);
});

// Regressão — bug real achado ao vivo 2026-08-31: o fluxo da Tykhe manda o
// texto literal "Sim"/"Não" digitado pelo usuário, não "true"/"false" como
// o contrato previa. Confirmação de nome com "Sim" literal virava false (a
// comparação estrita === "true" não reconhecia), negando a confirmação sem
// motivo e mandando pro handoff. respostaEhSim() aceita as duas formas.
test("resume com 'Sim'/'Não' literal (não 'true'/'false') funciona igual", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  const r = await grafo.invoke(new Command({ resume: "Sim" }), config);
  const p = pergunta(r);
  assert.match(p?.pergunta ?? "", /Qual o número do processo/, "'Sim' deveria contar como temProcesso=true, igual 'true'");
});

test("resume com 'false' não quebra (regressão do bug de Command({resume:false})/valor falsy)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config); // pausa em pedirTemProcesso
  // resume é sempre STRING ("false"), nunca boolean cru — é isso que evita
  // o bug real do LangGraph (graph.invoke trata resume:false como "sem
  // resume", lança "Received empty Command input"). Se alguém reintroduzir
  // resume:boolean aqui, este teste quebra.
  await assert.doesNotReject(() => grafo.invoke(new Command({ resume: "false" }), config));
});

// Issue #49 — sem número do processo, os dados são coletados/confirmados
// normalmente (RG, nome, parentesco), mas o desfecho vira handoff_humano em
// vez de concluido: falta o processo pra confirmar/acompanhar de verdade,
// só um atendente resolve isso.
test("fluxo completo: SEM processo, nome confirmado → handoff_humano (issue #49), não concluido", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config); // tem processo?
  await grafo.invoke(new Command({ resume: "false" }), config); // → RG direto
  const rApenado = await grafo.invoke(new Command({ resume: "11111111111" }), config); // RG
  const pApenado = pergunta(rApenado);
  assert.match(pApenado?.pergunta ?? "", /Confirma que a pessoa presa é/);

  const rConfirma = await grafo.invoke(new Command({ resume: "true" }), config); // confirma nome
  const pParentesco = pergunta(rConfirma);
  assert.match(pParentesco?.pergunta ?? "", /parentesco/);

  const rParentesco = await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco
  assert.match(pergunta(rParentesco)?.pergunta ?? "", /CPF/, "issue #183 — deveria pausar pedindo CPF do assistido antes de concluir");
  const rFinal = await identificarComCpf(config);
  assert.equal(pergunta(rFinal), undefined, "não deve ter pergunta pendente no fim");
  const final = rFinal as { statusFinal?: string; motivoHandoff?: string; mensagemFinal?: string };
  assert.equal(final.statusFinal, "handoff_humano", "sem número do processo não deveria ser marcado como concluido");
  assert.equal(final.motivoHandoff, "sem_numero_processo");
  assert.match(final.mensagemFinal ?? "", /número do processo/i);
});

// Regressão: COM número do processo, o desfecho continua concluido — só o
// caso sem processo (acima) mudou.
test("fluxo completo: COM processo, nome confirmado → concluido (comportamento inalterado)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config); // tem processo?
  await grafo.invoke(new Command({ resume: "true" }), config); // → pergunta número do processo
  await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config); // número do processo
  const rApenado = await grafo.invoke(new Command({ resume: "11111111111" }), config); // RG
  assert.match(pergunta(rApenado)?.pergunta ?? "", /Confirma que a pessoa presa é/);

  const rConfirma = await grafo.invoke(new Command({ resume: "true" }), config); // confirma nome
  assert.match(pergunta(rConfirma)?.pergunta ?? "", /parentesco/);

  await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco → pausa pra CPF
  const rFinal = await identificarComCpf(config);
  const final = rFinal as { statusFinal?: string; motivoHandoff?: string };
  assert.equal(final.statusFinal, "concluido");
  assert.equal(final.motivoHandoff, undefined);
});

// Issue #51 — mesma lógica da #49, agora pro caminho COM processo: só
// origem SEEU é considerada "resolvida" pelo bot. Sentinela de teste
// "0000000-00.0000.0.00.0000" simula origem não suportada (ver
// integracoes/verde.ts::consultarProcesso).
test("fluxo completo: COM processo de origem NÃO suportada → handoff_humano (issue #51)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config); // tem processo?
  await grafo.invoke(new Command({ resume: "true" }), config); // → pergunta número do processo
  await grafo.invoke(new Command({ resume: "0000000-00.0000.0.00.0000" }), config); // origem não suportada (sentinela)
  const rApenado = await grafo.invoke(new Command({ resume: "11111111111" }), config); // RG
  assert.match(pergunta(rApenado)?.pergunta ?? "", /Confirma que a pessoa presa é/);

  const rConfirma = await grafo.invoke(new Command({ resume: "true" }), config); // confirma nome
  assert.match(pergunta(rConfirma)?.pergunta ?? "", /parentesco/);

  await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco → pausa pra CPF
  const rFinal = await identificarComCpf(config);
  const final = rFinal as { statusFinal?: string; motivoHandoff?: string; mensagemFinal?: string };
  assert.equal(final.statusFinal, "handoff_humano", "origem diferente de SEEU não deveria ser marcada como concluido");
  assert.equal(final.motivoHandoff, "origem_processo_nao_suportada");
  assert.match(final.mensagemFinal ?? "", /origem/i);
});

// Processo não encontrado na consulta (sem origem nenhuma) cai no MESMO
// handoff de origem não suportada — sentinela "000000000" simula isso.
test("fluxo completo: processo NÃO ENCONTRADO na consulta → handoff_humano, mesmo motivo de origem não suportada", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config); // tem processo?
  await grafo.invoke(new Command({ resume: "true" }), config); // → pergunta número do processo
  await grafo.invoke(new Command({ resume: "000000000" }), config); // processo não encontrado (sentinela)
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // RG
  await grafo.invoke(new Command({ resume: "true" }), config); // confirma nome
  await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco → pausa pra CPF
  const rFinal = await identificarComCpf(config);
  const final = rFinal as { statusFinal?: string; motivoHandoff?: string };
  assert.equal(final.statusFinal, "handoff_humano");
  assert.equal(final.motivoHandoff, "origem_processo_nao_suportada");
});

// Issue #57 — situação/tipo de preso/regime fora do permitido (ticket
// original do sistema de origem, SIPEN) também viram handoff_humano, no
// mesmo esquema de #49/#51: fluxo continua perguntando normalmente, só o
// desfecho final muda. Sentinelas de RG simulam cada caso (ver
// integracoes/verde.ts::consultarApenadoPorRg).
test("fluxo completo: situação fora do permitido (ex: LIBERTADO) → handoff_humano (issue #57)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config);
  await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config); // origem SEEU (padrão)
  await grafo.invoke(new Command({ resume: "22222222222" }), config); // situação LIBERTADO (sentinela)
  await grafo.invoke(new Command({ resume: "true" }), config); // confirma nome
  await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco → pausa pra CPF
  const rFinal = await identificarComCpf(config);
  const final = rFinal as { statusFinal?: string; motivoHandoff?: string };
  assert.equal(final.statusFinal, "handoff_humano");
  assert.equal(final.motivoHandoff, "dados_pessoa_nao_atendidos");
});

test("fluxo completo: tipo de preso fora do permitido (ex: PROVISÓRIO) → handoff_humano (issue #57)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config);
  await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config);
  await grafo.invoke(new Command({ resume: "33333333333" }), config); // tipoPreso PROVISÓRIO (sentinela)
  await grafo.invoke(new Command({ resume: "true" }), config);
  await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco → pausa pra CPF
  const rFinal = await identificarComCpf(config);
  const final = rFinal as { statusFinal?: string; motivoHandoff?: string };
  assert.equal(final.statusFinal, "handoff_humano");
  assert.equal(final.motivoHandoff, "dados_pessoa_nao_atendidos");
});

test("fluxo completo: regime fora do permitido (ex: ABERTO) → handoff_humano (issue #57)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config);
  await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config);
  await grafo.invoke(new Command({ resume: "44444444444" }), config); // regime ABERTO (sentinela)
  await grafo.invoke(new Command({ resume: "true" }), config);
  await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco → pausa pra CPF
  const rFinal = await identificarComCpf(config);
  const final = rFinal as { statusFinal?: string; motivoHandoff?: string };
  assert.equal(final.statusFinal, "handoff_humano");
  assert.equal(final.motivoHandoff, "dados_pessoa_nao_atendidos");
});

// Achado ao vivo: Verde é inconsistente no prefixo "EM" ("ATIVO" sem,
// "EM RESDOM" com) — normalizarSituacao (graph.ts) remove esse prefixo
// antes de comparar, então "EM RESDOM" deveria ser reconhecido igual a
// "RESDOM" (situação permitida) e concluir normalmente.
test("fluxo completo: situação com prefixo 'EM' (EM RESDOM) → reconhecida, conclui normalmente (issue #57)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config);
  await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config);
  await grafo.invoke(new Command({ resume: "55555555555" }), config); // situação "EM RESDOM" (sentinela)
  await grafo.invoke(new Command({ resume: "true" }), config);
  await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco → pausa pra CPF
  const rFinal = await identificarComCpf(config);
  const final = rFinal as { statusFinal?: string; motivoHandoff?: string };
  assert.equal(final.statusFinal, "concluido", "'EM RESDOM' deveria ser reconhecido como 'RESDOM' (situação permitida)");
  assert.equal(final.motivoHandoff, undefined);
});

// Issue #183 — CPF do assistido esgotando as 3 tentativas entra no subgrafo
// cadastroPessoa (nome, data de nascimento, endereço via coletarEndereco) —
// mesmo racional de violenciaDomestica/graph.ts (issue #171). Endereço:
// mock padrão de consultarCep (verde.ts) devolve logradouro/bairro/
// município/UF completos — só número e complemento pausam de verdade
// (mesmo racional de coletarEndereco/graph.test.ts).
test("esgota as 3 tentativas de CPF do assistido → entra em cadastro; sucesso conclui normalmente (issue #183)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config); // tem processo?
  await grafo.invoke(new Command({ resume: "true" }), config); // → pergunta número do processo
  await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config); // número do processo (origem SEEU, mock padrão)
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // RG
  await grafo.invoke(new Command({ resume: "true" }), config); // confirma nome
  await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco → pausa pra CPF

  const t1 = await grafo.invoke(new Command({ resume: "00000000000" }), config); // cpf sentinela "não encontrado"
  assert.match(pergunta(t1)?.pergunta ?? "", /tentativa 1 de 3/);
  await grafo.invoke(new Command({ resume: "Sim" }), config); // quer tentar de novo
  const t2 = await grafo.invoke(new Command({ resume: "00000000000" }), config);
  assert.match(pergunta(t2)?.pergunta ?? "", /tentativa 2 de 3/);
  await grafo.invoke(new Command({ resume: "Sim" }), config);
  const t3 = await grafo.invoke(new Command({ resume: "00000000000" }), config); // esgotou → entra em cadastro
  assert.match(pergunta(t3)?.pergunta ?? "", /qual o seu nome completo/);

  await grafo.invoke(new Command({ resume: "Maria de Teste" }), config); // nome
  const rDataNasc = await grafo.invoke(new Command({ resume: "01/01/1990" }), config); // data de nascimento → pausa endereço
  assert.match(pergunta(rDataNasc)?.pergunta ?? "", /CEP/);
  await grafo.invoke(new Command({ resume: "20000-000" }), config); // CEP
  await grafo.invoke(new Command({ resume: "123" }), config); // número
  const rFinal = await grafo.invoke(new Command({ resume: "não" }), config); // sem complemento → cadastra

  assert.equal(pergunta(rFinal), undefined);
  const final = rFinal as { statusFinal?: string; motivoHandoff?: string };
  assert.equal(final.statusFinal, "concluido");
  assert.equal(final.motivoHandoff, undefined);
});

test("esgota as 3 tentativas de CPF do assistido → entra em cadastro; cadastro falha → handoff_humano, motivo falha_cadastro (issue #183)", async () => {
  const original = process.env.MOCK_CADASTRO_FALHA;
  process.env.MOCK_CADASTRO_FALHA = "true";
  try {
    const config = novoConfig();
    await grafo.invoke({}, config);
    await grafo.invoke(new Command({ resume: "false" }), config); // sem processo → RG
    await grafo.invoke(new Command({ resume: "11111111111" }), config); // RG
    await grafo.invoke(new Command({ resume: "true" }), config); // confirma nome
    await grafo.invoke(new Command({ resume: "amigo" }), config); // parentesco → pausa pra CPF

    await grafo.invoke(new Command({ resume: "00000000000" }), config); // tentativa 1
    await grafo.invoke(new Command({ resume: "Sim" }), config);
    await grafo.invoke(new Command({ resume: "00000000000" }), config); // tentativa 2
    await grafo.invoke(new Command({ resume: "Sim" }), config);
    await grafo.invoke(new Command({ resume: "00000000000" }), config); // tentativa 3, esgotou → cadastro

    await grafo.invoke(new Command({ resume: "Maria de Teste" }), config); // nome
    await grafo.invoke(new Command({ resume: "01/01/1990" }), config); // data de nascimento → pausa endereço
    await grafo.invoke(new Command({ resume: "20000-000" }), config); // CEP
    await grafo.invoke(new Command({ resume: "123" }), config); // número
    const rFinal = await grafo.invoke(new Command({ resume: "não" }), config); // sem complemento → cadastro falha (mock)

    assert.equal(pergunta(rFinal), undefined);
    const final = rFinal as { statusFinal?: string; motivoHandoff?: string; mensagemFinal?: string };
    assert.equal(final.statusFinal, "handoff_humano");
    assert.equal(final.motivoHandoff, "falha_cadastro");
    assert.match(final.mensagemFinal ?? "", /Não consegui localizar nem cadastrar/);
  } finally {
    process.env.MOCK_CADASTRO_FALHA = original;
  }
});

test("confirmação de nome com 'Sim' literal → concluido (cenário exato do bug real: WhatsApp/Tykhe manda 'Sim', não 'true')", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "Não" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // RG
  const rConfirma = await grafo.invoke(new Command({ resume: "Sim" }), config); // confirma nome, literal
  assert.match(pergunta(rConfirma)?.pergunta ?? "", /parentesco/, "'Sim' deveria confirmar o nome, não mandar pro handoff");
});

test("nome não confirmado → handoff_humano, NÃO pergunta parentesco", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // RG
  const rFinal = await grafo.invoke(new Command({ resume: "false" }), config); // NÃO confirma nome
  assert.equal(pergunta(rFinal), undefined);
  assert.equal((rFinal as { statusFinal?: string }).statusFinal, "handoff_humano");
});

test("RG não encontrado → pergunta se quer tentar de novo (tentativa 1 de 3)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  const r = await grafo.invoke(new Command({ resume: "000000000" }), config); // RG sentinela "não encontrado"
  const p = pergunta(r);
  assert.equal(p?.tipo, "sim_nao");
  assert.match(p?.pergunta ?? "", /tentativa 1 de 3/);
});

test("RG não encontrado, aceita tentar de novo, acha na 2ª → segue pro confirma nome", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "false" }), config);
  await grafo.invoke(new Command({ resume: "000000000" }), config); // 1ª tentativa, não encontrado
  const rPergunta = await grafo.invoke(new Command({ resume: "true" }), config); // quer tentar de novo
  assert.match(pergunta(rPergunta)?.pergunta ?? "", /RG da pessoa presa/);
  const rApenado = await grafo.invoke(new Command({ resume: "11111111111" }), config); // 2ª tentativa, acha
  assert.match(pergunta(rApenado)?.pergunta ?? "", /Confirma que a pessoa presa é/);
});

// Issue #54 — achado ao vivo (WhatsApp/Tykhe): a pessoa pula "Sim" e já
// manda o RG novo direto na pergunta "quer tentar de novo?".
test("RG não encontrado, digita o RG novo DIRETO na confirmação (sem responder 'Sim' antes) → pula a pergunta, consulta na hora", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "false" }), config);
  await grafo.invoke(new Command({ resume: "000000000" }), config); // 1ª tentativa, não encontrado
  // RG novo digitado direto, sem "Sim" antes — não deveria perguntar "qual o RG?" de novo
  const rApenado = await grafo.invoke(new Command({ resume: "11111111111" }), config);
  assert.match(
    pergunta(rApenado)?.pergunta ?? "",
    /Confirma que a pessoa presa é/,
    "deveria pular direto pra consulta no Verde, sem perguntar o RG de novo"
  );
});

test("RG não encontrado, resposta inválida na confirmação (nem sim/não nem RG) → tratada como 'não', handoff_humano", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "false" }), config);
  await grafo.invoke(new Command({ resume: "000000000" }), config);
  const rFinal = await grafo.invoke(new Command({ resume: "não sei" }), config); // nem sim/não nem RG
  assert.equal(pergunta(rFinal), undefined);
  assert.equal((rFinal as { statusFinal?: string }).statusFinal, "handoff_humano", "resposta não reconhecida deveria cair no comportamento atual (tratar como não)");
});

test("RG não encontrado, NÃO quer tentar de novo → handoff_humano direto", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "false" }), config);
  await grafo.invoke(new Command({ resume: "000000000" }), config);
  const rFinal = await grafo.invoke(new Command({ resume: "false" }), config); // não quer tentar de novo
  assert.equal(pergunta(rFinal), undefined);
  assert.equal((rFinal as { statusFinal?: string }).statusFinal, "handoff_humano");
});

test("RG não encontrado 3x seguidas → esgota tentativas, vai direto pro atendente sem perguntar de novo", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "false" }), config);
  const rTentativa1 = await grafo.invoke(new Command({ resume: "000000000" }), config); // tentativa 1
  assert.match(pergunta(rTentativa1)?.pergunta ?? "", /tentativa 1 de 3/);
  await grafo.invoke(new Command({ resume: "true" }), config); // quer tentar de novo → pedirRg
  const rTentativa2 = await grafo.invoke(new Command({ resume: "000000000" }), config); // tentativa 2
  assert.match(pergunta(rTentativa2)?.pergunta ?? "", /tentativa 2 de 3/);
  await grafo.invoke(new Command({ resume: "true" }), config); // quer tentar de novo → pedirRg
  // tentativa 3: esgotou — vai direto pro atendente, SEM perguntar "quer tentar de novo?" de novo
  const rFinal = await grafo.invoke(new Command({ resume: "000000000" }), config);
  assert.equal(pergunta(rFinal), undefined, "não deve perguntar de novo — esgotou as 3 tentativas");
  assert.equal((rFinal as { statusFinal?: string }).statusFinal, "handoff_humano");
});

// Validação de formato do RG (issue #15) — rejeita ANTES de consultar o
// Verde, sem gastar uma das 3 tentativas de "não encontrado" (essa é outra
// contagem, tentativasRg, só incrementada dentro de consultarApenado).
test("RG com letras é rejeitado, repergunta sem consultar o Verde nem contar tentativa", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  const r = await grafo.invoke(new Command({ resume: "abc123" }), config); // RG com letras
  const p = pergunta(r);
  assert.match(p?.pergunta ?? "", /RG da pessoa presa|apenas números/, "deveria repetir a pergunta do RG, não seguir pro Verde");
  assert.equal((r as { dadosApenado?: unknown }).dadosApenado, undefined, "não deveria ter chamado consultarApenado");
  assert.equal((r as { tentativasRg?: number }).tentativasRg, undefined, "rejeição de formato não conta como tentativa de 'não encontrado'");
});

test("RG com letras, corrige na 2ª tentativa → segue pro Verde normalmente", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "false" }), config);
  await grafo.invoke(new Command({ resume: "abc123" }), config); // formato inválido
  const r = await grafo.invoke(new Command({ resume: "11111111111" }), config); // agora válido
  const p = pergunta(r);
  assert.match(p?.pergunta ?? "", /Confirma que a pessoa presa é/, "RG válido deveria seguir o fluxo normalmente, achando a pessoa");
});

// Extração livre — campos pré-preenchidos no state inicial simulam "já veio
// da extração" sem precisar chamar IA de verdade (isso é testado à parte,
// em test-integracao/extrair.test.ts). O que importa aqui é o BYPASS: campo
// já definido pula a pergunta correspondente, mas Verde e a confirmação de
// nome continuam rodando normalmente — extração só pré-preenche, não pula
// verificação nenhuma.
test("extração livre: campos pré-preenchidos pulam a pergunta, mas Verde e confirmação continuam normais", async () => {
  const config = novoConfig();
  const r = await grafo.invoke(
    { temProcesso: true, numeroProcesso: "0000088-95.2026.8.19.0010", rg: "11111111111", parentesco: "amigo" },
    config
  );
  const p = pergunta(r);
  assert.match(
    p?.pergunta ?? "",
    /Confirma que a pessoa presa é/,
    "deveria pular direto pra confirmação de nome, sem perguntar temProcesso/numeroProcesso/rg/parentesco de novo"
  );
  const dadosProcesso = (r as { dadosProcesso?: { encontrado: boolean } }).dadosProcesso;
  const dadosApenado = (r as { dadosApenado?: { encontrado: boolean } }).dadosApenado;
  assert.equal(typeof dadosProcesso?.encontrado, "boolean", "consultarProcesso deveria rodar mesmo com numeroProcesso pré-preenchido");
  assert.equal(dadosApenado?.encontrado, true, "consultarApenado deveria rodar mesmo com rg pré-preenchido");
});

test("extração livre: confirmação de nome NUNCA pula, mesmo com todos os campos pré-preenchidos", async () => {
  const config = novoConfig();
  const r = await grafo.invoke({ temProcesso: false, rg: "11111111111", parentesco: "amigo" }, config);
  const p = pergunta(r);
  assert.equal(p?.tipo, "sim_nao");
  assert.match(p?.pergunta ?? "", /Confirma que a pessoa presa é/);
});

// Bug que esse teste evita reintroduzir: rg é REESCRITO a cada volta do
// retry loop (pedirRg roda de novo quando tentativasRg>=1) — um bypass
// ingênuo ("se rg definido, pula") quebraria o retry, porque o rg da
// tentativa anterior (que FALHOU) também "está definido". O bypass só vale
// na tentativa 0 — ver rgVeioDaExtracao() em graph.ts.
test("extração livre: rg pré-preenchido que falha ainda entra no retry loop normalmente", async () => {
  const config = novoConfig();
  const r = await grafo.invoke({ temProcesso: false, rg: "000000000" }, config); // RG sentinela "não encontrado"
  const p = pergunta(r);
  assert.match(p?.pergunta ?? "", /tentativa 1 de 3/, "deveria cair no retry normal, não travar por causa do bypass");
});

// Mesma ideia do teste acima, mas pra validação de FORMATO (issue #15): rg
// pré-preenchido inválido não pode ser aceito só porque "veio da extração".
test("extração livre: rg pré-preenchido com formato inválido também é rejeitado, não trava o bypass", async () => {
  const config = novoConfig();
  const r = await grafo.invoke({ temProcesso: false, rg: "amigo" }, config); // rg inválido "vindo da extração"
  const p = pergunta(r);
  assert.match(p?.pergunta ?? "", /RG da pessoa presa|apenas números/, "formato inválido deveria reperguntar, mesmo tendo vindo pré-preenchido");
});

test("extração livre ligada (EXTRACAO_LIVRE_IA=true) — grafo pausa na pergunta livre primeiro", async () => {
  const original = process.env.EXTRACAO_LIVRE_IA;
  process.env.EXTRACAO_LIVRE_IA = "true";
  try {
    const config = novoConfig();
    const r = await grafo.invoke({}, config);
    const p = pergunta(r);
    assert.equal(p?.tipo, "texto");
    assert.match(p?.pergunta ?? "", /situação/);
  } finally {
    process.env.EXTRACAO_LIVRE_IA = original;
  }
});

// NODE_ENV continua "test" mesmo com EXTRACAO_LIVRE_IA=true — extrairCamposLivre
// não chama Bedrock de verdade (mesmo guard de reescreverPergunta), então
// nada é extraído e o fluxo segue 100% normal depois da pergunta livre.
test("extração livre ligada, mas NODE_ENV=test — não extrai nada de verdade, segue fluxo normal depois", async () => {
  const original = process.env.EXTRACAO_LIVRE_IA;
  process.env.EXTRACAO_LIVRE_IA = "true";
  try {
    const config = novoConfig();
    await grafo.invoke({}, config); // pausa na pergunta livre
    const r = await grafo.invoke(new Command({ resume: "meu marido tá preso, RG 11111111111, sou esposa" }), config);
    const p = pergunta(r);
    assert.equal(p?.tipo, "sim_nao");
    assert.match(p?.pergunta ?? "", /número do processo/, "nada foi extraído (NODE_ENV=test) — deveria perguntar temProcesso normalmente");
  } finally {
    process.env.EXTRACAO_LIVRE_IA = original;
  }
});

// Issue #17 — resposta livre de pedirParentesco é classificada contra lista
// fechada (não guarda texto cru). MOCK_CLASSIFICACAO_PARENTESCO simula o
// que a IA teria escolhido — classificarParentesco (graph.ts) só lê essa var
// em NODE_ENV=test, mesmo padrão de MOCK_CLASSIFICACAO_FLOWID(S) no orquestrador.
async function ateParentesco(resposta: string, config: ReturnType<typeof novoConfig>) {
  await grafo.invoke({}, config); // tem processo?
  await grafo.invoke(new Command({ resume: "false" }), config); // → RG direto
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // RG
  await grafo.invoke(new Command({ resume: "true" }), config); // confirma nome
  return grafo.invoke(new Command({ resume: resposta }), config); // parentesco
}

test("parentesco: relato indireto com match claro → classificado pro valor da lista (issue #17)", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_PARENTESCO;
  process.env.MOCK_CLASSIFICACAO_PARENTESCO = "Ex-esposo(a)";
  try {
    const config = novoConfig();
    const r = await ateParentesco("Fui casada por dez anos mas já nos divorciamos", config);
    const final = r as { parentesco?: string };
    assert.equal(final.parentesco, "Ex-esposo(a)", "relato indireto deveria virar o valor normalizado da lista, não o texto cru");
  } finally {
    process.env.MOCK_CLASSIFICACAO_PARENTESCO = original;
  }
});

test("parentesco: resposta já é um valor da lista → classifica sem ambiguidade (issue #17)", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_PARENTESCO;
  process.env.MOCK_CLASSIFICACAO_PARENTESCO = "Amigo(a)";
  try {
    const config = novoConfig();
    const r = await ateParentesco("amigo", config);
    const final = r as { parentesco?: string };
    assert.equal(final.parentesco, "Amigo(a)");
  } finally {
    process.env.MOCK_CLASSIFICACAO_PARENTESCO = original;
  }
});

test("parentesco: relato sem match claro → cai em 'Outro', nunca guarda texto cru (issue #17)", async () => {
  const original = process.env.MOCK_CLASSIFICACAO_PARENTESCO;
  delete process.env.MOCK_CLASSIFICACAO_PARENTESCO; // sem mock → classificarParentesco cai no default "Outro"
  try {
    const config = novoConfig();
    const r = await ateParentesco("um relato qualquer sem relação clara", config);
    const final = r as { parentesco?: string };
    assert.equal(final.parentesco, "Outro");
  } finally {
    process.env.MOCK_CLASSIFICACAO_PARENTESCO = original;
  }
});
