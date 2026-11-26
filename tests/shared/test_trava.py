"""#453: a trava por chave (`maria.shared.trava`), em memória e no Postgres."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator

import psycopg
import pytest

from maria.shared import trava as trava_mod
from maria.shared.trava import SEMENTE_DO_HASH, fechar_travas, trava


@pytest.fixture(autouse=True)
async def travas_limpas() -> AsyncIterator[None]:
    await fechar_travas()
    yield
    await fechar_travas()


async def _usar(chave: str, espera: float, segurar: float, registro: list[tuple[str, object]], nome: str) -> bool:
    async with trava(chave, espera) as obtida:
        registro.append((nome, obtida))
        if obtida:
            await asyncio.sleep(segurar)
            registro.append((nome, "saiu"))
        return obtida


# --- Em memória (sem DATABASE_URL) ----------------------------------------------------------------------------------------


@pytest.fixture
def sem_banco(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


async def test_memoria_a_segunda_espera_a_primeira_terminar(sem_banco: None) -> None:
    registro: list[tuple[str, object]] = []
    await asyncio.gather(_usar("chave", 2.0, 0.2, registro, "1"), _usar("chave", 2.0, 0.0, registro, "2"))
    assert registro == [("1", True), ("1", "saiu"), ("2", True), ("2", "saiu")]


async def test_memoria_espera_estourada_entrega_false(sem_banco: None) -> None:
    registro: list[tuple[str, object]] = []
    primeira, segunda = await asyncio.gather(_usar("chave", 2.0, 0.5, registro, "1"), _usar("chave", 0.05, 0.0, registro, "2"))
    assert (primeira, segunda) == (True, False)


async def test_memoria_chaves_diferentes_nao_se_esperam(sem_banco: None) -> None:
    registro: list[tuple[str, object]] = []
    await asyncio.gather(_usar("chave-a", 0.05, 0.3, registro, "a"), _usar("chave-b", 0.05, 0.0, registro, "b"))
    assert ("a", True) in registro and ("b", True) in registro


async def test_memoria_liberada_mesmo_com_erro(sem_banco: None) -> None:
    with pytest.raises(RuntimeError):
        async with trava("chave", 0.1):
            raise RuntimeError("falha no meio")
    async with trava("chave", 0.1) as obtida:
        assert obtida is True


# --- Postgres de verdade: a trava vale entre conexões, como entre tarefas do ECS -----------------------------------------


def _url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("os testes postgres precisam de DATABASE_URL (no CI, o serviço Postgres)")
    return url


async def _livre_vista_de_fora(chave: str) -> bool:
    """Outra conexão, fora do pool da trava (como outra tarefa do ECS), tenta pegar a mesma trava sem esperar."""
    async with await psycopg.AsyncConnection.connect(_url()) as conexao, conexao.transaction():
        linha = await (
            await conexao.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, %s))", (chave, SEMENTE_DO_HASH))
        ).fetchone()
        return bool(linha and linha[0])


@pytest.mark.postgres
async def test_postgres_a_trava_e_vista_por_outra_conexao() -> None:
    _url()
    async with trava("chave-pg", 1.0) as obtida:
        assert obtida is True
        assert await _livre_vista_de_fora("chave-pg") is False
        assert await _livre_vista_de_fora("outra-chave") is True
    assert await _livre_vista_de_fora("chave-pg") is True  # liberada no fim da transação


@pytest.mark.postgres
async def test_postgres_a_segunda_conexao_espera_e_entra_depois() -> None:
    _url()
    registro: list[tuple[str, object]] = []
    await asyncio.gather(_usar("chave-pg", 5.0, 0.3, registro, "1"), _usar("chave-pg", 5.0, 0.0, registro, "2"))
    assert registro == [("1", True), ("1", "saiu"), ("2", True), ("2", "saiu")]


@pytest.mark.postgres
async def test_postgres_espera_estourada_entrega_false_dentro_do_prazo() -> None:
    _url()
    registro: list[tuple[str, object]] = []
    inicio = time.monotonic()

    async def segunda() -> bool:
        await asyncio.sleep(0.05)  # a primeira pega a trava antes
        return await _usar("chave-pg", 0.2, 0.0, registro, "2")

    primeira, obtida = await asyncio.gather(_usar("chave-pg", 5.0, 1.0, registro, "1"), segunda())
    assert (primeira, obtida) == (True, False)
    assert ("2", False) in registro
    # A segunda desistiu perto dos 0,2 s, e não depois de a primeira soltar (1 s).
    assert registro.index(("2", False)) < registro.index(("1", "saiu"))
    assert time.monotonic() - inicio < 2.0


@pytest.mark.postgres
async def test_postgres_liberada_mesmo_com_erro() -> None:
    _url()
    with pytest.raises(RuntimeError):
        async with trava("chave-pg", 1.0):
            raise RuntimeError("falha no meio")
    assert await _livre_vista_de_fora("chave-pg") is True


@pytest.mark.postgres
async def test_postgres_o_limite_de_espera_nao_fica_na_conexao_que_volta_ao_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    # `set_config(..., true)` vale só na transação da trava. Se valesse na sessão, os 20 s ficariam na conexão quando ela
    # volta ao pool e passariam a valer para consultas que não têm nada a ver com a trava.
    _url()
    async with trava("chave-pg", 3.0) as obtida:
        assert obtida is True
    pool = trava_mod._pool
    assert pool is not None
    async with pool.connection() as conexao:
        linha = await (await conexao.execute("SHOW lock_timeout")).fetchone()
        assert linha is not None and next(iter(linha.values())) == "0"


@pytest.mark.postgres
async def test_postgres_pool_lotado_entrega_false_dentro_do_prazo() -> None:
    # Com as 10 conexões do pool ocupadas por outras chaves, a 11ª chamada não espera os 120 s do pool: desiste no
    # prazo da trava (com o mínimo de 1 s para a conexão) e segue o caminho da espera estourada.
    _url()
    from maria.shared.pool import MAXIMO_DE_CONEXOES

    ocupadas = asyncio.Event()
    soltar = asyncio.Event()
    contagem = 0

    async def ocupar(i: int) -> None:
        nonlocal contagem
        async with trava(f"ocupa-{i}", 5.0) as obtida:
            assert obtida is True
            contagem += 1
            if contagem == MAXIMO_DE_CONEXOES:
                ocupadas.set()
            await soltar.wait()

    tarefas = [asyncio.create_task(ocupar(i)) for i in range(MAXIMO_DE_CONEXOES)]
    await asyncio.wait_for(ocupadas.wait(), timeout=10)
    inicio = time.monotonic()
    async with trava("outra-chave", 0.2) as obtida:
        assert obtida is False
    assert time.monotonic() - inicio < 3.0
    soltar.set()
    await asyncio.gather(*tarefas)


@pytest.mark.postgres
async def test_postgres_sem_espera_e_uma_tentativa_so() -> None:
    _url()
    async with trava("chave-pg", 1.0):
        async with trava("chave-pg", 0) as obtida:
            assert obtida is False
    async with trava("chave-pg", 0) as obtida:
        assert obtida is True
