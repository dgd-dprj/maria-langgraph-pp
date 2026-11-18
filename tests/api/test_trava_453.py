"""#453: duas chamadas iguais ao mesmo tempo para criar o mesmo atendimento rodam o fluxo uma vez só.

O fluxo de pessoa presa é o de verdade, envolvido num grafo "lento" que conta as execuções e espera um pouco antes ou
depois de rodar, para as duas chamadas se sobreporem. No Postgres, cada chamada usa a própria conexão do pool, como
duas tarefas do ECS: é a trava no banco que segura a segunda.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import os
from collections.abc import AsyncIterator
from itertools import count
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.rows import TupleRow

from maria.api import atendimentos
from maria.app import criar_app
from maria.fluxos import ID_PESSOA_PRESA, fluxos_por_id
from maria.shared import trava as trava_mod

_ids = count(1)


def _chat() -> str:
    return f"teste-453-{next(_ids)}"


class GrafoLento:
    """O grafo de verdade, com uma espera antes e depois do `ainvoke` e a contagem de execuções."""

    def __init__(self, antes: float = 0.0, depois: float = 0.0) -> None:
        self.antes, self.depois = antes, depois
        self.execucoes = 0
        self.grafo: Any = None
        # Sinais para a segunda chamada partir no momento certo, sem depender de tempo fixo:
        # `entrou` quando a primeira já segura a trava e roda o fluxo; `gravou` quando a 1ª pergunta já foi gravada.
        self.entrou = asyncio.Event()
        self.gravou = asyncio.Event()

    def __getattr__(self, nome: str) -> Any:
        return getattr(self.grafo, nome)

    async def ainvoke(self, entrada: Any, config: Any = None, **kwargs: Any) -> Any:
        self.execucoes += 1
        self.entrou.set()
        await asyncio.sleep(self.antes)
        resultado = await self.grafo.ainvoke(entrada, config, **kwargs)
        self.gravou.set()
        await asyncio.sleep(self.depois)
        return resultado


@pytest.fixture
def lento(monkeypatch: pytest.MonkeyPatch) -> GrafoLento:
    original = fluxos_por_id[ID_PESSOA_PRESA]
    grafo = GrafoLento()

    def obter() -> Any:
        grafo.grafo = original.obter_grafo()
        return grafo

    monkeypatch.setitem(fluxos_por_id, ID_PESSOA_PRESA, dataclasses.replace(original, obter_grafo=obter))
    return grafo


async def _criar(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str) -> tuple[int, Any]:
    r = await cliente.post("/atendimentos", json={"flowId": ID_PESSOA_PRESA, "chatId": chat}, headers=auth)
    return r.status_code, r.json()


def _visivel(corpo: Any) -> Any:
    """O que a Tykhe mostra e usa para seguir: a mesma resposta nas duas chamadas."""
    return {k: corpo.get(k) for k in ("chatId", "status", "resposta", "tipoResposta", "opcoes")}


async def _duas_ao_mesmo_tempo(
    cliente: httpx.AsyncClient, auth: dict[str, str], chat: str, sinal: asyncio.Event
) -> tuple[tuple[int, Any], tuple[int, Any]]:
    async def segunda() -> tuple[int, Any]:
        await asyncio.wait_for(sinal.wait(), timeout=10)  # chega com a primeira no meio, como um reenvio da Tykhe
        return await _criar(cliente, auth, chat)

    primeira, depois = await asyncio.gather(_criar(cliente, auth, chat), segunda())
    return primeira, depois


# --- Em memória (sem DATABASE_URL): a mesma regra com a trava local ------------------------------------------------------


async def test_memoria_duas_chamadas_rodam_o_fluxo_uma_vez(cliente: httpx.AsyncClient, auth: dict[str, str], lento: GrafoLento) -> None:
    lento.antes = 0.3
    (c1, a), (c2, b) = await _duas_ao_mesmo_tempo(cliente, auth, _chat(), lento.entrou)
    assert (c1, c2) == (200, 200)
    assert lento.execucoes == 1
    assert _visivel(a) == _visivel(b)


# --- Postgres de verdade ---------------------------------------------------------------------------------------------------


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
async def test_postgres_duas_chamadas_ao_mesmo_tempo_rodam_o_fluxo_uma_vez(
    cliente_postgres: tuple[httpx.AsyncClient, psycopg.AsyncConnection[TupleRow]], auth: dict[str, str], lento: GrafoLento
) -> None:
    cliente, banco = cliente_postgres
    lento.antes = 0.5
    chat = _chat()
    (c1, a), (c2, b) = await _duas_ao_mesmo_tempo(cliente, auth, chat, lento.entrou)
    assert (c1, c2) == (200, 200)
    assert lento.execucoes == 1
    # As duas recebem a mesma 1ª pergunta, e nenhuma recebe mensagem de sucesso antes da hora.
    assert _visivel(a) == _visivel(b)
    assert a["status"] == "em_andamento"
    cursor = await banco.execute("SELECT count(*) FROM public.atendimentos WHERE chat_id = %s", (chat,))
    assert await cursor.fetchone() == (1,)


@pytest.mark.postgres
async def test_postgres_sem_a_trava_o_defeito_aparece(
    cliente_postgres: tuple[httpx.AsyncClient, psycopg.AsyncConnection[TupleRow]],
    auth: dict[str, str],
    lento: GrafoLento,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # O controle: sem trava, a mesma corrida roda o fluxo duas vezes. É o que prova que o teste acima reproduz a #453.
    @contextlib.asynccontextmanager
    async def sem_trava(_chave: str, _espera: float | None = None) -> AsyncIterator[bool]:
        yield True

    monkeypatch.setattr(atendimentos, "trava", sem_trava)
    cliente, _ = cliente_postgres
    lento.antes = 0.5
    await _duas_ao_mesmo_tempo(cliente, auth, _chat(), lento.entrou)
    assert lento.execucoes == 2


@pytest.mark.postgres
async def test_postgres_espera_estourada_sem_estado_gravado_pede_para_tentar_de_novo(
    cliente_postgres: tuple[httpx.AsyncClient, psycopg.AsyncConnection[TupleRow]],
    auth: dict[str, str],
    lento: GrafoLento,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A primeira segura a trava por 1 s antes de gravar qualquer coisa; a segunda desiste aos 0,2 s.
    monkeypatch.setattr(trava_mod, "ESPERA_MAXIMA_S", 0.2)
    cliente, _ = cliente_postgres
    lento.antes = 1.0
    chat = _chat()
    (c1, a), (c2, b) = await _duas_ao_mesmo_tempo(cliente, auth, chat, lento.entrou)
    assert lento.execucoes == 1
    assert (c1, c2) == (200, 409)
    assert b == {"erro": "atendimento em processamento — tente de novo em instantes", "status": "em_andamento"}
    # A nova tentativa encontra o estado gravado: a mesma pergunta da primeira.
    c3, c = await _criar(cliente, auth, chat)
    assert c3 == 200 and _visivel(c) == _visivel(a)
    assert lento.execucoes == 1


@pytest.mark.postgres
async def test_postgres_espera_estourada_com_estado_gravado_devolve_o_estado_atual(
    cliente_postgres: tuple[httpx.AsyncClient, psycopg.AsyncConnection[TupleRow]],
    auth: dict[str, str],
    lento: GrafoLento,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A primeira já gravou a 1ª pergunta, mas ainda segura a trava por 1 s; a segunda desiste aos 0,2 s e devolve o estado.
    monkeypatch.setattr(trava_mod, "ESPERA_MAXIMA_S", 0.2)
    cliente, _ = cliente_postgres
    lento.depois = 1.0
    (c1, a), (c2, b) = await _duas_ao_mesmo_tempo(cliente, auth, _chat(), lento.gravou)
    assert (c1, c2) == (200, 200)
    assert lento.execucoes == 1
    assert _visivel(a) == _visivel(b)
