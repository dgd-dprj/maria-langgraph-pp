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

Depois do checkpointer vêm as stores de negócio, na mesma sequência de
`app.ts:40-43` em develop. As rotas de negócio chegam no módulo `api`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI

from maria.integracoes.cliente_http import fechar_cliente_http
from maria.shared.atendimentos_db import fechar_atendimentos_store, obter_atendimentos_store
from maria.shared.checkpointer import fechar_checkpointer, inicializar_checkpointer
from maria.shared.embeddings_fluxos import fechar_busca_fluxos
from maria.shared.fluxos_planejados_db import fechar_fluxos_planejados_store, listar_fluxos_planejados
from maria.shared.perguntas_db import fechar_perguntas_store, obter_perguntas_store

Inicializador = Callable[[], Awaitable[object]]


async def _preparar_esquema_perguntas() -> None:
    # A store de perguntas cria o esquema em segundo plano; uma consulta força a
    # espera, como `listarPerguntasPorFlow("0000…")` em app.ts:41-42.
    store = await obter_perguntas_store()
    await store.listar_perguntas_por_flow("00000000-0000-0000-0000-000000000000")


# Ordem importa: checkpointer primeiro, depois o schema de negócio (app.ts:40-43).
# O fluxo_embeddings fica de fora: é criado no pré-aquecimento, sem bloquear o boot.
INICIALIZADORES_PADRAO: tuple[Inicializador, ...] = (
    inicializar_checkpointer,
    obter_atendimentos_store,
    _preparar_esquema_perguntas,
    listar_fluxos_planejados,
)

# Develop nunca fechava os pools (o Node tem um único event loop). Aqui eles são
# fechados no fim do lifespan: o pytest-asyncio cria um loop por teste.
FINALIZADORES: tuple[Inicializador, ...] = (
    fechar_checkpointer,
    fechar_atendimentos_store,
    fechar_perguntas_store,
    fechar_fluxos_planejados_store,
    fechar_busca_fluxos,
    fechar_cliente_http,
)


def criar_app(inicializadores: Sequence[Inicializador] = INICIALIZADORES_PADRAO) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        for inicializar in inicializadores:
            await inicializar()
        try:
            yield
        finally:
            for finalizar in FINALIZADORES:
                await finalizar()

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
