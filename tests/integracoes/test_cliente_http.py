"""Teste 23 da spec do módulo integracoes: parâmetros do cliente HTTP, sem rede.

Cada valor reproduz o fetch/undici de develop, e não o padrão do httpx
(padrão "parâmetro com nome familiar e semântica diferente", comentário 12 da #208).
"""

from maria.app import FINALIZADORES
from maria.integracoes.cliente_http import LIMITES, PRAZOS, criar_cliente_http, fechar_cliente_http


async def test_23_parametros_do_cliente_reproduzem_o_undici() -> None:
    cliente = criar_cliente_http()
    try:
        assert cliente.follow_redirects is True
        assert cliente.max_redirects == 20
        assert cliente.trust_env is False
        assert cliente.timeout.connect == 10.0  # connectTimeout do undici
        for fase in (cliente.timeout.read, cliente.timeout.write, cliente.timeout.pool):
            assert fase is not None and fase > 30.0  # só o prazo total de 30 s por tentativa age
    finally:
        await cliente.aclose()


def test_23_limites_do_pool_de_conexoes() -> None:
    assert PRAZOS.connect == 10.0
    assert LIMITES.max_connections is None  # sem limite por origem, como o undici (aceito por fidelidade)
    assert LIMITES.max_keepalive_connections is None
    assert LIMITES.keepalive_expiry == 4.0  # keepAliveTimeout do undici


def test_cliente_fechado_no_fim_do_lifespan() -> None:
    assert fechar_cliente_http in FINALIZADORES
