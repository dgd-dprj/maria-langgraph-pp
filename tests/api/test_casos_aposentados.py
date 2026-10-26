"""O mecanismo de casos aposentados das conferências contra as fixtures (#321)."""

from __future__ import annotations

from tests.api.casos_aposentados import (
    CASOS_APOSENTADOS,
    CONFERENCIAS,
    CasoAposentado,
    falhas_da_conferencia,
    falhas_que_valem,
    nomes_dos_casos,
    problemas_do_registro,
)
from tests.api.fluxo_de_brinquedo import CASOS_DE_UM_FLUXO_NOVO

ESTE_TESTE = "tests/api/test_casos_aposentados.py"


def test_as_tres_conferencias_e_os_casos_delas() -> None:
    assert {c: len(nomes_dos_casos(c)) for c in CONFERENCIAS} == {"contrato": 50, "pr1": 343, "pr2": 313}
    assert set(CASOS_APOSENTADOS) == set(CONFERENCIAS)


def test_o_registro_atual_nao_tem_problemas() -> None:
    assert problemas_do_registro(CASOS_APOSENTADOS) == []


def test_os_casos_medidos_de_um_fluxo_novo_existem() -> None:
    for conferencia, nomes in CASOS_DE_UM_FLUXO_NOVO.items():
        assert nomes <= set(nomes_dos_casos(conferencia)), conferencia


def test_registro_com_problemas_e_recusado() -> None:
    bom = CasoAposentado(issue=321, motivo="fluxo novo", teste=ESTE_TESTE)
    problemas = problemas_do_registro(
        {
            "inexistente": {"fluxos": bom},
            "pr1": {
                "caso_que_nao_existe": bom,
                "fluxos": CasoAposentado(issue=321, motivo="fluxo novo", teste="tests/api/test_nao_existe.py"),
                "fluxos_query": CasoAposentado(issue=0, motivo=" ", teste=ESTE_TESTE),
                "fluxos_head": CasoAposentado(issue=99999, motivo="sem citação", teste="tests/api/test_campos_posteriores.py"),
            },
        }
    )
    assert problemas == [
        "conferência inexistente: inexistente",
        "pr1/caso_que_nao_existe: o caso não existe nessa conferência",
        "pr1/fluxos: o teste tests/api/test_nao_existe.py não existe",
        "pr1/fluxos_query: issue e motivo são obrigatórios",
        "pr1/fluxos_head: o teste tests/api/test_campos_posteriores.py não cita o caso nem a #99999",
    ]


def test_caso_fora_da_lista_mantem_as_falhas() -> None:
    assert falhas_que_valem("fluxos", ["fluxos: corpo diferente"], {}) == ["fluxos: corpo diferente"]
    assert falhas_que_valem("fluxos", [], {}) == []


def test_caso_aposentado_sai_da_comparacao() -> None:
    aposentados = {"fluxos": CasoAposentado(issue=321, motivo="fluxo novo", teste=ESTE_TESTE)}
    assert falhas_que_valem("fluxos", ["fluxos: corpo diferente"], aposentados) == []


def test_caso_aposentado_que_volta_a_bater_falha() -> None:
    # Entrada esquecida: o caso aposentado voltou a bater com a gravação.
    aposentados = {"fluxos": CasoAposentado(issue=321, motivo="fluxo novo", teste=ESTE_TESTE)}
    falhas = falhas_que_valem("fluxos", [], aposentados)
    assert len(falhas) == 1
    assert "voltou a bater" in falhas[0]


def test_falhas_da_conferencia_aplica_a_lista_caso_a_caso() -> None:
    por_caso = {"fluxos": ["fluxos: corpo diferente"], "health": [], "barra_final": ["barra_final: status"]}
    aposentados = {"fluxos": CasoAposentado(issue=321, motivo="fluxo novo", teste=ESTE_TESTE)}
    assert falhas_da_conferencia(por_caso, aposentados) == ["barra_final: status"]
