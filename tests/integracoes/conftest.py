"""Fixtures das integrações: cliente HTTP com transporte falso, sem rede.

O VERDE_JWT_TOKEN é lido na importação do módulo, como em develop. Para testar
o caminho real (fora do modo mock), os testes trocam o atributo do módulo, e
não a variável de ambiente.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import pytest

from maria.integracoes import verde, whatsapp
from maria.integracoes.cliente_http import criar_cliente_http, definir_cliente_http, fechar_cliente_http

URL_VERDE = "https://verde.teste/api/integra"

Tratador = Callable[[httpx.Request], Awaitable[httpx.Response]]


@dataclass
class TransporteFalso:
    """Registra cada requisição e devolve o que o `tratador` do teste mandar."""

    tratador: Tratador | None = None
    requisicoes: list[httpx.Request] = field(default_factory=list)
    corpos: list[bytes] = field(default_factory=list)

    async def __call__(self, requisicao: httpx.Request) -> httpx.Response:
        self.requisicoes.append(requisicao)
        self.corpos.append(await requisicao.aread())
        if self.tratador is None:
            return httpx.Response(200, json={"dados": {}})
        return await self.tratador(requisicao)


@pytest.fixture
async def transporte() -> AsyncIterator[TransporteFalso]:
    falso = TransporteFalso()
    await fechar_cliente_http()
    definir_cliente_http(criar_cliente_http(httpx.MockTransport(falso)))
    yield falso
    await fechar_cliente_http()


@pytest.fixture
def verde_real(monkeypatch: pytest.MonkeyPatch, transporte: TransporteFalso) -> TransporteFalso:
    """Tira o módulo do modo mock e aponta para uma URL de teste."""
    monkeypatch.setattr(verde, "VERDE_JWT_TOKEN", "token-de-teste")
    monkeypatch.setattr(verde, "VERDE_CLIENT_ID", "cliente-de-teste")
    monkeypatch.setattr(verde, "VERDE_API_URL", URL_VERDE)
    return transporte


@pytest.fixture
def whatsapp_real(monkeypatch: pytest.MonkeyPatch, transporte: TransporteFalso) -> TransporteFalso:
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "token-meta")
    monkeypatch.setattr(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "123456")
    monkeypatch.setattr(whatsapp, "WHATSAPP_API_URL", "https://graph.teste/v21.0")
    return transporte
