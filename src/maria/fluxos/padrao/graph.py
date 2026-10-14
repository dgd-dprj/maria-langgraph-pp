"""Grafo padrão (develop: `fluxos/padrao/graph.ts`, issues #21 e #22).

Compartilhado por qualquer fluxo planejado (tabela `fluxos_planejados`) sem
grafo próprio: um nó só, sem interrupt, conclui no primeiro invoke. O
isolamento entre conversas é pelo `thread_id`, não pelo `fluxoId`.

Issue #22: categorias de redirecionamento permanente têm `mensagemFixa`. O
`fluxoId` vem da config do run (`contexto_atual()`), o único jeito de este
grafo compartilhado saber qual categoria está rodando.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from maria.fluxos._fabrica import FabricaGrafo, GrafoCompilado
from maria.fluxos.padrao.api import MENSAGEM_CONCLUIDO
from maria.fluxos.padrao.state import PadraoState
from maria.shared import _js
from maria.shared.contexto import contexto_atual
from maria.shared.fluxos_planejados_db import buscar_fluxo_planejado_por_id


async def concluir_com_mensagem_padrao(state: PadraoState) -> dict[str, Any]:
    fluxo_id = contexto_atual().get("fluxoId")
    # `fluxoId ? await buscar(...) : undefined`: string vazia também não busca.
    planejado = await buscar_fluxo_planejado_por_id(fluxo_id) if fluxo_id else None
    mensagem = _js.coalesce(_js.opt(planejado, "mensagemFixa"), MENSAGEM_CONCLUIDO)
    return {"statusFinal": "concluido", "mensagemFinal": mensagem}


_construtor = StateGraph(PadraoState)
_construtor.add_node("concluir", concluir_com_mensagem_padrao)
_construtor.add_edge(START, "concluir")
_construtor.add_edge("concluir", END)

_fabrica = FabricaGrafo(_construtor)
criar_grafo = _fabrica.criar


def obter_grafo() -> GrafoCompilado:
    return _fabrica.obter()
