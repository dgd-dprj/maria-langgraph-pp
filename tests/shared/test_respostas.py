"""Traduzido de `src/shared/respostaSimNao.test.ts` (develop @ 1157a6d, #234)."""

import pytest

from maria.shared.respostas import normalizar_resposta, resposta_eh_nao, resposta_eh_sim


def test_normalizar_resposta_tira_acento_espaco_das_pontas_e_caixa() -> None:
    assert normalizar_resposta("  NÃO ") == "nao"
    assert normalizar_resposta("Recomeçar") == "recomecar"


@pytest.mark.parametrize("resposta", ["true", "sim", "Sim", "SIM", " s ", "S", "yes"])
def test_resposta_eh_sim_aceita_o_contrato_e_o_texto_digitado(resposta: str) -> None:
    assert resposta_eh_sim(resposta)


@pytest.mark.parametrize("resposta", ["false", "não", "talvez", "", "simples"])
def test_resposta_eh_sim_recusa_o_resto(resposta: str) -> None:
    assert not resposta_eh_sim(resposta)


@pytest.mark.parametrize("resposta", ["false", "não", "Não", "NAO", "nao", " n ", "no"])
def test_resposta_eh_nao_aceita_o_contrato_e_o_texto_digitado(resposta: str) -> None:
    assert resposta_eh_nao(resposta)


@pytest.mark.parametrize("resposta", ["true", "sim", "nada", ""])
def test_resposta_eh_nao_recusa_o_resto(resposta: str) -> None:
    assert not resposta_eh_nao(resposta)


def test_trim_do_js_remove_o_bom_e_nao_o_separador() -> None:
    # trim() do JS remove U+FEFF e não remove \x1c, ao contrário do strip().
    assert resposta_eh_nao("﻿não")
    assert not resposta_eh_nao("não\x1c")
