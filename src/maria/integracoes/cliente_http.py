"""Cliente HTTP único do processo, para o Verde e para o WhatsApp.

Em develop, o `fetch` do Node usa o pool global do undici. Os parâmetros
abaixo reproduzem o undici, e não os padrões do httpx. Cada um foi conferido
nos dois lados (padrão "parâmetro com nome familiar e semântica diferente",
comentário 12 da #208):

| | fetch/undici (develop) | httpx (padrão) | usado |
|---|---|---|---|
| redirect | segue até 20 | não segue | follow_redirects=True |
| abrir conexão | 10 s (connectTimeout) | 5 s | connect=10.0 |
| cabeçalhos e corpo | 300 s (headersTimeout/bodyTimeout) | 5 s por leitura | 300 s |
| conexões por origem | sem limite | 100 | max_connections=None |
| conexão ociosa | 4 s (keepAliveTimeout) | 5 s | keepalive_expiry=4.0 |
| proxy do ambiente | ignora | lê HTTP(S)_PROXY | trust_env=False |

O prazo TOTAL de cada chamada (30 s no Verde, 10 s no WhatsApp) não é do
cliente: é aplicado por chamada, com asyncio.timeout_at, como o
AbortSignal.timeout de develop.

`max_connections=None` é limite ausente que ninguém escolheu, nem em develop:
aceito por fidelidade, não por desenho (MIGRACAO.md).
"""

from __future__ import annotations

import httpx

# Cabeçalhos implícitos do fetch do Node, igualados (spec do módulo integracoes).
# O user-agent foi capturado com o Node 24; o padrão do undici no Node 22 é o
# mesmo, a conferir (pendência da spec). O accept-encoding segue o do httpx.
CABECALHOS_DO_FETCH = {"user-agent": "node", "accept-language": "*", "sec-fetch-mode": "cors"}

PRAZOS = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=300.0)
LIMITES = httpx.Limits(max_connections=None, max_keepalive_connections=None, keepalive_expiry=4.0)

_cliente: httpx.AsyncClient | None = None


def criar_cliente_http(transporte: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=20,
        trust_env=False,
        timeout=PRAZOS,
        limits=LIMITES,
        headers=CABECALHOS_DO_FETCH,
        transport=transporte,
    )


def obter_cliente_http() -> httpx.AsyncClient:
    """Criado na primeira chamada; em develop, o fetch não tem inicialização."""
    global _cliente
    if _cliente is None:
        _cliente = criar_cliente_http()
    return _cliente


def definir_cliente_http(cliente: httpx.AsyncClient | None) -> None:
    """Só para testes: injeta um cliente com transporte falso."""
    global _cliente
    _cliente = cliente


async def fechar_cliente_http() -> None:
    """Chamado no fim do lifespan (FINALIZADORES em app.py)."""
    global _cliente
    if _cliente is not None:
        await _cliente.aclose()
    _cliente = None
