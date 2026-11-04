"""Configuração comum da suíte.

O ambiente de teste é definido aqui, no topo, antes de qualquer import do
pacote `maria`. Equivale ao `cross-env NODE_ENV=test API_KEY=teste-fixo-chave`
do `pnpm test` de develop. Isso importa porque alguns módulos leem variáveis
na importação, como em develop (por exemplo, `VERDE_JWT_TOKEN`, que decide o
modo mock do Verde).

`APP_ENV` substitui `NODE_ENV` (#208). O código só distingue `test`; qualquer outro
valor se comporta como produção (corrigido em 2026-10-20, achado C4 da spec 09).
"""

import asyncio
import os
import sys
from collections.abc import Mapping

import pytest

os.environ["APP_ENV"] = "test"
os.environ["API_KEY"] = "teste-fixo-chave"

from maria.integracoes.email_nudecon import ResultadoEmail

# O psycopg assíncrono não funciona com o ProactorEventLoop, padrão do Windows.
# Só afeta quem roda a suíte no Windows; o CI e a imagem são Linux.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class EmailNudeconFalso:
    """Substitui a chamada à função de e-mail do NUDECON (#405): guarda as chamadas e devolve `resultado`."""

    def __init__(self) -> None:
        self.chamadas: list[dict[str, object]] = []
        self.resultado = ResultadoEmail(ok=True)

    async def __call__(self, protocolo: str, dados: Mapping[str, str], imagens: Mapping[str, str] | None = None) -> ResultadoEmail:
        self.chamadas.append({"protocolo": protocolo, "dados": dict(dados), "imagens": dict(imagens) if imagens else None})
        return self.resultado


@pytest.fixture(autouse=True)
def email_nudecon(monkeypatch: pytest.MonkeyPatch) -> EmailNudeconFalso:
    """Sem isto o fluxo do plano de saúde, sem URL nem chave da função, cairia no atendimento humano ao concluir."""
    falso = EmailNudeconFalso()
    monkeypatch.setattr("maria.fluxos.plano_saude.graph.enviar_email_nudecon", falso)
    return falso
