"""Store de atendimentos: testes novos da spec do módulo persistencia (1-5, 14, 18).

Develop não tinha teste próprio desta store; ela era exercida pelos testes de
rota, que migram no módulo api.
"""

import uuid
from datetime import datetime

import psycopg
import pytest
from psycopg.rows import TupleRow

from maria.shared.atendimentos_db import obter_atendimentos_store

pytestmark = pytest.mark.usefixtures("stores_limpas")

FLUXO_A = "cabb2495-4e12-4f4a-9956-3d20649059bc"
FLUXO_B = "8d9c5d1e-6a7b-4c3d-9e2f-1a2b3c4d5e6f"


@pytest.fixture
def sem_banco(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


# --- Em memória ----------------------------------------------------------------


@pytest.mark.usefixtures("sem_banco")
async def test_memoria_registrar_idempotente_e_conflito() -> None:
    store = await obter_atendimentos_store()
    assert await store.registrar("chat-m", FLUXO_A) == {"ok": True}
    assert await store.registrar("chat-m", FLUXO_A) == {"ok": True}
    assert await store.registrar("chat-m", FLUXO_B) == {"ok": False, "flowIdExistente": FLUXO_A}
    assert await store.buscar_flow_id("chat-m") == FLUXO_A
    assert await store.buscar_flow_id("chat-inexistente") is None


@pytest.mark.usefixtures("sem_banco")
async def test_memoria_concluir_grava_so_status_final() -> None:
    # Divergência mantida (atendimentosDb.ts:70-73): a memória ignora destino,
    # motivo e tokens; o Postgres grava tudo (teste 4).
    store = await obter_atendimentos_store()
    await store.registrar("chat-c", FLUXO_A)
    await store.concluir("chat-c", {"statusFinal": "handoff_humano", "destino": "x", "motivoHandoff": "y"})
    atividade = await store.buscar_atividade("chat-c")
    assert atividade is not None
    assert atividade["statusFinal"] == "handoff_humano"


@pytest.mark.usefixtures("sem_banco")
async def test_memoria_atividade_omite_chaves_ausentes() -> None:
    store = await obter_atendimentos_store()
    await store.registrar("chat-a", FLUXO_A)
    atividade = await store.buscar_atividade("chat-a")
    assert atividade is not None
    assert set(atividade) == {"atualizadoEm", "aguardandoConfirmacaoTtl"}
    assert atividade["aguardandoConfirmacaoTtl"] is False
    assert await store.buscar_atividade("chat-inexistente") is None


@pytest.mark.usefixtures("sem_banco")
async def test_memoria_resolver_confirmacao_ttl_devolve_a_resposta_pendente() -> None:
    # Na memória a resposta pendente volta; no Postgres, não (teste 18 e #217).
    store = await obter_atendimentos_store()
    await store.registrar("chat-ttl", FLUXO_A)
    await store.marcar_aguardando_confirmacao_ttl("chat-ttl", "123456789")
    assert await store.resolver_confirmacao_ttl_continuar("chat-ttl") == "123456789"
    atividade = await store.buscar_atividade("chat-ttl")
    assert atividade is not None
    assert atividade["aguardandoConfirmacaoTtl"] is False
    assert "respostaPendente" not in atividade


# --- Postgres real ------------------------------------------------------------


@pytest.mark.postgres
async def test_postgres_registrar_mesmo_flow_id_devolve_ok(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 1: sem o str() do uuid.UUID, o segundo registro viraria conflito falso.
    store = await obter_atendimentos_store()
    assert await store.registrar("chat-pg-1", FLUXO_A) == {"ok": True}
    assert await store.registrar("chat-pg-1", FLUXO_A) == {"ok": True}


@pytest.mark.postgres
async def test_postgres_registrar_outro_flow_id_devolve_conflito_em_str(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 2.
    store = await obter_atendimentos_store()
    await store.registrar("chat-pg-2", FLUXO_A)
    resultado = await store.registrar("chat-pg-2", FLUXO_B)
    assert resultado == {"ok": False, "flowIdExistente": FLUXO_A}
    assert type(resultado["flowIdExistente"]) is str  # type: ignore[typeddict-item]


@pytest.mark.postgres
async def test_postgres_buscar_flow_id_devolve_str(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 3.
    store = await obter_atendimentos_store()
    await store.registrar("chat-pg-3", FLUXO_A.upper())
    flow_id = await store.buscar_flow_id("chat-pg-3")
    assert type(flow_id) is str
    assert flow_id == FLUXO_A  # o Postgres devolve o UUID em minúsculas, como o pg


@pytest.mark.postgres
async def test_postgres_concluir_grava_todas_as_colunas_juntas(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 4. É o caminho que o plano de corte (#208) usa para encerrar
    # atendimentos; um teste em memória não provaria nada, porque a memória grava
    # só statusFinal.
    store = await obter_atendimentos_store()
    await store.registrar("chat-pg-4", FLUXO_A)
    await store.registrar("chat-pg-4b", FLUXO_A)
    await store.concluir(
        "chat-pg-4",
        {
            "statusFinal": "handoff_humano",
            "destino": "verde",
            "motivoHandoff": "rg_nao_encontrado",
            "tokensGastos": {"input": 11, "output": 7, "total": 18},
        },
    )
    await store.concluir("chat-pg-4b", {"statusFinal": "expirado"})
    cursor = await banco_de_negocio.execute(
        """SELECT chat_id, concluido_em IS NOT NULL, status_final, destino, motivo_handoff, tokens_entrada, tokens_saida, tokens_total
           FROM atendimentos WHERE chat_id IN ('chat-pg-4', 'chat-pg-4b') ORDER BY chat_id"""
    )
    assert await cursor.fetchall() == [
        ("chat-pg-4", True, "handoff_humano", "verde", "rg_nao_encontrado", 11, 7, 18),
        ("chat-pg-4b", True, "expirado", None, None, None, None, None),
    ]


@pytest.mark.postgres
async def test_postgres_atividade_com_fuso_e_sem_truncar(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 5: datetime com fuso, igual ao valor guardado (microssegundo mantido).
    store = await obter_atendimentos_store()
    await store.registrar("chat-pg-5", FLUXO_A)
    atividade = await store.buscar_atividade("chat-pg-5")
    assert atividade is not None
    assert isinstance(atividade["atualizadoEm"], datetime)
    assert atividade["atualizadoEm"].tzinfo is not None
    cursor = await banco_de_negocio.execute("SELECT atualizado_em FROM atendimentos WHERE chat_id = 'chat-pg-5'")
    linha = await cursor.fetchone()
    assert linha is not None
    assert atividade["atualizadoEm"] == linha[0]
    assert set(atividade) == {"atualizadoEm", "aguardandoConfirmacaoTtl"}


@pytest.mark.postgres
async def test_postgres_esquema_de_atendimentos(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 14.
    await obter_atendimentos_store()
    cursor = await banco_de_negocio.execute(
        """SELECT column_name, data_type, is_nullable, column_default
           FROM information_schema.columns WHERE table_name = 'atendimentos' ORDER BY ordinal_position"""
    )
    colunas = {nome: (tipo, nulo, padrao) for nome, tipo, nulo, padrao in await cursor.fetchall()}
    assert colunas == {
        "chat_id": ("text", "NO", None),
        "flow_id": ("uuid", "NO", None),
        "criado_em": ("timestamp with time zone", "NO", "now()"),
        "concluido_em": ("timestamp with time zone", "YES", None),
        "status_final": ("text", "YES", None),
        "destino": ("text", "YES", None),
        "motivo_handoff": ("text", "YES", None),
        "tokens_entrada": ("integer", "YES", None),
        "tokens_saida": ("integer", "YES", None),
        "tokens_total": ("integer", "YES", None),
        "atualizado_em": ("timestamp with time zone", "YES", "now()"),
        "aguardando_confirmacao_ttl": ("boolean", "NO", "false"),
        "resposta_pendente_ttl": ("text", "YES", None),
    }


@pytest.mark.postgres
async def test_postgres_resolver_confirmacao_ttl_devolve_none(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 18.
    # A divergência é DELIBERADA e TEMPORÁRIA: reproduz develop @ 4e695f2, onde o
    # RETURNING do UPDATE devolve o valor já limpo, e a resposta pendente da pessoa
    # é descartada em produção.
    # Defeito registrado em https://github.com/dgd-dprj/maria-langgraph-pp/issues/217
    # Não "corrija" aqui: isso muda o comportamento de produção sem decisão
    # registrada. A correção é feita naquela issue, que substitui este teste. Este
    # teste é também a confirmação, contra Postgres real, do defeito da #217.
    store = await obter_atendimentos_store()
    chat_id = f"chat-ttl-{uuid.uuid4()}"
    await store.registrar(chat_id, FLUXO_A)
    await store.marcar_aguardando_confirmacao_ttl(chat_id, "123456789")
    cursor = await banco_de_negocio.execute("SELECT resposta_pendente_ttl FROM atendimentos WHERE chat_id = %s", (chat_id,))
    assert await cursor.fetchone() == ("123456789",)

    assert await store.resolver_confirmacao_ttl_continuar(chat_id) is None

    cursor = await banco_de_negocio.execute(
        "SELECT aguardando_confirmacao_ttl, resposta_pendente_ttl FROM atendimentos WHERE chat_id = %s", (chat_id,)
    )
    assert await cursor.fetchone() == (False, None)
