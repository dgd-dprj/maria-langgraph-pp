"""Grafo do fluxo de problemas com plano de saúde (NUDECON, issue #329).

Esqueleto: um nó só, sem interrupt, conclui no primeiro invoke. O fluxo real
(canal, para quem, renda, confirmação) vem nas próximas etapas da #329.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from maria.fluxos._fabrica import FabricaGrafo, GrafoCompilado
from maria.fluxos.plano_saude.api import MENSAGEM_CONCLUIDO
from maria.fluxos.plano_saude.state import PlanoSaudeState


async def concluir(state: PlanoSaudeState) -> dict[str, Any]:
    return {"statusFinal": "concluido", "mensagemFinal": MENSAGEM_CONCLUIDO}


_construtor = StateGraph(PlanoSaudeState)
_construtor.add_node("concluir", concluir)
_construtor.add_edge(START, "concluir")
_construtor.add_edge("concluir", END)

_fabrica = FabricaGrafo(_construtor)
criar_grafo = _fabrica.criar


def obter_grafo() -> GrafoCompilado:
    return _fabrica.obter()
