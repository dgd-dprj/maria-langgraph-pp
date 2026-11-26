"""#393, item 3 (decisão da Nicole, 2026-11-17): a mensagem final da violência doméstica mostra o nome do órgão, para
a pessoa saber aonde ir, mas não o município. O órgão é escolhido pelo endereço do cadastro, e quem informava o CPF de
outra pessoa via a região dela (#236). Caso gravado aposentado: `vd_via_orq_3` (pr2)."""

from __future__ import annotations

import pytest

from maria.fluxos.violencia_domestica.graph import montar_mensagem_encaminhamento

ORGAO = {"id": 7, "nome": "Juizado de Teste", "enderecos": [{"municipio": "Niterói", "idLocalAtendimento": 1}]}


@pytest.mark.parametrize("urgente", [True, False])
def test_mensagem_traz_o_orgao_e_nao_o_municipio(urgente: bool) -> None:
    mensagem = montar_mensagem_encaminhamento(ORGAO, urgente, 31337)
    assert "Juizado de Teste" in mensagem
    assert "Niterói" not in mensagem
    assert "Protocolo: 31337." in mensagem


def test_texto_exato_do_encaminhamento_urgente() -> None:
    assert montar_mensagem_encaminhamento(ORGAO, True, 31337) == (
        "Como você já tem Boletim de Ocorrência, vou encaminhar seu atendimento com urgência para Juizado de Teste"
        " — sem necessidade de agendamento. Protocolo: 31337."
    )
