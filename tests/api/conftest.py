"""Aplicação completa em memória para os testes de rota (o `app.inject` de develop).

Sem `DATABASE_URL`: checkpointer, stores e embeddings em memória. `APP_ENV=test`
(conftest raiz): IA e Verde em mock. Cada teste sobe a aplicação com o lifespan
completo e fala com ela por ASGI, passando pelo PipelineFastify.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest

from maria.app import criar_app


@pytest.fixture
async def cliente(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VERDE_JWT_TOKEN", raising=False)
    for variavel in ("MOCK_CLASSIFICACAO_FLOWID", "MOCK_CLASSIFICACAO_FLOWIDS", "ORQUESTRADOR_INCLUIR_PLANEJADOS"):
        monkeypatch.delenv(variavel, raising=False)
    app = criar_app(pre_aquecer=False)
    async with app.router.lifespan_context(app):
        transporte = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transporte, base_url="http://127.0.0.1:3001") as c:
            yield c


@pytest.fixture
def auth() -> dict[str, str]:
    return {"authorization": f"Bearer {os.environ['API_KEY']}"}
