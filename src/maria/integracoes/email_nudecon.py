"""Envio do e-mail ao NUDECON pela função Lambda `maria-email-nudecon` (issue #405, contrato em
`maria-email-nudecon/docs/contrato.md`).

Sem EMAIL_NUDECON_URL ou EMAIL_NUDECON_API_KEY, só `APP_ENV=test` cai num mock (sucesso, sem chamar a função). Fora
dos testes a falta de configuração conta como falha, e não como sucesso: um ambiente mal configurado nunca pode
dizer à pessoa que o pedido foi enviado. Nunca registra os dados da pessoa, as URLs das imagens (o token vai na URL) nem a chave:
só o protocolo, o status e um motivo curto.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Mapping
from typing import Any

import httpx

from maria.integracoes.cliente_http import obter_cliente_http
from maria.shared import _js
from maria.shared.logger import logger

EMAIL_NUDECON_URL = os.environ.get("EMAIL_NUDECON_URL", "")
EMAIL_NUDECON_API_KEY = os.environ.get("EMAIL_NUDECON_API_KEY", "")
# Prazo total da chamada: a Lambda baixa as imagens e fala com o SES, e a resposta à Tykhe tem limite de 30 s (#344).
TIMEOUT_EMAIL_NUDECON_S = 20.0
TENTATIVAS_EMAIL_NUDECON = 3


def protocolo_do_atendimento(chat_id: str) -> str:
    """Chave de idempotência da Lambda: a mesma para o mesmo atendimento, e que não revela o `chatId`."""
    return "NUD-" + hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:12].upper()


async def enviar_email_nudecon(protocolo: str, dados: Mapping[str, str], imagens: Mapping[str, str]) -> bool:
    """`True` se a função confirmou o envio (200, inclusive protocolo repetido). Nunca lança exceção."""
    if not EMAIL_NUDECON_URL or not EMAIL_NUDECON_API_KEY:
        mock = os.environ.get("APP_ENV") == "test"
        logger.warn(
            "[email-nudecon] EMAIL_NUDECON_URL/EMAIL_NUDECON_API_KEY ausente"
            + (" — modo mock (testes), e-mail não enviado de verdade" if mock else ": e-mail não enviado"),
            protocolo=protocolo,
            evento="email_nudecon_mock" if mock else "email_nudecon_falha",
            motivo=None if mock else "sem_configuracao",
        )
        return mock

    corpo: dict[str, Any] = {"protocolo": protocolo, "dados": dict(dados)}
    if imagens:
        corpo["imagens"] = dict(imagens)
    headers = {"authorization": f"Bearer {EMAIL_NUDECON_API_KEY}", "content-type": "application/json"}
    conteudo = _js.json_stringify(corpo).encode("utf-8")
    # A função é idempotente pelo `protocolo`: repetir com o mesmo protocolo nunca manda outro e-mail. Por isso 5xx, 409
    # (envio igual em andamento), falha de rede e prazo são repetidos, dentro do prazo total da chamada.
    try:
        async with asyncio.timeout(TIMEOUT_EMAIL_NUDECON_S):
            for tentativa in range(1, TENTATIVAS_EMAIL_NUDECON + 1):
                try:
                    res = await obter_cliente_http().post(EMAIL_NUDECON_URL, headers=headers, content=conteudo)
                except httpx.HTTPError as erro:
                    logger.error(
                        "[email-nudecon] falha de rede",
                        protocolo=protocolo,
                        evento="email_nudecon_falha",
                        motivo="rede",
                        tentativa=tentativa,
                        tipoErro=type(erro).__name__,
                    )
                    continue
                except TimeoutError:
                    logger.error(
                        "[email-nudecon] prazo esgotado",
                        protocolo=protocolo,
                        evento="email_nudecon_falha",
                        motivo="timeout",
                        tentativa=tentativa,
                    )
                    continue
                if res.is_success:
                    logger.info(
                        "[email-nudecon] e-mail enviado",
                        protocolo=protocolo,
                        evento="email_nudecon_enviado",
                        status=res.status_code,
                        tentativa=tentativa,
                    )
                    return True
                logger.error(
                    "[email-nudecon] função recusou",
                    protocolo=protocolo,
                    evento="email_nudecon_falha",
                    status=res.status_code,
                    tentativa=tentativa,
                )
                if res.status_code < 500 and res.status_code != 409:
                    return False
    except TimeoutError:
        logger.error("[email-nudecon] prazo total esgotado", protocolo=protocolo, evento="email_nudecon_falha", motivo="timeout")
    return False
