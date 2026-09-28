import { test } from "node:test";
import assert from "node:assert/strict";
import { Command } from "@langchain/langgraph";
import { grafo } from "./graph.js";

let contador = 0;
function novoConfig() {
  contador += 1;
  return { configurable: { thread_id: `teste-grafo-vd-${contador}` } };
}

function pergunta(resultado: unknown): { pergunta: string; tipo: string; opcoes?: string[] } | undefined {
  return (resultado as { __interrupt__?: Array<{ value: { pergunta: string; tipo: string; opcoes?: string[] } }> }).__interrupt__?.[0]?.value;
}

// Issue #176 — subgrafo coletarEndereco, embutido dentro de cadastroPessoa
// (issue #171): CEP → consulta Verde → só pergunta o que a Verde não trouxe.
// Mock padrão de consultarCep (verde.ts) devolve logradouro/bairro/
// município/UF completos — só número e complemento (nunca vêm do CEP)
// ficam de pausa real. Devolve o resultado da ÚLTIMA resposta (complemento),
// que já é o desfecho do cadastro (POST no Verde roda logo depois, sem
// interrupt no meio, e o resto do fluxo pai também não pausa de novo).
async function preencherEndereco(config: { configurable: { thread_id: string } }) {
  await grafo.invoke(new Command({ resume: "20000-000" }), config); // CEP
  await grafo.invoke(new Command({ resume: "123" }), config); // número (nunca vem do CEP)
  return grafo.invoke(new Command({ resume: "não" }), config); // sem complemento → cadastra
}

// Issue #189 — depois de achar por CPF ou cadastrar com sucesso, o
// subgrafo pergunta "Confirma que seus dados são: <nome>?" antes de
// devolver pro fluxo pai. "sim" segue o caminho de sempre (comportamento
// inalterado pra quem confirma) — recusa tem teste dedicado próprio.
async function confirmarAssistido(config: { configurable: { thread_id: string } }) {
  return grafo.invoke(new Command({ resume: "sim" }), config);
}

test("1ª invocação pausa em pedirEhVitima", async () => {
  const config = novoConfig();
  const r = await grafo.invoke({}, config);
  const p = pergunta(r);
  assert.equal(p?.tipo, "sim_nao");
  assert.match(p?.pergunta ?? "", /vítima de violência doméstica/);
});

test("não é vítima → handoff_humano direto, sem mais perguntas", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  const r = await grafo.invoke(new Command({ resume: "false" }), config);
  assert.equal(pergunta(r), undefined);
  assert.equal((r as { statusFinal?: string }).statusFinal, "handoff_humano");
  assert.equal((r as { motivoHandoff?: string }).motivoHandoff, "nao_e_vitima");
});

test("é vítima → pergunta sobre processo em seguida", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  const r = await grafo.invoke(new Command({ resume: "true" }), config);
  const p = pergunta(r);
  assert.match(p?.pergunta ?? "", /processo relacionado/);
});

// Issue #110 — mesmo racional do retry (issue #77): número de processo
// digitado direto na pergunta INICIAL "existe processo?" (não só no
// retry) já é reconhecido pelo formato, pulando pedirNumeroProcesso.
test("processo digitado direto na pergunta inicial 'existe processo?' → pula pedirNumeroProcesso, consulta direto (issue #110)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  const r = await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config); // número direto, não "sim"
  assert.match(pergunta(r)?.pergunta ?? "", /Boletim de Ocorrência/, "deveria pular pedirNumeroProcesso e ir direto pra consulta");
  assert.equal((r as { dadosProcesso?: { encontrado: boolean } }).dadosProcesso?.encontrado, true, "deveria ter consultado com o número digitado, não perdido o valor");
});

test("resposta que não é sim/não nem processo na pergunta inicial → trata como não tem processo, sem regressão (issue #110)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  const r = await grafo.invoke(new Command({ resume: "não sei" }), config);
  assert.match(pergunta(r)?.pergunta ?? "", /Boletim de Ocorrência/, "resposta não reconhecida deveria cair no fallback de 'não tem processo' (pula pro RO), igual antes");
});

