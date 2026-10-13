"""Montagem da aplicação FastAPI, sem subir servidor.

Os testes usam a aplicação direto; quem quer rodar de verdade passa pelo
`main.py`.

Ordem de inicialização (issue #114 e #208, ponto de atenção 1). Em develop, o
schema era garantido por dois mecanismos: o `await` no topo do módulo de cada
grafo (`saver.setup()`) e as chamadas de `montarApp()` antes do `listen()`.
Aqui os dois viram inicializadores do lifespan, executados em sequência. O
uvicorn só abre o socket depois que o lifespan termina, então o `/health` do
ALB não responde enquanto o checkpointer e o schema de negócio não estiverem
prontos. O teste `tests/test_app.py` prova essa sequência.

A fundação entrega só o esqueleto. As stores de negócio (módulo
`persistencia`) entram em `INICIALIZADORES_PADRAO` depois do checkpointer, e as
rotas de negócio chegam no módulo `api`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI

from maria.shared.checkpointer import fechar_checkpointer, inicializar_checkpointer

Inicializador = Callable[[], Awaitable[object]]

# Ordem importa: checkpointer primeiro, depois o schema de negócio.
INICIALIZADORES_PADRAO: tuple[Inicializador, ...] = (inicializar_checkpointer,)


def criar_app(inicializadores: Sequence[Inicializador] = INICIALIZADORES_PADRAO) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        for inicializar in inicializadores:
            await inicializar()
        try:
            yield
        finally:
            await fechar_checkpointer()

    # /docs e /openapi.json chegam com as rotas, no módulo api, conferidos contra
    # o contrato de develop. Até lá, nenhuma rota além do /health.
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    # Health check do target group do ALB. Sem efeito colateral e fora da
    # autenticação: o ALB não manda Bearer token. O contrato exato (content-type,
    # HEAD) é conferido contra as fixtures no módulo api.
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
