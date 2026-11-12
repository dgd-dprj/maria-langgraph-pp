"""Tradução de `fluxos/pessoaPresa/graph.test.ts` (develop @ 0aecd98): 40 testes,
na mesma ordem, com o Verde em mock e o checkpointer em memória.

Os `process.env.X = original` de develop viram `monkeypatch.setenv`, que
restaura o valor anterior (em develop, restaurar `undefined` grava a string
"undefined"; nenhum teste depende disso).
"""

import re
from typing import Any

import pytest

from maria.fluxos.pessoa_presa.graph import obter_grafo
from tests.fluxos.conftest import Fluxo, pergunta, texto


def _fluxo() -> Fluxo:
    return Fluxo(obter_grafo(), "teste-grafo")


async def test_primeira_invocacao_pausa_em_pedir_tem_processo() -> None:
    r = await _fluxo().iniciar()
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao"
    assert re.search("número do processo", texto(r))


async def test_tem_processo_true_pergunta_numero_do_processo() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("true")
    assert re.search("Qual o número do processo", texto(r))


async def test_tem_processo_true_consulta_processo_e_segue_pro_rg() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("true", "0000088-95.2026.8.19.0010")
    assert re.search("RG da pessoa presa", texto(r)), "consultarProcesso não deve travar o fluxo"
    assert isinstance(r["dadosProcesso"]["encontrado"], bool)


async def test_tem_processo_false_pula_direto_pro_rg() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("false")
    assert re.search("RG da pessoa presa", texto(r))


async def test_resume_com_sim_literal_funciona_igual() -> None:
    # Achado ao vivo de 2026-08-31: a Tykhe repassa "Sim"/"Não" digitados.
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("Sim")
    assert re.search("Qual o número do processo", texto(r))


async def test_resume_com_false_em_string_nao_quebra() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("false")


async def test_fluxo_completo_sem_processo_nome_confirmado_handoff_issue_49() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("false")
    r_apenado = await f.responder("11111111111")
    assert re.search("Confirma que a pessoa presa é", texto(r_apenado))
    r_confirma = await f.responder("true")
    assert re.search("parentesco", texto(r_confirma))
    r_final = await f.responder("amigo")
    assert pergunta(r_final) is None
    assert r_final["statusFinal"] == "handoff_humano", "sem número do processo não deveria concluir"
    assert r_final["motivoHandoff"] == "sem_numero_processo"
    assert re.search("número do processo", r_final["mensagemFinal"], re.IGNORECASE)


async def test_fluxo_completo_com_processo_nome_confirmado_concluido() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "0000088-95.2026.8.19.0010")
    r_apenado = await f.responder("11111111111")
    assert re.search("Confirma que a pessoa presa é", texto(r_apenado))
    r_confirma = await f.responder("true")
    assert re.search("parentesco", texto(r_confirma))
    r_final = await f.responder("amigo")
    assert r_final["statusFinal"] == "concluido"
    assert r_final.get("motivoHandoff") is None


async def test_fluxo_completo_processo_de_origem_nao_suportada_handoff_issue_51() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("true", "0000000-00.0000.0.00.0000")
    r_apenado = await f.responder("11111111111")
    assert re.search("Confirma que a pessoa presa é", texto(r_apenado))
    r_confirma = await f.responder("true")
    assert re.search("parentesco", texto(r_confirma))
    r_final = await f.responder("amigo")
    assert r_final["statusFinal"] == "handoff_humano"
    assert r_final["motivoHandoff"] == "origem_processo_nao_suportada"
    assert re.search("origem", r_final["mensagemFinal"], re.IGNORECASE)


async def test_fluxo_completo_processo_nao_encontrado_mesmo_motivo_de_origem() -> None:
    f = _fluxo()
    await f.iniciar()
    r_final = await f.responder("true", "000000000", "11111111111", "true", "amigo")
    assert r_final["statusFinal"] == "handoff_humano"
    assert r_final["motivoHandoff"] == "origem_processo_nao_suportada"


