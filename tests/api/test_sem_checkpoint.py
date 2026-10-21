"""#270: atendimento registrado cujo checkpoint não existe mais.

Antes da correção, o estado vazio virava `concluido` com a mensagem de sucesso do
fluxo ("Show! Já confirmei os dados da pessoa presa…"), sem que nada tivesse
acontecido. Develop responde igual (controle executado em 2026-10-21), e o corte
da migração faria isso com toda conversa em andamento: a versão Python não lê o
checkpoint da TypeScript.
"""

import json
import os
from collections.abc import AsyncIterator
from itertools import count

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.rows import TupleRow

from maria.api.atendimentos import MENSAGEM_CONVERSA_SEM_CHECKPOINT
from maria.app import criar_app
from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA
from maria.fluxos.pessoa_presa.api import MENSAGEM_CONCLUIDO as CONCLUIDO_PESSOA_PRESA
from maria.fluxos.violencia_domestica.api import MENSAGEM_CONCLUIDO as CONCLUIDO_VIOLENCIA_DOMESTICA
from maria.shared.checkpointer import SCHEMA_CHECKPOINT, obter_checkpointer

_ids = count(1)

# (fluxo, respostas até ficar no meio da conversa, próxima resposta, mensagem de sucesso que não pode sair)
FLUXOS = {
    "pessoa presa": (ID_PESSOA_PRESA, ["Não"], "123456789", CONCLUIDO_PESSOA_PRESA),
    "violência doméstica": (ID_VIOLENCIA_DOMESTICA, [], "Sim", CONCLUIDO_VIOLENCIA_DOMESTICA),
}


async def _responder(cliente: httpx.AsyncClient, auth: dict[str, str], chat_id: str, resposta: str) -> httpx.Response:
    return await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": resposta}, headers=auth)


async def _no_meio_da_conversa(cliente: httpx.AsyncClient, auth: dict[str, str], fluxo: str, respostas: list[str]) -> str:
    chat_id = f"teste-sem-checkpoint-{next(_ids)}"
    r = await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": fluxo}, headers=auth)
    assert r.json()["status"] == "em_andamento"
    for resposta in respostas:
        r = await _responder(cliente, auth, chat_id, resposta)
        assert r.json()["status"] == "em_andamento"
    return chat_id


def _linhas_de_log(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    linhas = []
    for linha in capsys.readouterr().out.splitlines():
        try:
            linhas.append(json.loads(linha))
        except json.JSONDecodeError:
            continue
    return linhas


@pytest.mark.parametrize("caso", list(FLUXOS))
async def test_sem_checkpoint_nao_diz_que_concluiu(
    cliente: httpx.AsyncClient, auth: dict[str, str], capsys: pytest.CaptureFixture[str], caso: str
) -> None:
    fluxo, respostas, proxima, sucesso = FLUXOS[caso]
    chat_id = await _no_meio_da_conversa(cliente, auth, fluxo, respostas)
    await obter_checkpointer().adelete_thread(chat_id)
    capsys.readouterr()

    r = await _responder(cliente, auth, chat_id, proxima)

    corpo = r.json()
    assert r.status_code == 409
    assert corpo["status"] == "expirado"
    assert corpo["resposta"] == MENSAGEM_CONVERSA_SEM_CHECKPOINT
    assert corpo["resposta"] != sucesso
    assert "confirmei" not in corpo["resposta"] and "encaminhamento" not in corpo["resposta"]
    assert any(linha.get("evento") == "atendimento_sem_checkpoint" and linha.get("chatId") == chat_id for linha in _linhas_de_log(capsys))


async def test_depois_de_expirado_a_proxima_resposta_continua_expirada(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    fluxo, respostas, proxima, _ = FLUXOS["pessoa presa"]
    chat_id = await _no_meio_da_conversa(cliente, auth, fluxo, respostas)
    await obter_checkpointer().adelete_thread(chat_id)
    await _responder(cliente, auth, chat_id, proxima)

    r = await _responder(cliente, auth, chat_id, "oi")

    assert r.status_code == 409
    assert r.json()["status"] == "expirado"


async def test_concluido_de_verdade_continua_com_o_409_de_concluido(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    # Regressão: o checkpoint existe e tem statusFinal. Nada muda nesse caminho.
    chat_id = f"teste-sem-checkpoint-{next(_ids)}"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    fim = await _responder(cliente, auth, chat_id, "false")
    assert fim.json()["status"] == "handoff_humano"

    r = await _responder(cliente, auth, chat_id, "oi")

    assert r.status_code == 409
    assert r.json()["erro"] == "atendimento já foi concluído — nada esperando resposta"
    assert r.json()["status"] == "handoff_humano"


# --- Postgres real: o corte, com o checkpoint apagado do schema do Python -------


@pytest.fixture
async def cliente_postgres(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[httpx.AsyncClient, psycopg.AsyncConnection[TupleRow]]]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("os testes postgres precisam de DATABASE_URL (no CI, o serviço Postgres)")
    monkeypatch.delenv("VERDE_JWT_TOKEN", raising=False)
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as banco:
        await banco.execute("DROP TABLE IF EXISTS public.atendimentos")
        app = criar_app(pre_aquecer=False)
        async with app.router.lifespan_context(app):
            transporte = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            async with httpx.AsyncClient(transport=transporte, base_url="http://127.0.0.1:3001") as cliente:
                yield cliente, banco


@pytest.mark.postgres
async def test_corte_conversa_em_andamento_sem_checkpoint_no_postgres(
    cliente_postgres: tuple[httpx.AsyncClient, psycopg.AsyncConnection[TupleRow]], auth: dict[str, str]
) -> None:
    cliente, banco = cliente_postgres
    fluxo, respostas, proxima, sucesso = FLUXOS["pessoa presa"]
    chat_id = await _no_meio_da_conversa(cliente, auth, fluxo, respostas)
    # O que o corte faz: a linha de `atendimentos` fica, e o checkpoint que a versão
    # Python enxerga (schema próprio) não tem essa conversa.
    for tabela in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
        await banco.execute(
            sql.SQL("DELETE FROM {}.{} WHERE thread_id = %s").format(sql.Identifier(SCHEMA_CHECKPOINT), sql.Identifier(tabela)), (chat_id,)
        )

    r = await _responder(cliente, auth, chat_id, proxima)

    assert r.status_code == 409
    assert r.json()["status"] == "expirado"
    assert r.json()["resposta"] != sucesso
    cursor = await banco.execute("SELECT status_final, destino FROM public.atendimentos WHERE chat_id = %s", (chat_id,))
    assert await cursor.fetchone() == ("expirado", "sessao_expirada")
