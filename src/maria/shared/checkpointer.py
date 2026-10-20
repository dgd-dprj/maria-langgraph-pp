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

from maria.shared.logger import logger
from maria.shared.pool import ConexaoAsync, PoolAsync, criar_pool

SCHEMA_CHECKPOINT = "checkpoint_py"

_checkpointer: BaseCheckpointSaver[str] | None = None
_pool: PoolAsync | None = None
_trava = asyncio.Lock()


async def _fixar_search_path(conexao: ConexaoAsync) -> None:
    await conexao.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(SCHEMA_CHECKPOINT)))


async def _criar_checkpointer() -> BaseCheckpointSaver[str]:
    global _pool
    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.warn("[checkpoint] DATABASE_URL ausente — usando MemorySaver (não persiste)")
        return InMemorySaver()

    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conexao:
        try:
            await conexao.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(SCHEMA_CHECKPOINT)))
        except psycopg.errors.InsufficientPrivilege:
            # #260: é o primeiro erro de um deploy num banco novo, e sem esta
            # linha ele fica no fim de um traceback. Exige CREATE no banco mesmo
            # com o schema já criado. Nunca a URL: ela contém a senha.
            banco, usuario = conexao.info.dbname, conexao.info.user
            logger.error(
                "[checkpoint] sem permissão para criar o schema do checkpoint: o usuário precisa de CREATE no banco",
                schema=SCHEMA_CHECKPOINT,
                banco=banco,
                usuario=usuario,
                permissao="CREATE",
                correcao=f'GRANT CREATE ON DATABASE "{banco}" TO "{usuario}";',
            )
            raise

    # Parâmetros de pool e de conexão iguais aos do pg de develop (shared/pool.py).
    # O autocommit de lá também é exigido pelo setup() (CREATE INDEX CONCURRENTLY).
    pool = criar_pool(url, configure=_fixar_search_path)
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