test("tem processo → pede número, consulta Verde (informativo), segue pro RO normalmente", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  const rNumero = await grafo.invoke(new Command({ resume: "true" }), config); // tem processo
  assert.match(pergunta(rNumero)?.pergunta ?? "", /número do processo/);
  const r = await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config);
  assert.match(pergunta(r)?.pergunta ?? "", /Boletim de Ocorrência/, "consultarProcesso não deve travar o fluxo");
  const dadosProcesso = (r as { dadosProcesso?: { encontrado: boolean } }).dadosProcesso;
  assert.equal(typeof dadosProcesso?.encontrado, "boolean");
});

// Issue #75 — processo não encontrado dá até 3 tentativas, mas diferente
// de RG/CPF, desistir NUNCA vira handoff — só segue o fluxo sem o número.
test("processo não encontrado → pergunta se quer tentar de novo, depois acerta e segue pro RO (issue #75)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "true" }), config); // tem processo
  const t1 = await grafo.invoke(new Command({ resume: "000000000" }), config); // processo sentinela "não encontrado"
  assert.match(pergunta(t1)?.pergunta ?? "", /Não encontrei esse número de processo \(tentativa 1 de 3\)/);
  await grafo.invoke(new Command({ resume: "Sim" }), config); // quer tentar de novo → pausa pedindo número de novo
  const r = await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config); // número certo
  assert.match(pergunta(r)?.pergunta ?? "", /Boletim de Ocorrência/);
  assert.equal((r as { dadosProcesso?: { encontrado: boolean } }).dadosProcesso?.encontrado, true);
});

test("processo não encontrado, responde 'Não' quer tentar de novo → segue sem processo, SEM handoff (issue #75)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "true" }), config); // tem processo
  await grafo.invoke(new Command({ resume: "000000000" }), config); // não encontrado
  const r = await grafo.invoke(new Command({ resume: "Não" }), config); // não quer tentar de novo
  assert.match(pergunta(r)?.pergunta ?? "", /Boletim de Ocorrência/, "deveria seguir o fluxo, não travar nem dar handoff");
  assert.equal((r as { statusFinal?: string }).statusFinal, undefined, "não deveria concluir/handoff só por causa do processo");
  assert.equal((r as { dadosProcesso?: { encontrado: boolean } }).dadosProcesso?.encontrado, false);
});

test("esgota as 3 tentativas de processo → segue o fluxo direto, sem perguntar de novo e SEM handoff (issue #75)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "true" }), config); // tem processo
  const t1 = await grafo.invoke(new Command({ resume: "000000000" }), config); // tentativa 1
  assert.match(pergunta(t1)?.pergunta ?? "", /tentativa 1 de 3/);
  await grafo.invoke(new Command({ resume: "Sim" }), config); // quer tentar de novo
  const t2 = await grafo.invoke(new Command({ resume: "000000000" }), config); // tentativa 2
  assert.match(pergunta(t2)?.pergunta ?? "", /tentativa 2 de 3/);
  await grafo.invoke(new Command({ resume: "Sim" }), config); // quer tentar de novo
  const r = await grafo.invoke(new Command({ resume: "000000000" }), config); // tentativa 3, esgotou
  assert.match(pergunta(r)?.pergunta ?? "", /Boletim de Ocorrência/, "esgotou as 3 tentativas — deveria seguir o fluxo, não perguntar de novo nem dar handoff");
  assert.equal((r as { statusFinal?: string }).statusFinal, undefined);
});

