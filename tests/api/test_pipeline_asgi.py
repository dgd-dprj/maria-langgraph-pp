"""O pipeline falando ASGI cru, sem o httpx no meio.

O httpx descarta o corpo de respostas a HEAD e trata "//health" como referência
de rede (host "health"). Os dois casos foram mascarados por isso na conferência
e na verificação por mutação; aqui a mensagem ASGI é conferida direto.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI

from maria.app import criar_app


@pytest.fixture
async def app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    aplicacao = criar_app(pre_aquecer=False)
    async with aplicacao.router.lifespan_context(aplicacao):
        yield aplicacao


async def _chamar(app: FastAPI, metodo: str, caminho: str) -> tuple[int, dict[str, str], bytes]:
    enviados: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(mensagem: Any) -> None:
        enviados.append(mensagem)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": metodo,
        "scheme": "http",
        "path": caminho,
        "raw_path": caminho.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"127.0.0.1:3001")],
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 3001),
    }
    await app(scope, receive, send)
    inicio = enviados[0]
    cabecalhos = {k.decode(): v.decode() for k, v in inicio["headers"]}
    return inicio["status"], cabecalhos, b"".join(m.get("body", b"") for m in enviados[1:])


async def test_head_health_sem_corpo_e_com_o_content_type_do_get(app: FastAPI) -> None:
    # Fixture health-head: 200, application/json; charset=utf-8, corpo vazio.
    status, cabecalhos, corpo = await _chamar(app, "HEAD", "/health")
    assert status == 200
    assert cabecalhos["content-type"] == "application/json; charset=utf-8"
    assert corpo == b""


async def test_dupla_barra_e_rota_inexistente_com_o_caminho_cru(app: FastAPI) -> None:
    # Conferência (cenário dupla_barra): develop responde "Route GET://health not found".
    status, _, corpo = await _chamar(app, "GET", "//health")
    assert status == 404
    assert corpo == b'{"message":"Route GET://health not found","error":"Not Found","statusCode":404}'
