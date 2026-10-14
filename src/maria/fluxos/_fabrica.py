"""Compilação dos grafos de fluxo com o checkpointer compartilhado.

Em develop, cada `graph.ts` compila no topo do módulo com
`await criarCheckpointer()` (top-level await). Aqui o checkpointer é preparado
no lifespan da aplicação (`shared/checkpointer.py`), e importar o módulo do
grafo não pode depender disso. Por isso o construtor fica no nível do módulo e
a compilação é adiada para a primeira chamada de `obter()`.

`criar` é a fábrica do `langgraph.json` (Studio e `langgraph dev`): compila sem
checkpointer, porque o servidor do LangGraph injeta o dele.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from maria.shared.checkpointer import obter_checkpointer

GrafoCompilado = CompiledStateGraph[Any, Any, Any, Any]


class FabricaGrafo:
    def __init__(self, construtor: StateGraph[Any, Any, Any, Any]) -> None:
        self._construtor = construtor
        self._compilado: tuple[BaseCheckpointSaver[str], GrafoCompilado] | None = None

    def obter(self) -> GrafoCompilado:
        """O grafo compilado com o checkpointer do processo. Recompila se o
        checkpointer mudou (os testes fecham e reabrem o checkpointer)."""
        checkpointer = obter_checkpointer()
        if self._compilado is None or self._compilado[0] is not checkpointer:
            self._compilado = (checkpointer, self._construtor.compile(checkpointer=checkpointer))
        return self._compilado[1]

    async def criar(self, config: RunnableConfig) -> GrafoCompilado:
        return self._construtor.compile()