// Issue #77 — mesmo bug real da #54 (RG) e do teste equivalente de CPF
// acima: número de processo digitado direto (não "Sim") na pergunta de
// retry tem que ser reconhecido pelo formato.
test("processo errado, digita o número novo direto (não 'Sim') na pergunta de retry → pula direto pra consulta (issue #77)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "true" }), config); // tem processo
  await grafo.invoke(new Command({ resume: "000000000" }), config); // processo errado → pausa "tentativa 1"
  const r = await grafo.invoke(new Command({ resume: "0000088-95.2026.8.19.0010" }), config); // número novo direto, não "Sim"
  assert.match(pergunta(r)?.pergunta ?? "", /Boletim de Ocorrência/, "número digitado direto deveria ser aceito e consultado, seguindo pro RO");
  assert.equal((r as { dadosProcesso?: { encontrado: boolean } }).dadosProcesso?.encontrado, true, "deveria ter consultado com o número novo, não desistido");
});

test("sem processo → pula direto pra pergunta do RO", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  const r = await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  assert.match(pergunta(r)?.pergunta ?? "", /Boletim de Ocorrência/);
});

// CPF agora é comum aos 2 ramos (com/sem RO) — os dois precisam de idPessoa
// pra consultar órgão no Verde (decisão de design 2026-09-04, depois de
// descobrir que RO:true também precisa consultar /orgao/violencia-domestica).
test("depois do RO (tem RO), pergunta CPF — comum aos 2 ramos agora", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  const r = await grafo.invoke(new Command({ resume: "true" }), config); // tem RO
  assert.match(pergunta(r)?.pergunta ?? "", /Qual o seu CPF/);
});

test("depois do RO (sem RO), pergunta CPF também", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  const r = await grafo.invoke(new Command({ resume: "false" }), config); // sem RO
  assert.match(pergunta(r)?.pergunta ?? "", /Qual o seu CPF/);
});

test("tem RO, CPF válido → conclui urgente, mensagem cita o órgão real (mock)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "true" }), config); // tem RO
  const rConfirma = await grafo.invoke(new Command({ resume: "11111111111" }), config); // cpf → pausa confirmação (issue #189)
  assert.match(pergunta(rConfirma)?.pergunta ?? "", /Confirma que seus dados são/);
  const r = await confirmarAssistido(config);
  assert.equal(pergunta(r), undefined);
  assert.equal((r as { statusFinal?: string }).statusFinal, "concluido");
  assert.equal((r as { tipoEncaminhamento?: string }).tipoEncaminhamento, "urgente");
  const orgaos = (r as { orgaosViolenciaDomestica?: { orgaos: Array<{ nome: string }> } }).orgaosViolenciaDomestica;
  assert.match(orgaos?.orgaos[0]?.nome ?? "", /Juizado/);
});

// Issue #189 — CPF encontrado, mas a pessoa nega que os dados são dela:
// handoff direto, NÃO tenta cadastro (não confundir "não confirmo" com
// "não achei").
test("tem RO, CPF válido mas NÃO confirma os dados → handoff_humano, motivo assistido_nao_confirmado (issue #189)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "true" }), config); // tem RO
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // cpf → pausa confirmação
  const r = await grafo.invoke(new Command({ resume: "não" }), config); // NÃO confirma
  assert.equal(pergunta(r), undefined);
  const final = r as { statusFinal?: string; motivoHandoff?: string };
  assert.equal(final.statusFinal, "handoff_humano");
  assert.equal(final.motivoHandoff, "assistido_nao_confirmado");
});

// Issue #189 — mesmo racional, agora depois de CADASTRAR (não achar) — a
// pessoa nega os dados que ela mesma acabou de informar (nome/data de
// nascimento/endereço). Também handoff direto, não confunde com falha_cadastro.
test("tem RO, cadastra pessoa nova mas NÃO confirma os dados → handoff_humano, motivo assistido_nao_confirmado (issue #189)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "true" }), config); // tem RO
  await grafo.invoke(new Command({ resume: "00000000000" }), config); // cpf não encontrado
  await grafo.invoke(new Command({ resume: "Não" }), config); // não quer tentar de novo → entra em cadastro
  await grafo.invoke(new Command({ resume: "Maria de Teste" }), config); // nome
  await grafo.invoke(new Command({ resume: "01/01/1990" }), config); // data de nascimento → pausa endereço
  await preencherEndereco(config); // CEP...UF → cadastra → pausa confirmação
  const r = await grafo.invoke(new Command({ resume: "não" }), config); // NÃO confirma
  assert.equal(pergunta(r), undefined);
  const final = r as { statusFinal?: string; motivoHandoff?: string };
  assert.equal(final.statusFinal, "handoff_humano");
  assert.equal(final.motivoHandoff, "assistido_nao_confirmado");
});

