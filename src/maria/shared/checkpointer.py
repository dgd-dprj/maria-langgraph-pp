"""Checkpointer compartilhado por todos os grafos.

Sem `DATABASE_URL` (por exemplo, na suíte de testes, que não carrega `.env`),
usa `InMemorySaver`: o checkpoint vive em memória e morre com o processo, mas
os testes ficam rápidos e isolados. Com `DATABASE_URL`, persiste no Postgres.

Schema próprio (plano de corte da #208, item 1). O `setup()` do
langgraph-checkpoint-postgres cria tabelas sem qualificar o schema, com os
mesmos nomes das tabelas criadas pela biblioteca JS em `public`
(`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
`checkpoint_migrations`), e as duas serializações são incompatíveis. Por isso
toda conexão do pool fixa `search_path` só em `SCHEMA_CHECKPOINT`: o `setup()`
e as consultas do Python nunca enxergam as tabelas do JS.

Ordem de inicialização (#208, ponto 1, e issue #114). `inicializar_checkpointer()`
roda no lifespan da aplicação, antes de o servidor aceitar conexões, nunca na
primeira requisição. As fábricas de grafo chamam `obter_checkpointer()`, que
só devolve o que o lifespan já preparou.
"""

from __future__ import annotations

import asyncio
import os

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from maria.shared.logger import logger

SCHEMA_CHECKPOINT = "checkpoint_py"

_checkpointer: BaseCheckpointSaver[str] | None = None
_pool: AsyncConnectionPool[psycopg.AsyncConnection[DictRow]] | None = None
_trava = asyncio.Lock()


async def _fixar_search_path(conexao: psycopg.AsyncConnection[DictRow]) -> None:
    await conexao.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(SCHEMA_CHECKPOINT)))


async def _criar_checkpointer() -> BaseCheckpointSaver[str]:
    global _pool
    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.warn("[checkpoint] DATABASE_URL ausente — usando MemorySaver (não persiste)")
        return InMemorySaver()

    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conexao:
        await conexao.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(SCHEMA_CHECKPOINT)))

    # min_size=0 reproduz a abertura preguiçosa do pg.Pool de develop (decisão da
    # spec de persistência, para não abrir conexões ociosas no RDS Proxy compartilhado).
    # autocommit é exigido pelo setup() (CREATE INDEX CONCURRENTLY); prepare_threshold=0
    # evita prepared statements, que o RDS Proxy não multiplexa.
    pool: AsyncConnectionPool[psycopg.AsyncConnection[DictRow]] = AsyncConnectionPool(
        url,
        min_size=0,
        max_size=10,
        open=False,
        configure=_fixar_search_path,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    _pool = pool
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    logger.info("[checkpoint] PostgresSaver conectado")
    return saver


async def inicializar_checkpointer() -> BaseCheckpointSaver[str]:
    """Cria o checkpointer e as tabelas de checkpoint. Memoizado por processo:
    todos os grafos compartilham a mesma instância e o mesmo pool."""
    global _checkpointer
    async with _trava:
        if _checkpointer is None:
            _checkpointer = await _criar_checkpointer()
        return _checkpointer


def obter_checkpointer() -> BaseCheckpointSaver[str]:
    """O checkpointer já inicializado no lifespan. Lança se for chamado antes,
    porque isso significaria criar tabela fora da inicialização."""
    if _checkpointer is None:
        raise RuntimeError("checkpointer não inicializado: inicializar_checkpointer() roda no lifespan, antes de qualquer grafo")
    return _checkpointer


async def fechar_checkpointer() -> None:
    global _checkpointer, _pool
    if _pool is not None:
        await _pool.close()
    _pool = None
    _checkpointer = None
