"""Um fluxo extra, registrado só durante um teste, para medir o que um fluxo novo muda nas
conferências contra as fixtures (#321). Reaproveita o grafo padrão: o que importa é o registro."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from maria.fluxos import FluxoConfig, fluxos_por_id
from maria.fluxos.padrao import api as api_padrao
from maria.fluxos.padrao.graph import obter_grafo
from tests.api.casos_aposentados import CONFERENCIAS, CasoAposentado

ID_BRINQUEDO = "0b1d7c1e-0000-4000-8000-00000000b21d"

# Casos que um fluxo novo muda, medidos com este fluxo em 2026-10-23 (#321): todos são `GET /fluxos`
# respondido com 200, cujo corpo é a lista de fluxos. Inclui as autenticações que a API aceita (espaços
# a mais depois de "Bearer") e o caminho com escape. HEAD e os erros na mesma rota não mudam.
CASOS_DE_UM_FLUXO_NOVO: dict[str, set[str]] = {
    "contrato": {"fluxos-200"},
    "pr1": {"fluxos", "fluxos_query", "auth_bearer_espacos_fluxos", "auth_bearer_duplo_espaco_fluxos"},
    "pr2": {"rota_get_fluxos_codificado"},
}


def registrar_fluxo_de_brinquedo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        fluxos_por_id,
        ID_BRINQUEDO,
        FluxoConfig(
            nome="fluxo-de-brinquedo",
            descricao="Fluxo de teste, registrado só durante a medição da #321.",
            obter_grafo=obter_grafo,
            extrair_metadados=api_padrao.extrair_metadados_padrao,
            mensagem_concluido=api_padrao.MENSAGEM_CONCLUIDO,
            mensagem_handoff=api_padrao.MENSAGEM_HANDOFF,
        ),
    )


def casos_que_falharam(por_caso: Mapping[str, list[str]]) -> set[str]:
    return {nome for nome, falhas in por_caso.items() if falhas}


def aposentados_do_brinquedo(conferencia: str) -> dict[str, CasoAposentado]:
    """Os casos medidos, aposentados como um fluxo novo faria."""
    return {
        nome: CasoAposentado(issue=321, motivo="fluxo novo muda a lista de GET /fluxos", teste=CONFERENCIAS[conferencia])
        for nome in CASOS_DE_UM_FLUXO_NOVO[conferencia]
    }
