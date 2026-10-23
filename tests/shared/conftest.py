"""Fixtures das stores de persistência.

O pytest-asyncio cria um event loop por teste, e um pool memoizado aberto no
loop de um teste quebraria no seguinte. `stores_limpas` fecha as stores antes e
depois de cada teste. Em develop, o Node tem um único loop e os pools nunca são
fechados (ver a spec do módulo persistencia).
"""

import os
from collections.abc import AsyncIterator

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import TupleRow

from maria.shared.atendimentos_db import fechar_atendimentos_store
from maria.shared.embeddings_fluxos import fechar_busca_fluxos
from maria.shared.fluxos_planejados_db import fechar_fluxos_planejados_store
from maria.shared.perguntas_db import fechar_perguntas_store

TABELAS_DE_NEGOCIO = ("atendimentos", "perguntas", "assuntos_verde", "flow_assuntos", "fluxos_planejados", "fluxo_embeddings")


async def _fechar_todas() -> None:
    await fechar_atendimentos_store()
    await fechar_perguntas_store()
    await fechar_fluxos_planejados_store()
    await fechar_busca_fluxos()


@pytest.fixture
async def stores_limpas() -> AsyncIterator[None]:
    await _fechar_todas()
    yield
    await _fechar_todas()


@pytest.fixture
async def banco_de_negocio(stores_limpas: None) -> AsyncIterator[psycopg.AsyncConnection[TupleRow]]:
    """Conexão direta ao Postgres de teste, com as tabelas de negócio apagadas."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("os testes postgres precisam de DATABASE_URL (no CI, o serviço Postgres)")
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conexao:
        for tabela in TABELAS_DE_NEGOCIO:
            await conexao.execute(sql.SQL("DROP TABLE IF EXISTS public.{}").format(sql.Identifier(tabela)))
        yield conexao
