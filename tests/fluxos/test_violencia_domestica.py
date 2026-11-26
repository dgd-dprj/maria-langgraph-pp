"""Tradução de `fluxos/violenciaDomestica/graph.test.ts` (develop @ 0aecd98): 31 testes,
na mesma ordem, com o Verde em mock e o checkpointer em memória."""

import datetime
import re
from typing import Any

import pytest

from maria.fluxos.violencia_domestica.graph import obter_grafo
from tests.fluxos.conftest import Fluxo, pergunta, texto


def _fluxo() -> Fluxo:
    return Fluxo(obter_grafo(), "teste-grafo-vd")


async def _preencher_endereco(f: Fluxo) -> dict[str, Any]:
    # Issue #176: só número e complemento pausam de verdade com o mock do CEP.
    return await f.responder("20000-000", "123", "não")


async def _confirmar_assistido(f: Fluxo) -> dict[str, Any]:
    # Issue #189: "sim" na confirmação dos dados.
    return await f.responder("sim")


async def test_primeira_invocacao_pausa_em_pedir_eh_vitima() -> None:
    f = _fluxo()
    r = await f.iniciar()
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao"
    assert re.search("vítima de violência doméstica", texto(r))


async def test_nao_eh_vitima_handoff_direto_sem_mais_perguntas() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("false")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "nao_e_vitima"


async def test_eh_vitima_pergunta_sobre_processo_em_seguida() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("true")
    assert re.search("processo relacionado", texto(r))


async def test_processo_digitado_direto_na_pergunta_inicial_pula_pedir_numero_issue_110() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true")
    r = await f.responder("0000088-95.2026.8.19.0010")
    assert re.search("Boletim de Ocorrência", texto(r)), "deveria pular pedirNumeroProcesso e ir direto pra consulta"
    assert r["dadosProcesso"]["encontrado"] is True, "deveria ter consultado com o número digitado"


async def test_resposta_nao_reconhecida_na_pergunta_inicial_trata_como_sem_processo_issue_110() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true")
    r = await f.responder("não sei")
    assert re.search("Boletim de Ocorrência", texto(r))


async def test_tem_processo_pede_numero_consulta_verde_e_segue_pro_ro() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true")
    r_numero = await f.responder("true")
    assert re.search("número do processo", texto(r_numero))
    r = await f.responder("0000088-95.2026.8.19.0010")
    assert re.search("Boletim de Ocorrência", texto(r)), "consultarProcesso não deve travar o fluxo"
    assert isinstance(r["dadosProcesso"]["encontrado"], bool)


async def test_processo_nao_encontrado_tenta_de_novo_e_acerta_issue_75() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "true")
    t1 = await f.responder("000000000")
    assert re.search(r"Não encontrei esse número de processo \(tentativa 1 de 3\)", texto(t1))
    await f.responder("Sim")
    r = await f.responder("0000088-95.2026.8.19.0010")
    assert re.search("Boletim de Ocorrência", texto(r))
    assert r["dadosProcesso"]["encontrado"] is True


async def test_processo_nao_encontrado_nao_quer_tentar_segue_sem_handoff_issue_75() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "true", "000000000")
    r = await f.responder("Não")
    assert re.search("Boletim de Ocorrência", texto(r)), "deveria seguir o fluxo, não travar nem dar handoff"
    assert r.get("statusFinal") is None
    assert r["dadosProcesso"]["encontrado"] is False


async def test_esgota_3_tentativas_de_processo_segue_sem_handoff_issue_75() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "true")
    t1 = await f.responder("000000000")
    assert re.search("tentativa 1 de 3", texto(t1))
    await f.responder("Sim")
    t2 = await f.responder("000000000")
    assert re.search("tentativa 2 de 3", texto(t2))
    await f.responder("Sim")
    r = await f.responder("000000000")
    assert re.search("Boletim de Ocorrência", texto(r))
    assert r.get("statusFinal") is None


async def test_processo_errado_digita_numero_novo_direto_no_retry_issue_77() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "true", "000000000")
    r = await f.responder("0000088-95.2026.8.19.0010")
    assert re.search("Boletim de Ocorrência", texto(r))
    assert r["dadosProcesso"]["encontrado"] is True


async def test_sem_processo_pula_direto_pro_ro() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true")
    r = await f.responder("false")
    assert re.search("Boletim de Ocorrência", texto(r))


