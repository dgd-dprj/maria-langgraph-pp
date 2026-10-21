"""Envio e extração de mensagens do WhatsApp, pela Graph API da Meta
(tradução de `integracoes/whatsapp.ts`, issue #198).

Sem token ou phone_number_id, cai em modo mock (dev local): registra e não envia.
Nunca registra o texto, o número de destino nem o corpo bruto de erro da Graph
API, que costuma ecoar o número.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, NotRequired, TypedDict

from maria.integracoes.cliente_http import obter_cliente_http
from maria.shared import _js
from maria.shared._js import AUSENTE
from maria.shared.logger import logger

# Lidos na importação, como em develop (whatsapp.ts:7-9).
WHATSAPP_API_URL = os.environ.get("WHATSAPP_API_URL", "https://graph.facebook.com/v21.0")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
# Prazo total (AbortSignal.timeout), da conexão ao último byte do corpo.
TIMEOUT_WHATSAPP_S = 10.0


def _agora_ms() -> int:
    return time.time_ns() // 1_000_000


async def enviar_mensagem_whatsapp(para: str, texto: str, chat_id: str) -> None:
    """Nunca lança exceção: falha só vira log."""
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.warn(
            "[whatsapp] WHATSAPP_ACCESS_TOKEN/WHATSAPP_PHONE_NUMBER_ID ausente — modo mock (dev local), mensagem não enviada de verdade",
            chatId=chat_id,
            evento="whatsapp_envio_mock",
        )
        return

    inicio = _agora_ms()
    try:
        cliente = obter_cliente_http()
        corpo = _js.json_stringify({"messaging_product": "whatsapp", "to": para, "type": "text", "text": {"body": texto}})
        async with asyncio.timeout(TIMEOUT_WHATSAPP_S):
            res = await cliente.post(
                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
                headers={"authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}", "content-type": "application/json"},
                content=corpo.encode("utf-8"),
            )
            duracao_ms = _agora_ms() - inicio
            if not res.is_success:
                # O corpo de erro da Graph API costuma ecoar o número de destino:
                # só código e tipo do erro vão para o log.
                corpo_texto = res.content.decode("utf-8", errors="replace")
                erro_detalhe: Any = AUSENTE
                try:
                    erro = _js.prop(json.loads(corpo_texto), "error")
                    if _js.verdadeiro(erro):
                        erro_detalhe = {}
                        _js.definir(erro_detalhe, "codigo", _js.prop(erro, "code"))
                        _js.definir(erro_detalhe, "tipo", _js.prop(erro, "type"))
                except (ValueError, TypeError):
                    erro_detalhe = AUSENTE
                campos: dict[str, Any] = {
                    "chatId": chat_id,
                    "status": res.status_code,
                    "duracaoMs": duracao_ms,
                    "evento": "whatsapp_envio_falhou",
                }
                _js.definir(campos, "erroDetalhe", erro_detalhe)
                logger.error("[whatsapp] envio falhou", **campos)
                return
        logger.info("[whatsapp] mensagem enviada", chatId=chat_id, duracaoMs=duracao_ms, evento="whatsapp_envio_ok")
    except Exception as erro:
        logger.error(
            "[whatsapp] erro ao enviar mensagem",
            chatId=chat_id,
            duracaoMs=_agora_ms() - inicio,
            evento="whatsapp_envio_erro",
            erro=str(erro),
        )


class MensagemRecebidaWhatsapp(TypedDict):
    de: str
    texto: str


class StatusEntregaWhatsapp(TypedDict):
    status: str
    erroCodigo: NotRequired[int]
    erroTitulo: NotRequired[str]


def _primeiro_item_de_cada_change(payload: Any, chave: str) -> list[Any]:
    """Percorre entry[].changes[] e devolve, de cada change, o 1º item de
    `value.<chave>` (só o primeiro: se ele não servir, passa ao próximo change)."""
    entry = _js.opt(payload, "entry")
    if not isinstance(entry, list):
        return []
    primeiros: list[Any] = []
    for item in entry:
        changes = _js.opt(item, "changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            itens = _js.opt(_js.opt(change, "value"), chave)
            if not isinstance(itens, list) or len(itens) == 0:
                continue
            primeiros.append(itens[0])
    return primeiros


def extrair_mensagem_whatsapp(payload: Any) -> MensagemRecebidaWhatsapp | None:
    """1ª mensagem de texto. Status de entrega e tipos não-texto voltam None.

    Como em develop, o acesso ao 1º item não usa `?.`: um item null em
    `messages` lança TypeError (whatsapp.ts:81)."""
    for mensagem in _primeiro_item_de_cada_change(payload, "messages"):
        tipo = _js.prop(mensagem, "type")
        de = _js.prop(mensagem, "from")
        corpo = _js.opt(_js.prop(mensagem, "text"), "body")
        if tipo != "text" or not _js.verdadeiro(de) or not _js.verdadeiro(corpo):
            continue
        return {"de": de, "texto": corpo}
    return None


def extrair_status_whatsapp(payload: Any) -> StatusEntregaWhatsapp | None:
    """Resultado de entrega (sent/delivered/read/failed). Nunca devolve o
    recipient_id, que é o telefone. Um item null em `statuses` lança TypeError,
    como em develop (whatsapp.ts:115)."""
    for status in _primeiro_item_de_cada_change(payload, "statuses"):
        valor = _js.prop(status, "status")
        if not _js.verdadeiro(valor):
            continue
        erros = _js.prop(status, "errors")
        erro = AUSENTE if erros is None or erros is AUSENTE else _js.indice(erros, 0)
        saida: dict[str, Any] = {"status": valor}
        _js.definir(saida, "erroCodigo", _js.opt(erro, "code"))
        _js.definir(saida, "erroTitulo", _js.opt(erro, "title"))
        return saida  # type: ignore[return-value]
    return None
