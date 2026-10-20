"""Pool com o banco fora do ar: quanto tempo quem pede conexão espera (decisão 5, fechada em 2026-10-20).

Medido em Linux (2026-10-20), com duas consultas seguidas por caso:

| Banco fora do ar | pg de develop (8.23.0) | psycopg_pool sem a correção |
|---|---|---|
| conexão recusada | erro em 0,00 s | PoolTimeout em 120 s |
| pacote descartado | erro em 21 s (prazo do TCP) | PoolTimeout em 120 s |

A correção (`PoolComoPg`, em `shared/pool.py`) entrega o erro de conexão a quem
espera, como o pg. Estes testes medem o efeito, o tempo até o erro, e não o
parâmetro passado à biblioteca.

O prazo é reduzido para PRAZO_S só no teste, para o CI não esperar 120 s. Não precisa de
Postgres: os dois destinos não respondem como banco.
"""

import sys
import time

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from maria.shared import pool as modulo_pool

PRAZO_S = 5.0

# Porta fechada: o sistema recusa a conexão (RST). No Linux, a recusa chega na hora.
RECUSADA = "postgresql://ninguem@127.0.0.1:1/nada"
# Endereço que não responde (RFC 5737, reservado para documentação): o pacote é descartado
# e a conexão TCP fica esperando o prazo do sistema.
DESCARTADA = "postgresql://ninguem@192.0.2.1:5432/nada"


async def _tempo_ate_o_erro(url: str, consultas: int = 2) -> list[tuple[type[BaseException], float]]:
    pool = modulo_pool.criar_pool(url)
    await pool.open()
    resultados: list[tuple[type[BaseException], float]] = []
    try:
        for _ in range(consultas):
            inicio = time.monotonic()
            with pytest.raises(Exception) as erro:
                async with pool.connection() as conexao:
                    await conexao.execute("SELECT 1")
            resultados.append((erro.type, time.monotonic() - inicio))
    finally:
        await pool.close(timeout=1)
    return resultados


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows, o libpq não percebe a conexão recusada e espera sem limite")
async def test_conexao_recusada_devolve_o_erro_na_hora_como_o_pg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modulo_pool, "ESPERA_POR_CONEXAO_S", PRAZO_S)
    for tipo, espera in await _tempo_ate_o_erro(RECUSADA):
        # O erro é o da conexão, e não o PoolTimeout do fim do prazo. PoolTimeout é
        # subclasse de OperationalError: só o primeiro teste não distinguiria os dois.
        assert issubclass(tipo, psycopg.OperationalError), f"erro {tipo.__name__} em {espera:.2f} s"
        assert not issubclass(tipo, PoolTimeout), f"erro {tipo.__name__} em {espera:.2f} s: é o fim do prazo, e não o erro da conexão"
        assert espera < 1.0, f"a conexão recusada levou {espera:.2f} s para virar erro (o pg erra em 0,00 s)"


async def test_pacote_descartado_ainda_respeita_o_prazo_do_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    # A conexão TCP não termina antes do prazo: nem o pg nem o pool recebem erro do sistema.
    # Aqui o prazo do pool é o limite, e a requisição não fica pendurada sem fim.
    monkeypatch.setattr(modulo_pool, "ESPERA_POR_CONEXAO_S", PRAZO_S)
    [(tipo, espera)] = await _tempo_ate_o_erro(DESCARTADA, consultas=1)
    assert issubclass(tipo, PoolTimeout), f"erro {tipo.__name__} em {espera:.2f} s"
    assert PRAZO_S * 0.95 <= espera < PRAZO_S + 3, f"esperou {espera:.2f} s, com prazo de {PRAZO_S} s"