async def test_depois_do_ro_com_ro_pergunta_cpf() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false")
    r = await f.responder("true")
    assert re.search("Qual o seu CPF", texto(r))


async def test_depois_do_ro_sem_ro_pergunta_cpf_tambem() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false")
    r = await f.responder("false")
    assert re.search("Qual o seu CPF", texto(r))


async def test_tem_ro_cpf_valido_conclui_urgente_com_orgao_do_mock() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "true")
    r = await f.responder("12345678909")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    assert r["tipoEncaminhamento"] == "urgente"
    assert re.search("Juizado", r["orgaosViolenciaDomestica"]["orgaos"][0]["nome"])


async def test_tem_ro_cpf_valido_nao_confirma_dados_assistido_nao_confirmado_issue_189() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("true", "false", "true", "12345678909")
    r = await f.responder("não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "assistido_nao_confirmado"


async def test_tem_ro_cadastra_mas_nao_confirma_dados_assistido_nao_confirmado_issue_189() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("true", "false", "true", "00000000191", "Não", "Maria de Teste", "01/01/1990")
    await _preencher_endereco(f)
    r = await f.responder("não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "assistido_nao_confirmado"


async def test_sem_via_orquestrador_cpf_pre_preenchido_esgota_tentativas_cpf_nao_encontrado_issue_191() -> None:
    f = _fluxo()
    await f.iniciar({"cpf": "00000000000"})
    await f.responder("true", "false")
    t1 = await f.responder("true")
    assert re.search("tentativa 1 de 3", texto(t1))
    await f.responder("Sim")
    t2 = await f.responder("00000000191")
    assert re.search("tentativa 2 de 3", texto(t2))
    await f.responder("Sim")
    r = await f.responder("00000000191")
    assert pergunta(r) is None, "nunca deveria entrar em cadastro"
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "cpf_nao_encontrado"
    assert re.search("Não consegui localizar seus dados com o CPF informado", r["mensagemFinal"])


async def test_tem_ro_cpf_nao_encontrado_pergunta_se_quer_tentar_de_novo_issue_72() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "true")
    r = await f.responder("00000000191")
    assert re.search(r"Não encontrei ninguém com esse CPF \(tentativa 1 de 3\)", texto(r))
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao"


async def test_tem_ro_cpf_errado_depois_acerta_conclui_issue_72() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "true", "00000000191", "Sim")
    r = await f.responder("12345678909")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    assert r["tipoEncaminhamento"] == "urgente"


async def test_tem_ro_cpf_errado_nao_quer_tentar_entra_em_cadastro_e_conclui_issue_171() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("true", "false", "true", "00000000191")
    r1 = await f.responder("Não")
    assert re.search("qual o seu nome completo", texto(r1))
    r2 = await f.responder("Maria de Teste")
    assert re.search("data de nascimento", texto(r2))
    r3 = await f.responder("01/01/1990")
    assert re.search("CEP", texto(r3)), "issue #176: deveria pedir o endereço antes de cadastrar"
    r4 = await _preencher_endereco(f)
    assert re.search("Confirma que seus dados são", texto(r4))
    r5 = await _confirmar_assistido(f)
    assert pergunta(r5) is None
    assert r5["statusFinal"] == "concluido"
    assert r5["tipoEncaminhamento"] == "urgente"


async def test_tem_ro_cpf_com_falha_de_infra_handoff_direto_issue_172() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("true", "false", "true")
    r = await f.responder("66666666070")
    assert pergunta(r) is None, "nem retry de negócio, nem cadastro"
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "falha_infra_verde"


async def test_tem_ro_esgota_cpf_cadastro_falha_falha_cadastro_issue_171(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CADASTRO_FALHA", "true")
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("true", "false", "true")
    t1 = await f.responder("00000000191")
    assert re.search("tentativa 1 de 3", texto(t1))
    await f.responder("Sim")
    t2 = await f.responder("00000000191")
    assert re.search("tentativa 2 de 3", texto(t2))
    await f.responder("Sim")
    t3 = await f.responder("00000000191")
    assert re.search("qual o seu nome completo", texto(t3)), "esgotou as 3 tentativas de CPF: deveria entrar em cadastro"
    await f.responder("Maria de Teste", "01/01/1990")
    r = await _preencher_endereco(f)
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "falha_cadastro"
    assert re.search("Não consegui localizar nem cadastrar", r["mensagemFinal"])


async def test_tem_ro_cpf_errado_digita_cpf_novo_direto_no_retry_issue_77() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "true", "00000000191")
    r = await f.responder("12345678909")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"


