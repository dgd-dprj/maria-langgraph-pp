"""O que o Bedrock dos módulos persistencia (embeddings) e ia (Converse) compartilha.

Um único lugar, como o `criar_pool` para o Postgres: cada parâmetro aqui
reproduz develop, e não o padrão da biblioteca Python (padrão "parâmetro com
nome familiar e semântica diferente", comentário 12 da #208).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any

from botocore.config import Config
from botocore.exceptions import ConnectionError as ErroDeConexaoBotocore
from botocore.retries import standard

# O SDK JS (@aws-sdk/client-bedrock-runtime) usa o modo "standard" com 3
# tentativas no total. Sem Config, o boto3 cai no modo "legacy", com 5.
# ATENÇÃO: no botocore, "max_attempts" conta as RETENTATIVAS (max_attempts: 3
# vira 4 requisições); o total é "total_max_attempts". Mais um caso do padrão.
# Os prazos ficam nos padrões do botocore (60 s de conexão e de leitura):
# herdados, não escolhidos (decisão 2 da revisão da spec do ia).
CONFIG_BOTOCORE = Config(retries={"mode": "standard", "total_max_attempts": 3})

# Classificação de erro do SDK JS (@smithy/core 3.33.3, submodules/retry).
_CODIGOS_DE_THROTTLING_DO_SDK_JS = frozenset(
    {
        "BandwidthLimitExceeded",
        "EC2ThrottledException",
        "LimitExceededException",
        "PriorRequestNotComplete",
        "ProvisionedThroughputExceededException",
        "RequestLimitExceeded",
        "RequestThrottled",
        "RequestThrottledException",
        "SlowDown",
        "ThrottledException",
        "Throttling",
        "ThrottlingException",
        "TooManyRequestsException",
        "TransactionInProgressException",
    }
)
_CODIGOS_TRANSITORIOS_DO_SDK_JS = frozenset({"TimeoutError", "RequestTimeout", "RequestTimeoutException"})
_STATUS_TRANSITORIOS_DO_SDK_JS = frozenset({500, 502, 503, 504})


class _CotaComoSdkJs(standard.RetryQuotaChecker):
    """Cota de retentativas com os custos do SDK JS.

    Os dois SDKs começam com 500 fichas por cliente. O JS cobra 10 por
    retentativa de erro "TRANSIENT" (5xx 500/502/503/504, timeout, erro de rede)
    e 5 pelas demais; o botocore cobra 10 só de timeout. Com o Bedrock dando 500
    sempre, o JS esgota a cota em 50 retentativas, e o botocore em 100: 99 contra
    147 requisições nos embeddings (medido em develop). Throttling vem antes,
    como no `getRetryErrorType` do JS, e custa 5.
    """

    def _is_timeout_error(self, context: Any) -> bool:
        resposta = context.http_response
        status = None if resposta is None else resposta.status_code
        if status == 429 or context.get_error_code() in _CODIGOS_DE_THROTTLING_DO_SDK_JS:
            return False
        return (
            isinstance(context.caught_exception, ErroDeConexaoBotocore)
            or context.get_error_code() in _CODIGOS_TRANSITORIOS_DO_SDK_JS
            or status in _STATUS_TRANSITORIOS_DO_SDK_JS
        )


@contextmanager
def cota_como_sdk_js() -> Iterator[None]:
    """Cria, dentro do bloco, clientes botocore com a cota do SDK JS.

    O botocore não expõe como trocar a cota de um cliente já criado; o
    `register_retry_handler` lê a classe pelo nome do módulo na criação. A troca
    vale só durante o bloco, que deve conter apenas a construção do cliente
    (síncrona, na thread do event loop).
    """
    original = standard.RetryQuotaChecker
    standard.RetryQuotaChecker = _CotaComoSdkJs  # type: ignore[misc]
    try:
        yield
    finally:
        standard.RetryQuotaChecker = original  # type: ignore[misc]


# maxRetries padrão do AsyncCaller do @langchain/core (async_caller.js:182).
TENTATIVAS_EXTRAS_DO_ASYNC_CALLER = 6


def espera_do_p_retry(tentativa: int) -> float:
    """Segundos antes da tentativa seguinte à `tentativa`-ésima falha.

    p-retry com `randomize: true`, `factor` 2, `minTimeout` 1 s e sem teto
    (p-retry/index.js:29-33): de 63 a 126 s somando as 6 esperas.
    """
    return round((random.random() + 1) * 1000 * (1 << (tentativa - 1))) / 1000


async def chamar_como_async_caller[T](
    funcao: Callable[[], Awaitable[T]],
    tentativas_extras: int = TENTATIVAS_EXTRAS_DO_ASYNC_CALLER,
    dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Reproduz `AsyncCaller.call` de develop para os embeddings.

    Retenta qualquer `Exception`. O tratador padrão de develop desiste em 4xx,
    mas o `_embedText` reembrulha o erro do SDK em `new Error(...)` sem status,
    e então nada é reconhecido (nem o 400). Ver a #222.
    """
    tentativa = 1
    while True:
        try:
            return await funcao()
        except Exception:
            if tentativa > tentativas_extras:
                raise
            await dormir(espera_do_p_retry(tentativa))
            tentativa += 1