// Issue #72 — CPF não encontrado no ramo com RO (o mais urgente) agora dá
// até 3 tentativas antes de desistir, em vez de handoff direto — mesmo
// racional do retry de RG em pessoaPresa.
test("tem RO, CPF não encontrado no Verde (idPessoa=0) → pergunta se quer tentar de novo (issue #72)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "true" }), config); // tem RO
  const r = await grafo.invoke(new Command({ resume: "00000000000" }), config); // cpf sentinela "não encontrado"
  assert.match(pergunta(r)?.pergunta ?? "", /Não encontrei ninguém com esse CPF \(tentativa 1 de 3\)/);
  assert.equal(pergunta(r)?.tipo, "sim_nao");
});

test("tem RO, CPF errado 1x depois acerta → conclui normal (issue #72)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "true" }), config); // tem RO
  await grafo.invoke(new Command({ resume: "00000000000" }), config); // cpf errado (não encontrado)
  await grafo.invoke(new Command({ resume: "Sim" }), config); // quer tentar de novo
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // cpf certo → pausa confirmação
  const r = await confirmarAssistido(config);
  assert.equal(pergunta(r), undefined);
  assert.equal((r as { statusFinal?: string }).statusFinal, "concluido");
  assert.equal((r as { tipoEncaminhamento?: string }).tipoEncaminhamento, "urgente");
});

// Issue #171 — esgotar tentativas de CPF não vira mais handoff direto: entra
// no subgrafo de cadastro (pede nome + data de nascimento, cadastra no
// Verde). Sucesso segue o fluxo normal com o idPessoa novo; falha (aqui
// simulada via MOCK_CADASTRO_FALHA) vira handoff_humano, motivo falha_cadastro.
test("tem RO, CPF errado, responde 'Não' quer tentar de novo → entra em cadastro, sucesso conclui normalmente (issue #171)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "true" }), config); // tem RO
  await grafo.invoke(new Command({ resume: "00000000000" }), config); // cpf errado
  const r1 = await grafo.invoke(new Command({ resume: "Não" }), config); // não quer tentar de novo → entra em cadastro
  assert.match(pergunta(r1)?.pergunta ?? "", /qual o seu nome completo/);
  const r2 = await grafo.invoke(new Command({ resume: "Maria de Teste" }), config); // nome
  assert.match(pergunta(r2)?.pergunta ?? "", /data de nascimento/);
  const r3 = await grafo.invoke(new Command({ resume: "01/01/1990" }), config); // data de nascimento → pausa pra endereço
  assert.match(pergunta(r3)?.pergunta ?? "", /CEP/, "issue #176 — deveria pausar pedindo endereço antes de cadastrar");
  const r4 = await preencherEndereco(config); // CEP...UF → cadastra → pausa confirmação (issue #189)
  assert.match(pergunta(r4)?.pergunta ?? "", /Confirma que seus dados são/);
  const r5 = await confirmarAssistido(config);
  assert.equal(pergunta(r5), undefined);
  assert.equal((r5 as { statusFinal?: string }).statusFinal, "concluido");
  assert.equal((r5 as { tipoEncaminhamento?: string }).tipoEncaminhamento, "urgente");
});