@pytest.mark.parametrize(
    "rg",
    [
        pytest.param("22222222222", id="situacao-libertado"),
        pytest.param("33333333333", id="tipo-preso-provisorio"),
        pytest.param("44444444444", id="regime-aberto"),
    ],
)
async def test_fluxo_completo_dados_do_apenado_fora_do_permitido_issue_57(rg: str) -> None:
    # Três testes de develop (situação, tipo de preso e regime), um por sentinela.
    f = _fluxo()
    await f.iniciar()
    r_final = await f.responder("true", "0000088-95.2026.8.19.0010", rg, "true", "amigo")
    assert r_final["statusFinal"] == "handoff_humano"
    assert r_final["motivoHandoff"] == "dados_pessoa_nao_atendidos"


async def test_fluxo_completo_situacao_com_prefixo_em_conclui_issue_57() -> None:
    f = _fluxo()
    await f.iniciar()
    r_final = await f.responder("true", "0000088-95.2026.8.19.0010", "55555555555", "true", "amigo")
    assert r_final["statusFinal"] == "concluido", "'EM RESDOM' deveria ser reconhecido como 'RESDOM'"
    assert r_final.get("motivoHandoff") is None


async def test_esgota_cpf_do_assistido_entra_em_cadastro_e_conclui_issue_183() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("true", "0000088-95.2026.8.19.0010", "11111111111", "true", "amigo")
    t1 = await f.responder("00000000000")
    assert re.search("tentativa 1 de 3", texto(t1))
    await f.responder("Sim")
    t2 = await f.responder("00000000000")
    assert re.search("tentativa 2 de 3", texto(t2))
    await f.responder("Sim")
    t3 = await f.responder("00000000000")
    assert re.search("qual o seu nome completo", texto(t3))
    await f.responder("Maria de Teste")
    r_data_nasc = await f.responder("01/01/1990")
    assert re.search("CEP", texto(r_data_nasc))
    r_confirma = await f.responder("20000-000", "123", "não")
    assert re.search("Confirma que seus dados são", texto(r_confirma))
    r_final = await f.responder("sim")
    assert pergunta(r_final) is None
    assert r_final["statusFinal"] == "concluido"
    assert r_final.get("motivoHandoff") is None


async def test_cpf_do_assistido_com_falha_de_infra_handoff_direto_issue_172() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("false", "11111111111", "true", "amigo")
    r_final = await f.responder("66666666666")
    assert pergunta(r_final) is None, "nem retry de negócio, nem cadastro"
    assert r_final["statusFinal"] == "handoff_humano"
    assert r_final["motivoHandoff"] == "falha_infra_verde"


