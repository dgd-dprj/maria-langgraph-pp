"""Trava por chave entre processos (#453).

Duas chamadas iguais ao mesmo tempo (um reenvio da Tykhe, dois toques no botão, a Meta repetindo o webhook) não
podem rodar o mesmo trecho em paralelo. Em deploy, duas ou três tarefas do ECS atendem ao mesmo tempo (medido nos
logs em 2026-11-18), então uma trava em memória não protege: a segunda chamada pode cair em outro processo.

Com `DATABASE_URL`, a trava é um `pg_advisory_xact_lock` sobre a chave, numa transação aberta só para isso. Ela é
liberada sozinha quando a transação termina, inclusive com erro ou com a conexão caindo. A espera tem limite
(`lock_timeout`): quem não consegue a trava dentro do prazo recebe `False` e decide o que devolver, sem rodar o
trecho de novo. Sem `DATABASE_URL` (testes em memória), vale um `asyncio.Lock` por chave, com o mesmo limite.

Uso:

    async with trava(f"atendimento:{chat_id}") as obtida:
        if not obtida:
            ...  # devolve o estado atual, sem rodar o fluxo
        ...
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator

import psycopg

from maria.shared.pool import PoolAsync, criar_pool

# A espera da segunda chamada cabe no orçamento de 25 s por resposta (#477): até 20 s esperando a primeira, e o resto
# para ler o estado e responder antes de o CloudFront cortar aos 30 s.
ESPERA_MAXIMA_S = 20.0
# Semente do hash da chave: separa estas travas de qualquer outro advisory lock que use a mesma chave.
SEMENTE_DO_HASH = 453

_pool: PoolAsync | None = None
_travas_em_memoria: dict[str, asyncio.Lock] = {}


async def _obter_pool() -> PoolAsync | None:
    global _pool
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    if _pool is None:
        _pool = criar_pool(url)
        await _pool.open()
    return _pool


@contextlib.asynccontextmanager
async def trava(chave: str, espera_maxima_s: float | None = None) -> AsyncIterator[bool]:
    """Segura a trava da `chave` durante o bloco. Entrega `True` se conseguiu, ou `False` se a espera estourou.

    Sem `espera_maxima_s`, vale `ESPERA_MAXIMA_S`, lida na hora da chamada."""
    if espera_maxima_s is None:
        espera_maxima_s = ESPERA_MAXIMA_S
    pool = await _obter_pool()
    if pool is None:
        async with _trava_em_memoria(chave, espera_maxima_s) as obtida:
            yield obtida
        return

    async with pool.connection() as conexao:
        obtida = False
        try:
            async with conexao.transaction():
                if espera_maxima_s <= 0:
                    # `lock_timeout = 0` quer dizer "sem limite" no Postgres: sem espera, é a tentativa única.
                    linha = await (
                        await conexao.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, %s))", (chave, SEMENTE_DO_HASH))
                    ).fetchone()
                    if not (linha and next(iter(linha.values()))):
                        raise psycopg.errors.LockNotAvailable("trava ocupada (sem espera)")
                else:
                    prazo_ms = max(1, round(espera_maxima_s * 1000))
                    # `set_config(..., true)` vale só nesta transação, como um SET LOCAL.
                    await conexao.execute("SELECT set_config('lock_timeout', %s, true)", (f"{prazo_ms}ms",))
                    await conexao.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))", (chave, SEMENTE_DO_HASH))
                obtida = True
                yield True
        except psycopg.errors.LockNotAvailable:
            if obtida:
                raise
        if not obtida:
            yield False


@contextlib.asynccontextmanager
async def _trava_em_memoria(chave: str, espera_maxima_s: float) -> AsyncIterator[bool]:
    trava_local = _travas_em_memoria.setdefault(chave, asyncio.Lock())
    try:
        await asyncio.wait_for(trava_local.acquire(), timeout=max(espera_maxima_s, 0.0))
    except TimeoutError:
        yield False
        return
    try:
        yield True
    finally:
        trava_local.release()


async def fechar_travas() -> None:
    """Fecha o pool das travas e esquece as travas em memória (fim do lifespan e testes)."""
    global _pool
    if _pool is not None:
        await _pool.close()
    _pool = None
    _travas_em_memoria.clear()
