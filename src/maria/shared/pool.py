"""Construção dos pools Postgres: um único lugar para os parâmetros.

Todos os pools do serviço (checkpointer e, a partir do módulo persistencia,
as quatro stores) são criados aqui, para que o comportamento de conexão não
divirja entre eles. Consolidar os pools num só é outra coisa, registrada no
MIGRACAO.md como melhoria fora do escopo.

Os parâmetros reproduzem o `new Pool(...)` do `pg` (pg-pool 3.14) de develop,
e não os padrões do psycopg_pool. Os dois contrastam em tudo que importa
contra o RDS Proxy compartilhado com o stack antigo:

| | pg (develop) | psycopg_pool (padrão) |
|---|---|---|
| conexões abertas ao iniciar | nenhuma | 4 |
| máximo de conexões | 10 | min_size |
| conexão ociosa fecha em | 10 s | 600 s |
| espera por conexão com o pool cheio | sem limite | 30 s, depois PoolTimeout |
| idade máxima da conexão | nenhuma | 3600 s |
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

ConexaoAsync = psycopg.AsyncConnection[DictRow]
PoolAsync = AsyncConnectionPool[ConexaoAsync]

MAXIMO_DE_CONEXOES = 10
# idleTimeoutMillis padrão do pg: 10 000 ms.
OCIOSIDADE_MAXIMA_S = 10.0
# connectionTimeoutMillis padrão do pg é 0, que significa esperar SEM LIMITE por
# uma conexão quando o pool está cheio. É intencional: o padrão de 30 s do
# psycopg_pool transformaria em erro (PoolTimeout) o que em develop é espera, e
# sob carga isso apareceria como falha inexplicável no atendimento. Não trocar
# por um número finito sem decisão registrada na #208.
ESPERA_POR_CONEXAO_S = math.inf
# O pg não recicla conexões por idade; o psycopg_pool recicla a cada 3600 s.
IDADE_MAXIMA_S = math.inf


# Parâmetros de cada conexão, fixos para todos os pools, também reproduzindo o pg:
# - autocommit: no pg, cada `pool.query` roda como transação própria. Sem isso, o
#   psycopg abriria uma transação implícita por conexão.
# - prepare_threshold=None: DESLIGA prepared statements. O pg só usa statements
#   sem nome. ATENÇÃO: 0 faz o contrário (prepara toda consulta já na primeira
#   execução), e prepared statements fazem o RDS Proxy fixar a sessão (pinning),
#   perdendo a multiplexação no proxy compartilhado com o stack antigo.
PARAMETROS_DE_CONEXAO: dict[str, Any] = {"autocommit": True, "prepare_threshold": None, "row_factory": dict_row}


def criar_pool(url: str, *, configure: Callable[[ConexaoAsync], Awaitable[None]] | None = None) -> PoolAsync:
    """Pool fechado (`open=False`); quem cria abre com `await pool.open()`.

    `min_size=0` reproduz a abertura preguiçosa do pg: nenhuma conexão até a
    primeira consulta. Toda conexão nova recebe PARAMETROS_DE_CONEXAO e, se
    houver, passa pelo `configure` (por exemplo, o search_path do checkpointer).
    """
    return AsyncConnectionPool(
        url,
        min_size=0,
        max_size=MAXIMO_DE_CONEXOES,
        max_idle=OCIOSIDADE_MAXIMA_S,
        timeout=ESPERA_POR_CONEXAO_S,
        max_lifetime=IDADE_MAXIMA_S,
        open=False,
        configure=configure,
        kwargs=dict(PARAMETROS_DE_CONEXAO),
    )
