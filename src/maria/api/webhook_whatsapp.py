"""Bridge do WhatsApp (develop: `rotas/webhookWhatsapp.ts` @ 1157a6d; #198, #203, #225).

Integração separada da Tykhe: a Meta chama o webhook, e o bridge fala só com
`POST /atendimentos/orquestrador` e `POST /atendimentos/respostas`, por chamada
interna em processo (o `app.inject` de develop), pelo pipeline inteiro.

Público, fora do Bearer: quem chama é a Meta. A autenticação é o `verify_token`
da verificação inicial (`GET`).

Estado em memória por número, como em develop: o `chatId` aberto de cada número
e a fila que processa em série as mensagens de um mesmo número. Some no
restart, e a mensagem seguinte abre um atendimento novo. Depende de um único
worker (`main.py`).

Reproduzido de develop (spec 07, achados A1 e A2): o telefone vai no `chatId`
(`whatsapp:<número>:<timestamp>`), e daí para os logs e para a tabela
`atendimentos`; só existe em release, com números de teste.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, ClassVar

from maria.api.pipeline import Contexto, ErroFastify, Resposta, RespostaInjetada, Rota
from maria.integracoes.whatsapp import enviar_mensagem_whatsapp, extrair_mensagem_whatsapp, extrair_status_whatsapp
from maria.orquestrador.graph import obter_grafo as obter_grafo_orquestrador
from maria.shared import _js
from maria.shared._js import trim_js
from maria.shared.atendimentos_db import obter_atendimentos_store

PALAVRA_CHAVE_SAIR = "#sair"
MENSAGEM_SAIU = "Conversa encerrada. Pode mandar uma mensagem nova quando quiser."
# #225: no bridge não há Tykhe para continuar os tipos de caso que ela atende.
MENSAGEM_REDIRECIONADO = (
    "Esse assunto é atendido pelo aplicativo Defensoria RJ ou pelo telefone 129 (ligação gratuita). "
    "Por lá a equipe continua o seu atendimento."
)
MENSAGEM_NADA_PARA_SAIR = "Você não tem nenhuma conversa em andamento. Pode mandar uma mensagem pra começar."
MENSAGEM_FALHA = "Desculpa, tive um problema pra processar sua mensagem. Tenta de novo em instantes."

# Número → chatId da conversa em aberto. Invalidado quando o atendimento conclui,
# para a próxima mensagem do número abrir uma conversa nova (code review da #198).
_conversas_ativas: dict[str, str] = {}
# Número → trava: duas mensagens quase simultâneas do mesmo número (retry do
# webhook da Meta) não podem ler o mesmo estado do grafo antes de a primeira gravar.
_travas: dict[str, asyncio.Lock] = {}


def chat_id_ativo_de_teste(numero: str) -> str | None:
    """`_chatIdAtivoDeTeste` de develop."""
    return _conversas_ativas.get(numero)


def limpar_conversas_ativas_de_teste() -> None:
    """`_limparConversasAtivasDeTeste` de develop."""
    _conversas_ativas.clear()
    _travas.clear()


class _ErroNode(TypeError):
    """O TypeError [ERR_INVALID_ARG_TYPE] do Node: no log, `type` TypeError e o `code`."""

    campos_log_js: ClassVar[dict[str, str]] = {"code": "ERR_INVALID_ARG_TYPE"}

    def __repr__(self) -> str:  # pragma: no cover
        return f"TypeError({self.args[0]!r})"


def _obter_chat_id_ativo(numero: str) -> str:
    existente = _conversas_ativas.get(numero)
    if existente:
        return existente
    novo = f"whatsapp:{numero}:{int(time.time() * 1000)}"
    _conversas_ativas[numero] = novo
    return novo


def montar_texto_resposta(corpo: Any) -> str:
    if not _js.verdadeiro(_js.opt(corpo, "resposta")):
        return MENSAGEM_FALHA
    # `corpo.opcoes?.length`: a rota só devolve lista (ou nada) em `opcoes`.
    opcoes = _js.prop(corpo, "opcoes")
    if _js.prop(corpo, "tipoResposta") in ("opcoes", "sim_nao") and isinstance(opcoes, list) and len(opcoes) > 0:
        return f"{_js.texto_template(corpo['resposta'])}\n\n" + "\n".join(f"- {_js.texto_template(o)}" for o in opcoes)
    return _js.texto_template(corpo["resposta"])


async def _get_webhook(ctx: Contexto) -> Resposta:
    modo = ctx.consulta.get("hub.mode")
    token = ctx.consulta.get("hub.verify_token")
    challenge = ctx.consulta.get("hub.challenge")
    # Lido a cada requisição, como em develop.
    verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if verify_token and modo == "subscribe" and token == verify_token:
        desafio = _js.coalesce(challenge, "")
        if not isinstance(desafio, str):
            # `hub.challenge` repetido vira lista, e `reply.send(lista)` com o tipo
            # text/plain falha: no GET, o Fastify recusa o payload; no HEAD, o erro
            # vem do Node ao calcular o tamanho (executado em develop @ 1157a6d).
            if ctx.metodo == "HEAD":
                raise _ErroNode(
                    'The "string" argument must be of type string or an instance of Buffer or ArrayBuffer. Received an instance of Array'
                )
            raise ErroFastify(
                500, "FST_ERR_REP_INVALID_PAYLOAD_TYPE", "Attempted to send payload of invalid type 'object'. Expected a string or Buffer."
            )
        return Resposta(200, None, texto=desafio, content_type="text/plain")
    return Resposta(403, None, texto="", content_type=None)


async def _post_webhook(ctx: Contexto) -> Resposta:
    mensagem = extrair_mensagem_whatsapp(ctx.corpo)
    if mensagem is None:
        # Status de entrega ou tipo não suportado: fora de escopo da v1 (#198), mas
        # o status de entrega vai para o log (diagnóstico de 2026-09-30).
        status = extrair_status_whatsapp(ctx.corpo)
        if status is not None:
            ctx.log.info(
                "[whatsapp] status de entrega recebido",
                evento="whatsapp_status_entrega",
                status=status["status"],
                erroCodigo=status.get("erroCodigo"),
                erroTitulo=status.get("erroTitulo"),
            )
        return Resposta(200, None, texto='{"ok":true}')

    trava = _travas.setdefault(mensagem["de"], asyncio.Lock())
    async with trava:
        await _processar(ctx, mensagem["de"], mensagem["texto"])
    return Resposta(200, None, texto='{"ok":true}')


async def _processar(ctx: Contexto, de: str, texto: str) -> None:
    assert ctx.injetar is not None
    if not isinstance(texto, str):
        # `text.body` que não é texto (número, por exemplo): o `.trim()` de develop lança.
        raise TypeError("mensagem.texto.trim is not a function")
    # "#sair": único jeito de encerrar uma conversa no meio. Reaproveita o
    # statusFinal "expirado" do TTL, com destino próprio ("saida_manual").
    if trim_js(texto).lower() == PALAVRA_CHAVE_SAIR:
        chat_id_ativo = _conversas_ativas.get(de)
        if not chat_id_ativo:
            await enviar_mensagem_whatsapp(de, MENSAGEM_NADA_PARA_SAIR, "whatsapp:sem-conversa-ativa")
            return
        store_saida = await obter_atendimentos_store()
        # Antes de o orquestrador convergir para um fluxo não há atendimento a concluir.
        if _js.verdadeiro(await store_saida.buscar_flow_id(chat_id_ativo)):
            await store_saida.concluir(chat_id_ativo, {"statusFinal": "expirado", "destino": "saida_manual"})
        _conversas_ativas.pop(de, None)
        await enviar_mensagem_whatsapp(de, MENSAGEM_SAIU, chat_id_ativo)
        return

    chat_id = _obter_chat_id_ativo(de)
    store = await obter_atendimentos_store()
    flow_id_existente = await store.buscar_flow_id(chat_id)
    autorizacao = {"authorization": f"Bearer {ctx.chave_api}"}

    resposta_injetada: RespostaInjetada
    if _js.verdadeiro(flow_id_existente):
        resposta_injetada = await ctx.injetar("POST", "/atendimentos/respostas", autorizacao, {"chatId": chat_id, "resposta": texto})
    else:
        # Sem atendimento: 1ª mensagem, ou resposta a uma desambiguação do próprio
        # orquestrador, que o estado do grafo dele (`orquestrador:<chatId>`) resolve.
        estado = await obter_grafo_orquestrador().aget_state({"configurable": {"thread_id": f"orquestrador:{chat_id}"}})
        aguardando = len(estado.next or ()) > 0
        corpo_interno = {"chatId": chat_id, "resposta": texto} if aguardando else {"chatId": chat_id, "mensagem": texto}
        resposta_injetada = await ctx.injetar("POST", "/atendimentos/orquestrador", autorizacao, corpo_interno)

    if resposta_injetada.status != 200:
        ctx.log.error(
            "[whatsapp] chamada interna ao atendimento falhou",
            chatId=chat_id,
            status=resposta_injetada.status,
            evento="whatsapp_bridge_erro",
        )

    corpo = resposta_injetada.json()
    status = _js.prop(corpo, "status")
    # Conversa acabou (ou erro): a próxima mensagem do número abre atendimento novo.
    if resposta_injetada.status != 200 or status != "em_andamento":
        _conversas_ativas.pop(de, None)

    if status == "redirecionado":
        mensagem = MENSAGEM_SAIU if _js.prop(corpo, "tipoCaso") == "sair" else MENSAGEM_REDIRECIONADO
    else:
        mensagem = montar_texto_resposta(corpo)
    await enviar_mensagem_whatsapp(de, mensagem, chat_id)


ROTAS: tuple[Rota, ...] = (
    Rota("GET", "/webhook/whatsapp", _get_webhook, protegida=False),
    Rota("POST", "/webhook/whatsapp", _post_webhook, protegida=False),
)