async def test_esgota_cpf_do_assistido_cadastro_falha_falha_cadastro_issue_183(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CADASTRO_FALHA", "true")
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("false", "11111111111", "true", "amigo")
    await f.responder("00000000000", "Sim", "00000000000", "Sim", "00000000000")
    r_final = await f.responder("Maria de Teste", "01/01/1990", "20000-000", "123", "não")
    assert pergunta(r_final) is None
    assert r_final["statusFinal"] == "handoff_humano"
    assert r_final["motivoHandoff"] == "falha_cadastro"
    assert re.search("Não consegui localizar nem cadastrar", r_final["mensagemFinal"])


async def test_cpf_do_assistido_valido_mas_nao_confirma_issue_189() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("false", "11111111111", "true", "amigo", "11111111111")
    r = await f.responder("não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "assistido_nao_confirmado"


async def test_cadastra_assistido_novo_mas_nao_confirma_issue_189() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    await f.responder("false", "11111111111", "true", "amigo", "00000000000", "Não")
    await f.responder("Maria de Teste", "01/01/1990", "20000-000", "123", "não")
    r = await f.responder("não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "assistido_nao_confirmado"


async def test_sem_via_orquestrador_com_processo_conclui_sem_perguntar_cpf_issue_191() -> None:
    f = _fluxo()
    await f.iniciar()
    r_final = await f.responder("true", "0000088-95.2026.8.19.0010", "11111111111", "true", "amigo")
    assert pergunta(r_final) is None, "deve concluir direto, sem CPF nem confirmação"
    assert r_final["statusFinal"] == "concluido"
    assert r_final.get("motivoHandoff") is None
    assert "dadosPessoa" not in r_final, "identificarAssistido nunca rodou"


async def test_confirmacao_de_nome_com_sim_literal_segue_pro_parentesco() -> None:
    f = _fluxo()
    await f.iniciar()
    r_confirma = await f.responder("Não", "11111111111", "Sim")
    assert re.search("parentesco", texto(r_confirma)), "'Sim' deveria confirmar o nome"


async def test_nome_nao_confirmado_handoff_sem_perguntar_parentesco() -> None:
    f = _fluxo()
    await f.iniciar()
    r_final = await f.responder("false", "11111111111", "false")
    assert pergunta(r_final) is None
    assert r_final["statusFinal"] == "handoff_humano"


async def test_rg_nao_encontrado_pergunta_se_quer_tentar_de_novo() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("false", "000000000")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao"
    assert re.search("tentativa 1 de 3", p["pergunta"])


async def test_rg_nao_encontrado_aceita_tentar_de_novo_e_acha_na_segunda() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("false", "000000000")
    r_pergunta = await f.responder("true")
    assert re.search("RG da pessoa presa", texto(r_pergunta))
    r_apenado = await f.responder("11111111111")
    assert re.search("Confirma que a pessoa presa é", texto(r_apenado))


async def test_rg_nao_encontrado_digita_rg_novo_direto_na_confirmacao_issue_54() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("false", "000000000")
    r_apenado = await f.responder("11111111111")
    assert re.search("Confirma que a pessoa presa é", texto(r_apenado)), "deveria consultar direto, sem perguntar o RG de novo"


async def test_rg_nao_encontrado_resposta_invalida_na_confirmacao_vira_nao() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("false", "000000000")
    r_final = await f.responder("não sei")
    assert pergunta(r_final) is None
    assert r_final["statusFinal"] == "handoff_humano"


async def test_rg_nao_encontrado_nao_quer_tentar_handoff_direto() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("false", "000000000")
    r_final = await f.responder("false")
    assert pergunta(r_final) is None
    assert r_final["statusFinal"] == "handoff_humano"


async def test_rg_nao_encontrado_3x_esgota_e_vai_pro_atendente() -> None:
    f = _fluxo()
    await f.iniciar()
    await f.responder("false")
    r1 = await f.responder("000000000")
    assert re.search("tentativa 1 de 3", texto(r1))
    await f.responder("true")
    r2 = await f.responder("000000000")
    assert re.search("tentativa 2 de 3", texto(r2))
    await f.responder("true")
    r_final = await f.responder("000000000")
    assert pergunta(r_final) is None, "esgotou as 3 tentativas"
    assert r_final["statusFinal"] == "handoff_humano"


async def test_rg_com_falha_de_infra_handoff_direto_falha_infra_verde_issue_172() -> None:
    f = _fluxo()
    await f.iniciar()
    r_final = await f.responder("false", "66666666666")
    assert pergunta(r_final) is None
    assert r_final["statusFinal"] == "handoff_humano"
    assert r_final["motivoHandoff"] == "falha_infra_verde"


async def test_rg_com_letras_rejeitado_sem_consultar_verde_nem_contar_tentativa() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("false", "abc123")
    assert re.search("RG da pessoa presa|apenas números", texto(r))
    assert r.get("dadosApenado") is None, "não deveria ter chamado consultarApenado"
    assert r.get("tentativasRg") is None, "rejeição de formato não conta tentativa"


async def test_rg_com_letras_corrige_na_segunda_e_segue() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("false", "abc123", "11111111111")
    assert re.search("Confirma que a pessoa presa é", texto(r))


# ---- #475: a pergunta do RG mostra os formatos aceitos ------------------------------
# Decisão da Nicole (2026-11-12): os dois formatos que a Maria aceita desde o #343. Cobre os casos aposentados
# pessoa-presa-resposta-texto-sem-opcoes-200, pp_sem_processo e orq_identifica_responde
# (tests/api/casos_aposentados.py).


async def test_475_pergunta_do_rg_mostra_os_formatos_aceitos() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("false")
    assert texto(r) == ("Qual o RG da pessoa presa? Pode escrever só os números ou com pontos e traço. Exemplo: 123456789 ou 12.345.678-9.")


async def test_475_os_dois_formatos_do_exemplo_sao_aceitos() -> None:
    for rg in ("11111111111", "11.111.111-111"):
        f = _fluxo()
        await f.iniciar()
        r = await f.responder("false", rg)
        assert re.search("Confirma que a pessoa presa é", texto(r)), rg


# ---- #394: limite de recusas do RG pelo formato -------------------------------------
# Decisão da Nicole (2026-11-12): a mensagem diz a tentativa e dá um exemplo fictício; na 3ª recusa, a
# conversa vai para o atendimento humano com `motivoHandoff: rg_formato_invalido`. Cobre o caso aposentado
# pp_rg_invalido (tests/api/casos_aposentados.py).


async def test_394_recusa_diz_a_tentativa_e_da_um_exemplo() -> None:
    f = _fluxo()
    await f.iniciar()
    r1 = await f.responder("false", "abc123")
    assert texto(r1) == (
        "Não consegui ler esse RG (tentativa 1 de 3). Escreva só os números do RG da pessoa presa, sem letras. Por exemplo: 123456789."
    )
    r2 = await f.responder("12/345")
    assert texto(r2).startswith("Não consegui ler esse RG (tentativa 2 de 3).")


async def test_394_terceira_recusa_vai_para_o_atendimento_humano_sem_consultar_o_verde() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("false", "abc", "12/345", "não sei o RG")
    assert pergunta(r) is None
    assert (r["statusFinal"], r["motivoHandoff"]) == ("handoff_humano", "rg_formato_invalido")
    assert r.get("dadosApenado") is None, "nenhuma consulta ao Verde"
    # O texto recusado não fica no estado (nem nos metadados).
    assert r.get("rg") is None


async def test_394_rg_certo_depois_de_duas_recusas_segue_normal() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("false", "abc", "12/345", "11.111.111-111")
    assert re.search("Confirma que a pessoa presa é", texto(r))


async def test_394_evento_da_recusa_sem_o_que_foi_digitado(capsys: pytest.CaptureFixture[str]) -> None:
    f = _fluxo()
    await f.iniciar()
    capsys.readouterr()
    await f.responder("false", "ab12c3")
    saida = capsys.readouterr().out
    [linha] = [x for x in saida.splitlines() if '"rg_recusado_formato"' in x]
    assert '"recusa":1' in linha.replace(" ", "")
    assert '"digitos":3' in linha.replace(" ", "")
    assert '"temLetra":true' in linha.replace(" ", "")
    assert "ab12c3" not in saida


# ---- #393: o nome da pessoa presa sai mascarado ------------------------------------
# Decisão da Nicole (2026-11-04): quem digita o RG de qualquer pessoa não vê o nome
# completo dela. Cobre os casos aposentados pessoa-presa-resposta-rg-200,
# pessoa-presa-get-metadados-parciais-200, pp_rg e pp_get_confirma_nome
# (tests/api/casos_aposentados.py).


async def test_393_confirmacao_do_rg_mostra_o_nome_mascarado() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("false", "11111111111")
    assert texto(r) == "Confirma que a pessoa presa é Pessoa T.?"
    assert "de Teste" not in texto(r) and "(mock)" not in texto(r)


def test_393_texto_da_confirmacao_com_nome_real_e_sem_nome() -> None:
    from maria.fluxos.pessoa_presa.graph import texto_confirma_nome

    assert texto_confirma_nome({"dadosApenado": {"encontrado": True, "nome": "JOSE DOS SANTOS PEREIRA"}}) == (
        "Confirma que a pessoa presa é Jose S. P.?"
    )
    assert texto_confirma_nome({}) == "Confirma que a pessoa presa é essa pessoa?"


async def test_extracao_livre_campos_pre_preenchidos_pulam_perguntas_mas_verde_roda() -> None:
    r = await _fluxo().iniciar(
        {"temProcesso": True, "numeroProcesso": "0000088-95.2026.8.19.0010", "rg": "11111111111", "parentesco": "amigo"}
    )
    assert re.search("Confirma que a pessoa presa é", texto(r))
    assert isinstance(r["dadosProcesso"]["encontrado"], bool)
    assert r["dadosApenado"]["encontrado"] is True


async def test_extracao_livre_confirmacao_de_nome_nunca_pula() -> None:
    r = await _fluxo().iniciar({"temProcesso": False, "rg": "11111111111", "parentesco": "amigo"})
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao"
    assert re.search("Confirma que a pessoa presa é", p["pergunta"])


async def test_extracao_livre_rg_pre_preenchido_que_falha_entra_no_retry() -> None:
    r = await _fluxo().iniciar({"temProcesso": False, "rg": "000000000"})
    assert re.search("tentativa 1 de 3", texto(r))


async def test_extracao_livre_rg_pre_preenchido_invalido_e_rejeitado() -> None:
    r = await _fluxo().iniciar({"temProcesso": False, "rg": "amigo"})
    assert re.search("RG da pessoa presa|apenas números", texto(r))


async def test_extracao_livre_ligada_pausa_na_pergunta_livre(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACAO_LIVRE_IA", "true")
    r = await _fluxo().iniciar()
    p = pergunta(r)
    assert p is not None and p["tipo"] == "texto"
    assert re.search("situação", p["pergunta"])


async def test_extracao_livre_ligada_em_teste_nao_extrai_e_segue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACAO_LIVRE_IA", "true")
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("meu marido tá preso, RG 11111111111, sou esposa")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao"
    assert re.search("número do processo", p["pergunta"]), "nada extraído em APP_ENV=test"


async def _ate_parentesco(resposta: str) -> dict[str, Any]:
    f = _fluxo()
    await f.iniciar()
    return await f.responder("false", "11111111111", "true", resposta)


async def test_parentesco_relato_indireto_classificado_issue_17(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_PARENTESCO", "Ex-esposo(a)")
    r = await _ate_parentesco("Fui casada por dez anos mas já nos divorciamos")
    assert r["parentesco"] == "Ex-esposo(a)"


async def test_parentesco_valor_da_lista_issue_17(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_PARENTESCO", "Amigo(a)")
    r = await _ate_parentesco("amigo")
    assert r["parentesco"] == "Amigo(a)"


async def test_parentesco_sem_match_cai_em_outro_issue_17(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOCK_CLASSIFICACAO_PARENTESCO", raising=False)
    r = await _ate_parentesco("um relato qualquer sem relação clara")
    assert r["parentesco"] == "Outro"


# ---- #236: CPF vindo da Tykhe, pelo orquestrador ---------------------------------
# Fora da tradução de develop: decisão de 03/11, na janela das correções (#208).


async def test_cpf_da_tykhe_via_orquestrador_conclui_sem_confirmacao_issue_236() -> None:
    f = _fluxo()
    await f.iniciar({"cpf": "11111111111", "viaOrquestrador": True})
    r = await f.responder("true", "0000088-95.2026.8.19.0010", "11111111111", "true", "amigo")
    assert pergunta(r) is None, "o CPF veio da Tykhe: sem a pergunta com o nome do titular"
    assert r["statusFinal"] == "concluido"
    assert r.get("motivoHandoff") is None
    assert r["dadosPessoa"]["encontrado"] is True


async def test_cpf_digitado_via_orquestrador_continua_com_confirmacao_issue_236() -> None:
    f = _fluxo()
    await f.iniciar({"viaOrquestrador": True})
    r_confirma = await f.responder("true", "0000088-95.2026.8.19.0010", "11111111111", "true", "amigo", "11111111111")
    assert re.search("Confirma que seus dados são", texto(r_confirma)), "CPF digitado na conversa: confirmação como antes"
    r = await f.responder("sim")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
