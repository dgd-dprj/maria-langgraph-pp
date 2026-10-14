"""Execução dos subgrafos em testes: um grafo envelope com `InMemorySaver`, como
o `MemorySaver` dos testes de develop (`coletarEndereco/graph.test.ts:11-15`).

`APP_ENV=test` (conftest raiz) mantém o `preparar_pergunta` sem IA, e o Verde
fica em modo mock porque `VERDE_JWT_TOKEN` está vazio nos testes.
"""

from collections.abc import Sequence
from itertools import count
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

# Fixtures do transporte falso do Verde (teste 8 da spec).
from tests.integracoes.conftest import transporte, verde_real  # noqa: F401

_ids = count(1)


def envelope(estado: type, *subgrafos: Any) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Pai mínimo que roda os subgrafos em sequência, cada um como nó."""
    construtor: StateGraph[Any, Any, Any, Any] = StateGraph(estado)
    anterior = START
    for i, subgrafo in enumerate(subgrafos):
        nome = f"sub{i}"
        construtor.add_node(nome, subgrafo)
        construtor.add_edge(anterior, nome)
        anterior = nome
    construtor.add_edge(anterior, END)
    return construtor.compile(checkpointer=InMemorySaver())


class Conversa:
    """Uma conversa num thread: guarda as perguntas feitas e responde em ordem."""

    def __init__(self, grafo: CompiledStateGraph[Any, Any, Any, Any]) -> None:
        self.grafo = grafo
        self.config: Any = {"configurable": {"thread_id": f"t{next(_ids)}"}}
        self.perguntas: list[dict[str, Any]] = []
        self._resultado: dict[str, Any] = {}

    def _registrar(self, resultado: dict[str, Any]) -> None:
        self._resultado = resultado
        pendentes = resultado.get("__interrupt__") or []
        if pendentes:
            self.perguntas.append(pendentes[0].value)

    @property
    def pendente(self) -> dict[str, Any] | None:
        pendentes = self._resultado.get("__interrupt__") or []
        return pendentes[0].value if pendentes else None

    async def iniciar(self, entrada: dict[str, Any]) -> "Conversa":
        self._registrar(await self.grafo.ainvoke(entrada, self.config))
        return self

    async def responder(self, *respostas: str) -> "Conversa":
        for resposta in respostas:
            assert self.pendente is not None, f"sem pergunta pendente para responder {resposta!r}"
            self._registrar(await self.grafo.ainvoke(Command(resume=resposta), self.config))
        return self

    async def estado(self) -> dict[str, Any]:
        return dict((await self.grafo.aget_state(self.config)).values)


def textos(perguntas: Sequence[dict[str, Any]]) -> list[str]:
    return [p["pergunta"] for p in perguntas]
