"""Parâmetros dos pools Postgres (`shared/pool.py`).

Sem banco: o pool é criado fechado (`open=False`) e os parâmetros são lidos
do próprio objeto do psycopg_pool. Os valores reproduzem o `pg` (pg-pool 3.14)
de develop, e não os padrões do psycopg_pool.
"""

import math

from psycopg.rows import dict_row

from maria.shared.pool import criar_pool

URL = "postgresql://usuario@host-falso:5432/banco"


def test_parametros_reproduzem_o_pg_de_develop() -> None:
    pool = criar_pool(URL)
    assert pool.min_size == 0  # pg: nenhuma conexão até a primeira consulta
    assert pool.max_size == 10  # pg: max 10
    assert pool.max_idle == 10.0  # pg: idleTimeoutMillis 10 000
    assert pool.timeout == math.inf  # pg: connectionTimeoutMillis 0 = espera sem limite
    assert pool.max_lifetime == math.inf  # pg: sem idade máxima


def test_nenhum_parametro_ficou_no_padrao_do_psycopg_pool() -> None:
    # Padrões do psycopg_pool: min_size 4, max_idle 600, timeout 30, max_lifetime 3600.
    pool = criar_pool(URL)
    assert (pool.min_size, pool.max_idle, pool.timeout, pool.max_lifetime) != (4, 600.0, 30.0, 3600.0)
    assert pool.min_size != 4
    assert pool.max_idle != 600.0
    assert pool.timeout != 30.0
    assert pool.max_lifetime != 3600.0


def test_pool_nasce_fechado() -> None:
    assert criar_pool(URL).closed


def test_kwargs_de_conexao_e_row_factory() -> None:
    pool = criar_pool(URL, autocommit=True, prepare_threshold=0)
    assert pool.kwargs == {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