async def test_cpf_valido_endereco_detalhado_ganha_id_uf_via_consultar_cep_issue_127() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "false")
    r = await f.responder("12345678909")
    endereco = r["dadosPessoa"]["enderecoDetalhado"]
    assert endereco["idUf"] == 19
    assert "bairro" not in endereco
    assert "municipio" not in endereco


async def test_sem_ro_cpf_valido_conclui_padrao_com_orgao_do_mock() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "false")
    r = await f.responder("12345678909")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    assert r["tipoEncaminhamento"] == "padrao"
    assert re.search("Coordenação de Defesa", r["mensagemFinal"])


async def test_sem_ro_cpf_nao_encontrado_entra_em_cadastro_e_acha_orgao() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("true", "false", "false")
    t1 = await f.responder("00000000191")
    await f.responder("Não", "Maria de Teste", "01/01/1990")
    await _preencher_endereco(f)
    r = await _confirmar_assistido(f)
    assert re.search("tentativa 1 de 3", texto(t1))
    assert r["statusFinal"] == "concluido"
    assert r["tipoEncaminhamento"] == "padrao"


async def test_concluido_inclui_encaminhamento_id() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "false")
    r = await f.responder("12345678909")
    assert r["encaminhamentoId"] == 999999
    assert re.search("Protocolo: 999999", r["mensagemFinal"])


async def test_falha_ao_criar_encaminhamento_falha_encaminhamento(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_ENCAMINHAMENTO_FALHA", "true")
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "false")
    r = await f.responder("12345678909")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "falha_encaminhamento"
    assert r.get("encaminhamentoId") is None, "o encaminhamento falhou"


async def test_plantao_vigente_usa_orgao_de_plantao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_PLANTAO_VIGENTE", "true")
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "false")
    r = await f.responder("12345678909")
    assert r["statusFinal"] == "concluido"
    assert re.search("Plantão", r["orgaosViolenciaDomestica"]["orgaos"][0]["nome"])


async def test_plantao_vigente_cpf_nao_encontrado_tenta_de_novo_e_conclui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_PLANTAO_VIGENTE", "true")
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "false")
    r_tentativa = await f.responder("00000000191")
    assert re.search(r"Não encontrei ninguém com esse CPF \(tentativa 1 de 3\)", texto(r_tentativa))
    await f.responder("Sim")
    r = await f.responder("12345678909")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    assert re.search("Plantão", r["orgaosViolenciaDomestica"]["orgaos"][0]["nome"])


async def test_cpf_pre_preenchido_nao_pergunta_cpf_de_novo() -> None:
    f = _fluxo()
    r0 = await f.iniciar({"cpf": "11111111111"})
    assert re.search("vítima de violência doméstica", texto(r0))
    await f.responder("true", "false")
    r = await f.responder("false")
    assert pergunta(r) is None, "cpf já veio pronto: nem pergunta, nem confirmação"
    assert r["tipoEncaminhamento"] == "padrao"


# ---- #236: CPF vindo da Tykhe, pelo orquestrador ---------------------------------
# Fora da tradução de develop: decisão de 03/11, na janela das correções (#208).


async def test_cpf_da_tykhe_via_orquestrador_conclui_sem_confirmacao_issue_236() -> None:
    f = _fluxo()
    await f.iniciar({"cpf": "11111111111", "viaOrquestrador": True})
    await f.responder("true", "false")
    r = await f.responder("true")
    assert pergunta(r) is None, "o CPF veio da Tykhe: sem a pergunta com o nome do titular"
    assert r["statusFinal"] == "concluido"
    assert r["tipoEncaminhamento"] == "urgente"
    assert r.get("confirmaAssistido") is None


async def test_cpf_da_tykhe_nao_encontrado_cpf_digitado_continua_com_confirmacao_issue_236() -> None:
    f = _fluxo()
    await f.iniciar({"cpf": "00000000000", "viaOrquestrador": True})
    await f.responder("true", "false")
    t1 = await f.responder("true")
    assert re.search("tentativa 1 de 3", texto(t1))
    r_confirma = await f.responder("12345678909")
    assert re.search("Confirma que seus dados são", texto(r_confirma)), "CPF digitado na conversa: confirmação como antes"
    r = await f.responder("não")
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "assistido_nao_confirmado"


