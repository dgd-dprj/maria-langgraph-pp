"""Execução dos fluxos em testes, como os `graph.test.ts` de develop.

O checkpointer é o da aplicação, em memória: sem `DATABASE_URL` (o conftest
raiz não carrega `.env`), `inicializar_checkpointer()` devolve `InMemorySaver`.
`APP_ENV=test` mantém o `preparar_pergunta` sem IA e o parentesco no mock; o
Verde fica em modo mock porque `VERDE_JWT_TOKEN` está vazio.
"""

from collections.abc import AsyncIterator
from itertools import count
from typing import Any

import pytest
from langgraph.types import Command

from maria.fluxos._fabrica import GrafoCompilado
from maria.shared.checkpointer import fechar_checkpointer, inicializar_checkpointer

# Fixtures do transporte falso do Verde.
from tests.integracoes.conftest import transporte, verde_real  # noqa: F401

_ids = count(1)


@pytest.fixture(autouse=True)
async def checkpointer() -> AsyncIterator[None]:
    await inicializar_checkpointer()
    yield
    await fechar_checkpointer()


def novo_config(prefixo: str = "teste-fluxo", **configurable: Any) -> Any:
    return {"configurable": {"thread_id": f"{prefixo}-{next(_ids)}", **configurable}}


def pergunta(resultado: dict[str, Any]) -> dict[str, Any] | None:
    """`__interrupt__?.[0]?.value` de develop."""
    pendentes = resultado.get("__interrupt__") or []
    return pendentes[0].value if pendentes else None


def texto(resultado: dict[str, Any]) -> str:
    """`pergunta(r)?.pergunta ?? ""`."""
    p = pergunta(resultado)
    return p["pergunta"] if p else ""


class Fluxo:
    """Um atendimento num thread, com o `invoke` e o `Command({ resume })` de develop."""

    def __init__(self, grafo: GrafoCompilado, prefixo: str = "teste-fluxo", **configurable: Any) -> None:
        self.grafo = grafo
        self.config = novo_config(prefixo, **configurable)

    async def iniciar(self, entrada: dict[str, Any] | None = None) -> dict[str, Any]:
        resultado: dict[str, Any] = await self.grafo.ainvoke(entrada or {}, self.config)
        return resultado

    async def responder(self, *respostas: str) -> dict[str, Any]:
        """Responde em ordem e devolve o resultado da última resposta."""
        resultado: dict[str, Any] = {}
        for resposta in respostas:
            resultado = await self.grafo.ainvoke(Command(resume=resposta), self.config)
        return resultado

    async def estado(self) -> dict[str, Any]:
        return dict((await self.grafo.aget_state(self.config)).values)