test("tem RO, esgota as 3 tentativas de CPF → entra em cadastro; cadastro falha → handoff_humano, motivo falha_cadastro (issue #171)", async () => {
  const original = process.env.MOCK_CADASTRO_FALHA;
  process.env.MOCK_CADASTRO_FALHA = "true";
  try {
    const config = novoConfig();
    await grafo.invoke({}, config);
    await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
    await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
    await grafo.invoke(new Command({ resume: "true" }), config); // tem RO → pausa pedirCpf
    const t1 = await grafo.invoke(new Command({ resume: "00000000000" }), config); // tentativa 1
    assert.match(pergunta(t1)?.pergunta ?? "", /tentativa 1 de 3/);
    await grafo.invoke(new Command({ resume: "Sim" }), config); // quer tentar de novo → pausa pedirCpf de novo
    const t2 = await grafo.invoke(new Command({ resume: "00000000000" }), config); // tentativa 2
    assert.match(pergunta(t2)?.pergunta ?? "", /tentativa 2 de 3/);
    await grafo.invoke(new Command({ resume: "Sim" }), config); // quer tentar de novo → pausa pedirCpf de novo
    const t3 = await grafo.invoke(new Command({ resume: "00000000000" }), config); // tentativa 3, esgotou → entra em cadastro
    assert.match(pergunta(t3)?.pergunta ?? "", /qual o seu nome completo/, "esgotou as 3 tentativas de CPF — deveria entrar em cadastro, não perguntar CPF de novo");
    await grafo.invoke(new Command({ resume: "Maria de Teste" }), config); // nome
    await grafo.invoke(new Command({ resume: "01/01/1990" }), config); // data de nascimento → pausa pra endereço
    const r = await preencherEndereco(config); // CEP...UF → cadastro falha (mock)
    assert.equal(pergunta(r), undefined);
    assert.equal((r as { statusFinal?: string }).statusFinal, "handoff_humano");
    assert.equal((r as { motivoHandoff?: string }).motivoHandoff, "falha_cadastro");
    assert.match((r as { mensagemFinal?: string }).mensagemFinal ?? "", /Não consegui localizar nem cadastrar/);
  } finally {
    process.env.MOCK_CADASTRO_FALHA = original;
  }
});

// Issue #77 — mesmo bug real que motivou a #54 no RG: se a pessoa manda o
// CPF novo direto (não "Sim") na pergunta de retry, o fluxo tem que
// reconhecer pelo formato, não tratar como "não quer tentar de novo".
test("tem RO, CPF errado, digita o CPF novo direto (não 'Sim') na pergunta de retry → pula direto pra consulta (issue #77)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "true" }), config); // tem RO
  await grafo.invoke(new Command({ resume: "00000000000" }), config); // cpf errado → pausa "tentativa 1"
  const rConfirma = await grafo.invoke(new Command({ resume: "11111111111" }), config); // CPF novo direto, não "Sim" → pausa confirmação
  assert.match(pergunta(rConfirma)?.pergunta ?? "", /Confirma que seus dados são/, "CPF digitado direto deveria ser aceito e consultado, não tratado como 'não quer tentar de novo'");
  const r = await confirmarAssistido(config);
  assert.equal(pergunta(r), undefined, "não deveria pausar de novo depois de confirmar");
  assert.equal((r as { statusFinal?: string }).statusFinal, "concluido");
});

// Issue #127 — depois de consultarPessoa, consultarCep enriquece
// dadosPessoa.enderecoDetalhado com ids (idUf/idBairro/idMunicipio) via
// CEP — mock de consultarCep só devolve idUf, mesmo racional non-blocking
// de outras consultas informativas do fluxo.
test("CPF válido → dadosPessoa.enderecoDetalhado ganha idUf via consultarCep, sem campos de texto (issue #127)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "false" }), config); // sem RO
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // cpf → pausa confirmação
  const r = await confirmarAssistido(config);
  const dadosPessoa = (r as { dadosPessoa?: { enderecoDetalhado?: Record<string, unknown> } }).dadosPessoa;
  assert.equal(dadosPessoa?.enderecoDetalhado?.idUf, 19, "mock de consultarCep deveria preencher idUf");
  assert.equal(dadosPessoa?.enderecoDetalhado?.bairro, undefined, "não deveria mais existir campo de texto bairro");
  assert.equal(dadosPessoa?.enderecoDetalhado?.municipio, undefined, "não deveria mais existir campo de texto municipio");
});

