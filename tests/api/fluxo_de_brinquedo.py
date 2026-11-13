"""Um fluxo extra, registrado só durante um teste, para medir o que um fluxo novo muda nas
conferências contra as fixtures (#321). Reaproveita o grafo padrão: o que importa é o registro."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from maria.fluxos import FluxoConfig, fluxos_por_id
from maria.fluxos.padrao import api as api_padrao
from maria.fluxos.padrao.graph import obter_grafo
from tests.api.casos_aposentados import CASOS_APOSENTADOS, CONFERENCIAS, CasoAposentado

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


def aposentados_por_outro_motivo(conferencia: str) -> dict[str, CasoAposentado]:
    """Casos aposentados por uma mudança de comportamento, e não por fluxo novo (a #393, por exemplo).
    Eles falham com ou sem o fluxo de brinquedo, então ficam fora da medição do que um fluxo novo muda."""
    return {nome: caso for nome, caso in CASOS_APOSENTADOS[conferencia].items() if nome not in CASOS_DE_UM_FLUXO_NOVO[conferencia]}


def casos_que_falharam(por_caso: Mapping[str, list[str]], conferencia: str) -> set[str]:
    """Os casos que falharam com o fluxo de brinquedo, sem os aposentados por outro motivo."""
    return {nome for nome, falhas in por_caso.items() if falhas} - set(aposentados_por_outro_motivo(conferencia))


def aposentados_do_brinquedo(conferencia: str) -> dict[str, CasoAposentado]:
    """Os casos medidos, aposentados como um fluxo novo faria, mais os aposentados por outro motivo."""
    return {
        nome: CasoAposentado(issue=321, motivo="fluxo novo muda a lista de GET /fluxos", teste=CONFERENCIAS[conferencia])
        for nome in CASOS_DE_UM_FLUXO_NOVO[conferencia]
    } | aposentados_por_outro_motivo(conferencia)
