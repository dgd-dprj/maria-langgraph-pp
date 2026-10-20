"""Pool com o banco fora do ar: quanto tempo quem pede conexão espera (decisão em aberto 5 do MIGRACAO.md).

DEFEITO CONHECIDO, reproduzido aqui de propósito para virar teste de regressão da correção.
Com o banco fora, o psycopg_pool tenta conectar em segundo plano e não avisa quem espera:
a consulta só falha quando o prazo do pool (`ESPERA_POR_CONEXAO_S`, 120 s no código) acaba.
O `pg-pool` de develop entrega o erro de conexão direto a quem pediu (`index.js:283`, lido).

Hoje os testes provam que a espera dura o prazo inteiro. Quando a correção entrar, eles
devem passar a provar que a consulta erra antes do prazo: inverter a asserção marcada.

O prazo é reduzido para PRAZO_S só no teste, para o CI não esperar 120 s. Não precisa de
Postgres: os dois destinos não respondem como banco.
"""

import time

import pytest
from psycopg_pool import PoolTimeout

from maria.shared import pool as modulo_pool

PRAZO_S = 2.0

DESTINOS = {
    # Porta fechada: o sistema recusa a conexão (RST). No Linux, a recusa chega na hora.
    "conexão recusada": "postgresql://ninguem@127.0.0.1:1/nada",
    # Endereço que não responde (RFC 5737, reservado para documentação): o pacote é descartado
    # e a conexão TCP fica esperando o prazo do sistema.
    "pacote descartado": "postgresql://ninguem@192.0.2.1:5432/nada",
}


@pytest.mark.parametrize("caso", list(DESTINOS))
async def test_banco_fora_espera_o_prazo_inteiro_do_pool(monkeypatch: pytest.MonkeyPatch, caso: str) -> None:
    monkeypatch.setattr(modulo_pool, "ESPERA_POR_CONEXAO_S", PRAZO_S)
    pool = modulo_pool.criar_pool(DESTINOS[caso])
    await pool.open()
    inicio = time.monotonic()
    try:
        with pytest.raises(PoolTimeout):
            async with pool.connection() as conexao:
                await conexao.execute("SELECT 1")
        espera = time.monotonic() - inicio
    finally:
        await pool.close(timeout=1)
    # DEFEITO CONHECIDO (decisão 5): a espera é o prazo inteiro, nos dois casos.
    # Depois da correção, no caso "conexão recusada", inverter para `espera < PRAZO_S`.
    assert espera >= PRAZO_S * 0.95, f"{caso}: errou em {espera:.2f} s, antes do prazo de {PRAZO_S} s"
    assert espera < PRAZO_S + 3, f"{caso}: esperou {espera:.2f} s, muito além do prazo de {PRAZO_S} s"