test("sem RO, CPF válido → conclui padrão, mensagem cita o órgão real (mock)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "false" }), config); // sem RO
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // cpf → pausa confirmação
  const r = await confirmarAssistido(config);
  assert.equal(pergunta(r), undefined);
  assert.equal((r as { statusFinal?: string }).statusFinal, "concluido");
  assert.equal((r as { tipoEncaminhamento?: string }).tipoEncaminhamento, "padrao");
  assert.match((r as { resposta?: string; mensagemFinal?: string }).mensagemFinal ?? "", /Coordenação de Defesa/);
});

// Issue #171 — CPF não encontrado entra em cadastro (não tenta mais achar
// órgão com idPessoa=0). Depois de cadastrar com sucesso, sem RO sempre tem
// fallback no Verde (NUDEM > núcleo > DP única) — conclui normal.
test("sem RO, CPF não encontrado no Verde → entra em cadastro, sucesso encontra órgão (fallback do Verde)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "false" }), config); // sem RO
  const t1 = await grafo.invoke(new Command({ resume: "00000000000" }), config); // cpf sentinela "não encontrado"
  await grafo.invoke(new Command({ resume: "Não" }), config); // não quer tentar de novo → entra em cadastro
  await grafo.invoke(new Command({ resume: "Maria de Teste" }), config); // nome
  await grafo.invoke(new Command({ resume: "01/01/1990" }), config); // data de nascimento → pausa pra endereço
  await preencherEndereco(config); // CEP...UF → cadastra → pausa confirmação (issue #189)
  const r = await confirmarAssistido(config);
  assert.match(pergunta(t1)?.pergunta ?? "", /tentativa 1 de 3/);
  assert.equal((r as { statusFinal?: string }).statusFinal, "concluido");
  assert.equal((r as { tipoEncaminhamento?: string }).tipoEncaminhamento, "padrao");
});

test("concluido de verdade inclui encaminhamentoId (POST real no Verde, mock retorna sucesso)", async () => {
  const config = novoConfig();
  await grafo.invoke({}, config);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  await grafo.invoke(new Command({ resume: "false" }), config); // sem RO
  await grafo.invoke(new Command({ resume: "11111111111" }), config); // cpf → pausa confirmação
  const r = await confirmarAssistido(config);
  assert.equal((r as { encaminhamentoId?: number }).encaminhamentoId, 999999);
  assert.match((r as { mensagemFinal?: string }).mensagemFinal ?? "", /Protocolo: 999999/);
});

test("falha ao criar encaminhamento de verdade (MOCK_ENCAMINHAMENTO_FALHA) → handoff_humano, motivo falha_encaminhamento", async () => {
  const original = process.env.MOCK_ENCAMINHAMENTO_FALHA;
  process.env.MOCK_ENCAMINHAMENTO_FALHA = "true";
  try {
    const config = novoConfig();
    await grafo.invoke({}, config);
    await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
    await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
    await grafo.invoke(new Command({ resume: "false" }), config); // sem RO
    await grafo.invoke(new Command({ resume: "11111111111" }), config); // cpf → pausa confirmação
    const r = await confirmarAssistido(config); // confirma — acha órgão, mas encaminhar falha
    assert.equal(pergunta(r), undefined);
    assert.equal((r as { statusFinal?: string }).statusFinal, "handoff_humano");
    assert.equal((r as { motivoHandoff?: string }).motivoHandoff, "falha_encaminhamento");
    assert.equal((r as { encaminhamentoId?: number }).encaminhamentoId, undefined, "não deveria ter id, o encaminhamento falhou");
  } finally {
    process.env.MOCK_ENCAMINHAMENTO_FALHA = original;
  }
});

