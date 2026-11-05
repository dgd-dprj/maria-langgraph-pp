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
`app.ts:40-43` em develop. As rotas de negócio passam pelo `PipelineFastify`
(`maria/api/pipeline.py`), que reproduz o contrato HTTP do Fastify.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI

from maria.api import atendimentos, basicas, orquestrador, webhook_whatsapp
from maria.api.docs import registrar_docs
from maria.api.pipeline import PipelineFastify
from maria.fluxos import ambiente, catalogo_para_classificacao, fluxos_ligados, fluxos_por_id
from maria.integracoes.cliente_http import fechar_cliente_http
from maria.shared.atendimentos_db import fechar_atendimentos_store, obter_atendimentos_store
from maria.shared.checkpointer import fechar_checkpointer, inicializar_checkpointer
from maria.shared.embeddings_fluxos import aquecer_catalogo, fechar_busca_fluxos
from maria.shared.fluxos_planejados_db import fechar_fluxos_planejados_store, listar_fluxos_planejados
from maria.shared.logger import logger
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


async def _pre_aquecer_catalogo() -> None:
    """Issue #180 (`server.ts:16-18`): indexa o catálogo de embeddings logo depois de
    subir, sem esperar a 1ª requisição do orquestrador e sem atrasar o /health."""
    try:
        await aquecer_catalogo(await catalogo_para_classificacao())
    except Exception as erro:
        # Fire-and-forget, como o .catch de server.ts: a falha só é registrada.
        logger.error("[embeddingsFluxos] falha ao pré-aquecer catálogo no boot", err=erro)


def _registrar_fluxos_ligados() -> None:
    """#324: o ambiente e os fluxos ligados ficam visíveis a cada subida."""
    ligados = fluxos_ligados()
    logger.info(
        "[fluxos] ambiente e fluxos ligados",
        evento="fluxos_ligados",
        # O logger omite None: sem a variável, a linha diz "(ausente)", e não fica sem a chave.
        ambiente=ambiente() if ambiente() is not None else "(ausente)",
        fluxosLigados=[cfg.nome for cfg in ligados.values()],
        fluxosEmTesteDesligados=[cfg.nome for id_, cfg in fluxos_por_id.items() if id_ not in ligados],
    )


def criar_app(inicializadores: Sequence[Inicializador] = INICIALIZADORES_PADRAO, pre_aquecer: bool = True) -> FastAPI:
    # Sem default silencioso: erra alto na subida, nunca sobe a API "aberta" (app.ts:86-87).
    chave_api = os.environ.get("API_KEY")
    if not chave_api:
        raise RuntimeError("API_KEY obrigatório (.env local ou secret em produção)")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        for inicializar in inicializadores:
            await inicializar()
        _registrar_fluxos_ligados()
        aquecimento = asyncio.create_task(_pre_aquecer_catalogo()) if pre_aquecer else None
        try:
            yield
        finally:
            if aquecimento is not None:
                aquecimento.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await aquecimento
            for finalizar in FINALIZADORES:
                await finalizar()

    # O roteamento, a autenticação, os erros e a serialização das rotas de negócio
    # (e do /health) ficam no PipelineFastify, com o contrato do Fastify de develop.
    # O FastAPI fica com o lifespan e o /docs (spec 07, D-3).
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    rotas = [*basicas.ROTAS, *atendimentos.ROTAS, *orquestrador.ROTAS, *webhook_whatsapp.ROTAS]
    registrar_docs(app, rotas)
    app.add_middleware(PipelineFastify, rotas=rotas, chave_api=chave_api)
    return app
