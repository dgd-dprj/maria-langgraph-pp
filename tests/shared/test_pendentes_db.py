"""Store dos assuntos pendentes por assistido (#450): guardar, listar os ativos (apagando os vencidos), marcar a
situação e prorrogar uma vez. A data de agora é simulada (`pendentes_db.agora`).

Os mesmos casos rodam na memória e, no CI (`-m postgres`), no Postgres real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.rows import TupleRow

from maria.shared import pendentes_db
from maria.shared.pendentes_db import PRAZO, PendentesStore, obter_pendentes_store

pytestmark = pytest.mark.usefixtures("stores_limpas")

ID_PRESA = "3df874f2-675a-4c43-9ec7-480f7c702f50"
PENDENTES: list[dict[str, Any]] = [
    {"nome": "a pessoa presa", "urgente": False, "flowId": ID_PRESA, "dadosConhecidos": {"cpf": "11111111111", "parentesco": "Irmão(a)"}},
    {"nome": "o caso novo", "urgente": True, "tipoCaso": "novo-processo"},
]
INICIO = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


class Relogio:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.agora = INICIO
        monkeypatch.setattr(pendentes_db, "agora", lambda: self.agora)

    def avancar(self, dias: float) -> None:
        self.agora += timedelta(days=dias)


@pytest.fixture
def relogio(monkeypatch: pytest.MonkeyPatch) -> Relogio:
    return Relogio(monkeypatch)


@pytest.fixture
def sem_banco(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


async def _guardar_e_listar(store: PendentesStore, relogio: Relogio) -> None:
    await store.guardar("999999", "chat-a", PENDENTES)
    # Idempotente: guardar de novo, mesmo depois, não duplica nem muda a data.
    relogio.avancar(1)
    await store.guardar("999999", "chat-a", PENDENTES)
    ativos = await store.listar_ativos("999999")
    assert [(p["chatIdOrigem"], p["posicao"], p["nome"]) for p in ativos] == [("chat-a", 2, "a pessoa presa"), ("chat-a", 3, "o caso novo")]
    presa, novo = ativos
    assert presa == {
        "chatIdOrigem": "chat-a",
        "posicao": 2,
        "nome": "a pessoa presa",
        "urgente": False,
        "situacao": "pendente",
        "criadoEm": INICIO,
        "venceEm": INICIO + PRAZO,
        "prorrogado": False,
        "flowId": ID_PRESA,
    }
    # Nunca o relato nem os dadosConhecidos (o CPF do item fica de fora).
    assert novo["tipoCaso"] == "novo-processo" and "flowId" not in novo and novo["urgente"] is True
    assert await store.listar_ativos("outra-pessoa") == []


async def _marcar(store: PendentesStore) -> None:
    await store.guardar("999999", "chat-a", PENDENTES)
    assert await store.marcar("chat-a", 2, "em_andamento") is True
    assert [p["posicao"] for p in await store.listar_ativos("999999")] == [3]
    assert await store.marcar("chat-a", 3, "resolvido") is True
    assert await store.listar_ativos("999999") == []
    item = await store.buscar("chat-a", 2)
    assert item is not None and item["situacao"] == "em_andamento"
    # Sem linha (pessoa não identificada): nada acontece.
    assert await store.marcar("chat-sem-linha", 2, "resolvido") is False
    assert await store.buscar("chat-sem-linha", 2) is None
    with pytest.raises(ValueError, match="situação desconhecida"):
        await store.marcar("chat-a", 2, "excluido")  # type: ignore[arg-type]


async def _vencido_apagado(store: PendentesStore, relogio: Relogio) -> None:
    await store.guardar("999999", "chat-a", PENDENTES[:1])
    await store.guardar("888888", "chat-b", PENDENTES[:1])
    relogio.avancar(10)
    await store.guardar("999999", "chat-c", PENDENTES[1:])
    relogio.avancar(20)  # 30 dias depois do chat-a: venceu
    assert [p["chatIdOrigem"] for p in await store.listar_ativos("999999")] == ["chat-c"]
    # Apagado de verdade, e não só fora da lista.
    assert await store.buscar("chat-a", 2) is None
    # A limpeza é só da pessoa consultada: o vencido da outra pessoa fica até a consulta dela.
    assert await store.buscar("chat-b", 2) is not None
    assert await store.listar_ativos("888888") == []
    assert await store.buscar("chat-b", 2) is None
    # Resolvido também sai quando vence.
    await store.marcar("chat-c", 3, "resolvido")
    relogio.avancar(30)
    await store.listar_ativos("999999")
    assert await store.buscar("chat-c", 3) is None


async def _prorrogar_uma_vez(store: PendentesStore, relogio: Relogio) -> None:
    await store.guardar("999999", "chat-a", PENDENTES)
    relogio.avancar(25)
    assert await store.prorrogar("chat-a", 2) is True
    item = await store.buscar("chat-a", 2)
    assert item is not None
    assert (item["prorrogado"], item["venceEm"]) == (True, INICIO + timedelta(days=25) + PRAZO)
    # Uma prorrogação por assunto: a segunda não muda o prazo.
    relogio.avancar(10)
    assert await store.prorrogar("chat-a", 2) is False
    item = await store.buscar("chat-a", 2)
    assert item is not None and item["venceEm"] == INICIO + timedelta(days=55)
    # Cada assunto tem a sua prorrogação; sem linha, nada.
    assert await store.prorrogar("chat-a", 3) is True
    assert await store.prorrogar("chat-sem-linha", 2) is False
    # Dia 56: o prorrogado (vence no dia 55) sai; o outro (prorrogado no dia 35, vence no 65) fica.
    relogio.avancar(21)
    assert [p["posicao"] for p in await store.listar_ativos("999999")] == [3]
    relogio.avancar(10)
    assert await store.listar_ativos("999999") == []


# --- Em memória ----------------------------------------------------------------


@pytest.mark.usefixtures("sem_banco")
async def test_memoria_guardar_e_listar(relogio: Relogio) -> None:
    await _guardar_e_listar(await obter_pendentes_store(), relogio)


@pytest.mark.usefixtures("sem_banco")
async def test_memoria_marcar_a_situacao(relogio: Relogio) -> None:
    await _marcar(await obter_pendentes_store())


@pytest.mark.usefixtures("sem_banco")
async def test_memoria_vencido_e_apagado_na_consulta(relogio: Relogio) -> None:
    await _vencido_apagado(await obter_pendentes_store(), relogio)


@pytest.mark.usefixtures("sem_banco")
async def test_memoria_prorrogacao_so_uma_vez(relogio: Relogio) -> None:
    await _prorrogar_uma_vez(await obter_pendentes_store(), relogio)


@pytest.mark.usefixtures("sem_banco")
async def test_memoria_ainda_no_prazo_aparece(relogio: Relogio) -> None:
    store = await obter_pendentes_store()
    await store.guardar("999999", "chat-a", PENDENTES[:1])
    relogio.avancar(29.9)
    assert len(await store.listar_ativos("999999")) == 1


# --- Postgres real ------------------------------------------------------------


@pytest.mark.postgres
async def test_postgres_guardar_e_listar(banco_de_negocio: psycopg.AsyncConnection[TupleRow], relogio: Relogio) -> None:
    await _guardar_e_listar(await obter_pendentes_store(), relogio)


@pytest.mark.postgres
async def test_postgres_marcar_a_situacao(banco_de_negocio: psycopg.AsyncConnection[TupleRow], relogio: Relogio) -> None:
    await _marcar(await obter_pendentes_store())


@pytest.mark.postgres
async def test_postgres_vencido_e_apagado_na_consulta(banco_de_negocio: psycopg.AsyncConnection[TupleRow], relogio: Relogio) -> None:
    await _vencido_apagado(await obter_pendentes_store(), relogio)


@pytest.mark.postgres
async def test_postgres_prorrogacao_so_uma_vez(banco_de_negocio: psycopg.AsyncConnection[TupleRow], relogio: Relogio) -> None:
    await _prorrogar_uma_vez(await obter_pendentes_store(), relogio)


@pytest.mark.postgres
async def test_postgres_esquema_de_assuntos_pendentes(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    await obter_pendentes_store()
    colunas = await (
        await banco_de_negocio.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'assuntos_pendentes' ORDER BY ordinal_position"
        )
    ).fetchall()
    assert colunas == [
        ("id", "bigint", "NO"),
        ("id_pessoa", "text", "NO"),
        ("chat_id_origem", "text", "NO"),
        ("posicao", "integer", "NO"),
        ("nome", "text", "NO"),
        ("flow_id", "text", "YES"),
        ("tipo_caso", "text", "YES"),
        ("urgente", "boolean", "NO"),
        ("situacao", "text", "NO"),
        ("criado_em", "timestamp with time zone", "NO"),
        ("vence_em", "timestamp with time zone", "NO"),
        ("prorrogado", "boolean", "NO"),
    ]