// Em horário de plantão a regra de órgão muda — usa
// consultarOrgaosPlantaoViolenciaDomestica em vez da consulta normal, RO
// deixa de importar pra ESSA decisão (mas ainda decide urgente x padrão).
test("plantão vigente (MOCK_PLANTAO_VIGENTE) → usa órgão de plantão, não o normal", async () => {
  const original = process.env.MOCK_PLANTAO_VIGENTE;
  process.env.MOCK_PLANTAO_VIGENTE = "true";
  try {
    const config = novoConfig();
    await grafo.invoke({}, config);
    await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
    await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
    await grafo.invoke(new Command({ resume: "false" }), config); // sem RO
    await grafo.invoke(new Command({ resume: "11111111111" }), config); // cpf → pausa confirmação
    const r = await confirmarAssistido(config);
    assert.equal((r as { statusFinal?: string }).statusFinal, "concluido");
    const orgaos = (r as { orgaosViolenciaDomestica?: { orgaos: Array<{ nome: string }> } }).orgaosViolenciaDomestica;
    assert.match(orgaos?.orgaos[0]?.nome ?? "", /Plantão/, "deveria ter usado o órgão de plantão, não o normal (Coordenação/Juizado)");
  } finally {
    process.env.MOCK_PLANTAO_VIGENTE = original;
  }
});

// Órgão de plantão nunca tem fallback pra idAssistido=0 (diferente da
// consulta normal sem RO, que sempre acha algo) — RO nem entra nessa
// decisão (endpoint de plantão não recebe RO). Issue #72: mesmo assim,
// CPF errado agora dá chance de corrigir em vez de handoff direto.
test("plantão vigente + CPF não encontrado → pergunta se quer tentar de novo, depois acerta e conclui", async () => {
  const original = process.env.MOCK_PLANTAO_VIGENTE;
  process.env.MOCK_PLANTAO_VIGENTE = "true";
  try {
    const config = novoConfig();
    await grafo.invoke({}, config);
    await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
    await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
    await grafo.invoke(new Command({ resume: "false" }), config); // sem RO
    const rTentativa = await grafo.invoke(new Command({ resume: "00000000000" }), config); // cpf sentinela "não encontrado"
    assert.match(pergunta(rTentativa)?.pergunta ?? "", /Não encontrei ninguém com esse CPF \(tentativa 1 de 3\)/);
    await grafo.invoke(new Command({ resume: "Sim" }), config); // quer tentar de novo
    await grafo.invoke(new Command({ resume: "11111111111" }), config); // cpf certo → pausa confirmação
    const r = await confirmarAssistido(config);
    assert.equal(pergunta(r), undefined);
    assert.equal((r as { statusFinal?: string }).statusFinal, "concluido");
    const orgaos = (r as { orgaosViolenciaDomestica?: { orgaos: Array<{ nome: string }> } }).orgaosViolenciaDomestica;
    assert.match(orgaos?.orgaos[0]?.nome ?? "", /Plantão/);
  } finally {
    process.env.MOCK_PLANTAO_VIGENTE = original;
  }
});

test("cpf pré-preenchido em dadosConhecidos → não pergunta CPF de novo", async () => {
  const config = novoConfig();
  const r0 = await grafo.invoke({ cpf: "11111111111" }, config);
  assert.match(pergunta(r0)?.pergunta ?? "", /vítima de violência doméstica/);
  await grafo.invoke(new Command({ resume: "true" }), config); // é vítima
  await grafo.invoke(new Command({ resume: "false" }), config); // sem processo
  const rConfirma = await grafo.invoke(new Command({ resume: "false" }), config); // sem RO → deveria pular a pergunta de CPF, ir direto pra confirmação
  assert.match(pergunta(rConfirma)?.pergunta ?? "", /Confirma que seus dados são/, "cpf já veio pronto, não deveria pausar pra perguntar de novo — só a confirmação (issue #189)");
  const r = await confirmarAssistido(config);
  assert.equal(pergunta(r), undefined);
  assert.equal((r as { tipoEncaminhamento?: string }).tipoEncaminhamento, "padrao");
});
