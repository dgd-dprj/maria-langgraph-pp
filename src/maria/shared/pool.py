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
| banco fora, conexão recusada | erro na hora, para quem pediu | espera o prazo inteiro (corrigido em PoolComoPg) |
| idade máxima da conexão | nenhuma | 3600 s |
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from psycopg_pool.base import AttemptWithBackoff

ConexaoAsync = psycopg.AsyncConnection[DictRow]


class PoolComoPg(AsyncConnectionPool[ConexaoAsync]):
    """O psycopg_pool com a falha de conexão do pg (decisão 5, fechada em 2026-10-20).

    No pg-pool 3.14 de develop, quem pede conexão com o pool sem conexão livre
    abre uma conexão no próprio contexto (`newClient`), e o erro de conexão volta
    direto para quem pediu, sem nova tentativa. O psycopg_pool abre a conexão em
    segundo plano, tenta de novo por até `reconnect_timeout` e não avisa quem está
    na fila: com o banco fora, cada consulta esperava o prazo inteiro do pool.
    Medido em Linux, com a conexão recusada: o pg erra em 0,00 s, e este pool sem a
    correção, em 120 s.

    A correção mexe só na falha: o erro é entregue na hora a quem está na fila, e a
    tentativa termina ali, sem retentativa em segundo plano. O pool cheio com o
    banco no ar não muda. Usa internos do psycopg_pool 3.3 (`_waiting`, `_lock`,
    `_add_connection`); `tests/shared/test_pool_banco_fora.py` mede o efeito.
    """

    async def _connect(self, timeout: float | None = None) -> ConexaoAsync:  # noqa: ASYNC109 - assinatura da biblioteca
        try:
            return await super()._connect(timeout)
        except Exception as erro:
            async with self._lock:
                fila = list(self._waiting)
                self._waiting.clear()
            for cliente in fila:
                await cliente.fail(erro)
            raise

    async def _add_connection(self, attempt: AttemptWithBackoff | None, growing: bool = False) -> None:
        if attempt is None:
            # Já vencida: na primeira falha, a biblioteca desiste em vez de agendar outra.
            attempt = AttemptWithBackoff(timeout=0.0)
            attempt.give_up_at = monotonic()
        await super()._add_connection(attempt, growing=growing)


PoolAsync = PoolComoPg

MAXIMO_DE_CONEXOES = 10
# idleTimeoutMillis padrão do pg: 10 000 ms.
OCIOSIDADE_MAXIMA_S = 10.0
# ATENÇÃO, parâmetro com o mesmo nome e semântica diferente entre bibliotecas.
# O psycopg_pool usa `timeout` para DOIS casos que o pg trata de forma diferente:
# - pool cheio, banco no ar: o pg espera sem limite (connectionTimeoutMillis = 0);
# - banco fora do ar: o pg abre a conexão no contexto de quem pediu e devolve o
#   erro na hora (pg-pool 3.14, newClient).
# O segundo caso é tratado por PoolComoPg (decisão 5, fechada em 2026-10-20): o
# erro de conexão chega a quem espera sem esperar este prazo. Este prazo ainda
# limita o que nenhum dos dois devolve sozinho, como o pacote descartado, em que
# a conexão TCP fica esperando o sistema (no Linux, o pg errou em 21 s), e o pool
# cheio. 120 s é o ConnectionBorrowTimeout padrão do RDS Proxy. O custo: com o
# pool cheio por mais de 120 s, o psycopg_pool erra onde o pg esperaria, o que
# exige 10 consultas presas ao mesmo tempo no mesmo pool. Não trocar por math.inf:
# com o pacote descartado, a requisição ficaria pendurada sem limite.
ESPERA_POR_CONEXAO_S = 120.0
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
    return PoolComoPg(
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