# ---- #565: plantão vigente sem órgão para a vítima -------------------------------------------------------------------
# Decisão do Felipe (2026-11-26): dia útil, o humano; sábado, domingo ou feriado nacional ou estadual, o 129.


async def _ate_o_orgao_de_plantao_sem_orgao(monkeypatch: pytest.MonkeyPatch, util: bool | None) -> dict[str, Any]:
    monkeypatch.setenv("MOCK_PLANTAO_VIGENTE", "true")

    async def sem_orgao(*_: Any) -> dict[str, Any]:
        return {"encontrado": False, "orgaos": []}

    async def hoje() -> bool | None:
        return util

    monkeypatch.setattr("maria.fluxos.violencia_domestica.graph.consultar_orgaos_plantao_violencia_domestica", sem_orgao)
    monkeypatch.setattr("maria.fluxos.violencia_domestica.graph.hoje_e_dia_util", hoje)
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "false")
    return await f.responder("12345678909")


async def test_565_plantao_sem_orgao_em_dia_util_transfere_ao_humano_sem_o_129(monkeypatch: pytest.MonkeyPatch) -> None:
    r = await _ate_o_orgao_de_plantao_sem_orgao(monkeypatch, True)
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "sem_orgao_disponivel"
    assert "129" not in r["mensagemFinal"]
    assert re.search("atendente humano", r["mensagemFinal"])


@pytest.mark.parametrize("util", [False, None])
async def test_565_plantao_sem_orgao_em_dia_nao_util_ou_sem_saber_manda_o_129(monkeypatch: pytest.MonkeyPatch, util: bool | None) -> None:
    r = await _ate_o_orgao_de_plantao_sem_orgao(monkeypatch, util)
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "sem_orgao_disponivel"
    assert "129" in r["mensagemFinal"]


async def test_565_sem_plantao_vigente_continua_como_antes(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: list[int] = []

    async def hoje() -> bool | None:
        chamadas.append(1)
        return True

    monkeypatch.setattr("maria.fluxos.violencia_domestica.graph.hoje_e_dia_util", hoje)
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "false")
    r = await f.responder("12345678909")
    assert chamadas == [], "sem plantão vigente a data nem é consultada"
    assert r["statusFinal"] == "concluido"


async def test_565_mensagem_do_verde_com_contactar_crc_continua_valendo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_PLANTAO_VIGENTE", "true")

    async def crc(*_: Any) -> dict[str, Any]:
        return {"encontrado": False, "orgaos": [], "contactarCrc": True, "mensagemCrc": "Mensagem própria do Verde."}

    async def hoje() -> bool | None:
        return True

    monkeypatch.setattr("maria.fluxos.violencia_domestica.graph.consultar_orgaos_plantao_violencia_domestica", crc)
    monkeypatch.setattr("maria.fluxos.violencia_domestica.graph.hoje_e_dia_util", hoje)
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "false", "false")
    r = await f.responder("12345678909")
    assert r["mensagemFinal"] == "Mensagem própria do Verde."


@pytest.mark.parametrize(
    ("data", "feriado", "esperado"),
    [
        (datetime.date(2026, 11, 26), False, True),  # quinta-feira comum
        (datetime.date(2026, 11, 28), False, False),  # sábado
        (datetime.date(2026, 11, 29), False, False),  # domingo
        (datetime.date(2026, 11, 20), True, False),  # sexta-feira, Consciência Negra (estadual)
        (datetime.date(2026, 11, 26), None, None),  # o Verde não respondeu
    ],
)
async def test_565_e_dia_util(monkeypatch: pytest.MonkeyPatch, data: datetime.date, feriado: bool | None, esperado: bool | None) -> None:
    from maria.fluxos.violencia_domestica import graph

    chamadas: list[datetime.date] = []

    async def falso(d: datetime.date) -> bool | None:
        chamadas.append(d)
        return feriado

    monkeypatch.setattr(graph, "consultar_feriado_nacional_ou_estadual", falso)
    assert await graph.e_dia_util(data) is esperado
    assert chamadas == ([] if data.weekday() >= 5 else [data]), "fim de semana nem consulta o feriado"
