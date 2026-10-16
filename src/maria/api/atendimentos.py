"""Criação de atendimento (develop: `rotas/atendimentos.ts` @ 1157a6d).

No PR 1 do módulo api entram só o núcleo `criar_atendimento`, que a rota do
orquestrador usa quando o relato converge para um fluxo, e a rota
`POST /atendimentos`. `GET /atendimentos/:chatId`, `POST /atendimentos/respostas`
e o TTL entram no PR 2 (spec 07, D-4).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from typing import Any

from maria.api import esquemas
from maria.api.pipeline import Contexto, LogRequisicao, Resposta, Rota
from maria.fluxos import ID_VIOLENCIA_DOMESTICA, FluxoConfig, buscar_fluxo
from maria.shared import _js
from maria.shared._js import AUSENTE
from maria.shared.atendimentos_db import ConclusaoAtendimento, obter_atendimentos_store


def destino_do_log(fluxo_id: str, status_final: Any) -> str | None:
    """Issue #92: `destino` só no log interno; "concluido" no log cobre handoff também."""
    if status_final == "handoff_humano":
        return "atendimento_humano"
    if status_final == "expirado":
        return "sessao_expirada"
    if fluxo_id == ID_VIOLENCIA_DOMESTICA:
        return "agendamento"
    return None


def montar_links(chat_id: str, status: str) -> dict[str, Any]:
    links: dict[str, Any] = {"self": {"href": f"/atendimentos/{chat_id}"}}
    if status == "em_andamento":
        links["responder"] = {"href": "/atendimentos/respostas", "method": "POST"}
    return links


def extrair_interrupt(resultado: Mapping[str, Any]) -> Any:
    """`__interrupt__?.[0]?.value`: None quando o grafo não pausou."""
    pendentes = resultado.get("__interrupt__") or []
    return pendentes[0].value if pendentes else None


def _dados_coletados(valores: Mapping[str, Any]) -> dict[str, Any]:
    # Decisão 2026-09-09: só cpf, e só quando é texto.
    cpf = valores.get("cpf")
    return {"cpf": cpf} if isinstance(cpf, str) else {}


def montar_resposta_atendimento(
    fluxo: FluxoConfig, fluxo_id: str, chat_id: str, interrupt: Any, valores: Mapping[str, Any]
) -> dict[str, Any]:
    """Mesmo corpo para criar, consultar e responder (`atendimentos.ts:194-242`)."""
    metadados = fluxo.extrair_metadados(valores)
    dados_coletados = _dados_coletados(valores)
    if interrupt is not None:
        return {
            "resposta": _js.opt(interrupt, "pergunta"),
            "tipoResposta": _js.opt(interrupt, "tipo"),
            "opcoes": _js.opt(interrupt, "opcoes"),
            "status": "em_andamento",
            "flowId": fluxo_id,
            "metadados": metadados,
            "dadosColetados": dados_coletados,
            "_links": montar_links(chat_id, "em_andamento"),
        }
    status = _js.coalesce(valores.get("statusFinal"), "concluido")
    padrao = fluxo.mensagem_concluido if status == "concluido" else fluxo.mensagem_handoff
    return {
        "resposta": _js.coalesce(valores.get("mensagemFinal"), padrao),
        "tipoResposta": "texto",
        "status": status,
        "flowId": fluxo_id,
        "metadados": metadados,
        "dadosColetados": dados_coletados,
        # {0,0,0}, e não ausente, quando nenhuma chamada de IA rodou (#35, #69, #92).
        "tokensGastos": _js.coalesce(valores.get("tokensGastos"), {"input": 0, "output": 0, "total": 0}),
        "_links": montar_links(chat_id, status),
    }


async def criar_atendimento(
    fluxo: FluxoConfig,
    fluxo_id: str,
    chat_id_corpo: Any,
    dados_conhecidos: Any,
    log: LogRequisicao,
    via_orquestrador: bool = False,
) -> Resposta:
    """Núcleo de "criar (ou retomar) um atendimento" (`atendimentos.ts:254-356`).

    `via_orquestrador` NUNCA vem de `dadosConhecidos` (#191): qualquer
    `viaOrquestrador` dentro dele é descartado.
    """
    # `!chatIdBody && NODE_ENV !== "test"`: "" também é ausente.
    if not _js.verdadeiro(chat_id_corpo) and os.environ.get("APP_ENV") != "test":
        return Resposta(400, {"erro": "chatId obrigatório"})
    chat_id_gerado = not _js.verdadeiro(chat_id_corpo)
    chat_id: str = str(uuid.uuid4()) if chat_id_gerado else chat_id_corpo
    if chat_id_gerado:
        log.warn("chatId ausente na requisição — gerado UUID (só permitido em NODE_ENV=test)", fluxoId=fluxo_id, chatId=chat_id)

    # Registra chatId→flowId ANTES de tocar no grafo: chatId de outro fluxo é 409.
    store = await obter_atendimentos_store()
    registro = await store.registrar(chat_id, fluxo_id)
    if not registro["ok"]:
        existente = registro["flowIdExistente"]
        log.warn("chatId já pertence a outro flowId", chatId=chat_id, fluxoId=fluxo_id, flowIdExistente=existente)
        return Resposta(409, {"erro": f"chatId já está em uso pelo flowId {existente}"})

    config: Any = {"configurable": {"thread_id": chat_id, "fluxoId": fluxo_id}}
    grafo = fluxo.obter_grafo()

    # Idempotente: chatId que já existe devolve o estado atual, sem invoke de novo
    # (invoke num thread existente reiniciaria o grafo; achado ao vivo 2026-08-31).
    estado = await grafo.aget_state(config)
    interrupt_anterior = next((i.value for t in estado.tasks for i in t.interrupts), None)
    valores_anteriores = dict(estado.values or {})
    if interrupt_anterior is not None or len(valores_anteriores) > 0:
        log.warn("POST em chatId que já existe — devolvendo estado atual, sem reiniciar", fluxoId=fluxo_id, chatId=chat_id)
        corpo = montar_resposta_atendimento(fluxo, fluxo_id, chat_id, interrupt_anterior, valores_anteriores)
        return Resposta(200, corpo, {"Location": f"/atendimentos/{chat_id}"})

    log.info("atendimento criado", fluxoId=fluxo_id, chatId=chat_id, evento="atendimento_criado")
    dados = {k: v for k, v in (dados_conhecidos if isinstance(dados_conhecidos, dict) else {}).items() if k != "viaOrquestrador"}
    resultado: dict[str, Any] = await grafo.ainvoke({**dados, "viaOrquestrador": via_orquestrador}, config)

    interrupt = extrair_interrupt(resultado)
    if interrupt is not None:
        log.info(
            "pergunta enviada",
            fluxoId=fluxo_id,
            chatId=chat_id,
            evento="pergunta_enviada",
            status="em_andamento",
            tipoResposta=_js.opt(interrupt, "tipo"),
            viaIA=_js.coalesce(resultado.get("perguntaAtualViaIA"), False),
            tokensGastosTotal=resultado.get("perguntaAtualTokensTotal"),
        )
    else:
        status_final = resultado.get("statusFinal")
        destino = destino_do_log(fluxo_id, status_final)
        log.info(
            "atendimento finalizado",
            fluxoId=fluxo_id,
            chatId=chat_id,
            evento="atendimento_finalizado",
            status="concluido",
            destino=destino,
            motivoHandoff=resultado.get("motivoHandoff"),
            tokensGastos=resultado.get("tokensGastos"),
        )
        if _js.verdadeiro(status_final):
            conclusao: dict[str, Any] = {"statusFinal": status_final}
            for chave, valor in (
                ("destino", destino),
                ("motivoHandoff", resultado.get("motivoHandoff")),
                ("tokensGastos", resultado.get("tokensGastos")),
            ):
                if valor is not None:
                    conclusao[chave] = valor
            await store.concluir(chat_id, ConclusaoAtendimento(**conclusao))  # type: ignore[typeddict-item]

    corpo = montar_resposta_atendimento(fluxo, fluxo_id, chat_id, interrupt, resultado)
    return Resposta(200, corpo, {"Location": f"/atendimentos/{chat_id}"})


async def _post_atendimentos(ctx: Contexto) -> Resposta:
    corpo: dict[str, Any] = ctx.corpo
    fluxo_id = corpo.get("flowId", AUSENTE)
    if not _js.verdadeiro(fluxo_id):
        return Resposta(400, {"erro": "flowId obrigatório"})
    fluxo = await buscar_fluxo(fluxo_id)
    if fluxo is None:
        return Resposta(404, {"erro": "fluxo não encontrado — ver GET /fluxos"})
    # 200, e não 201: a Tykhe só reconhece 200 como sucesso (pedido explícito).
    return await criar_atendimento(fluxo, fluxo_id, corpo.get("chatId", AUSENTE), corpo.get("dadosConhecidos", AUSENTE), ctx.log)


ROTAS: tuple[Rota, ...] = (
    Rota(
        "POST",
        "/atendimentos",
        _post_atendimentos,
        corpo=esquemas.CORPO_CRIAR_ATENDIMENTO,
        respostas={
            200: esquemas.RESPOSTA_ATENDIMENTO,
            400: esquemas.ERRO_ATENDIMENTOS,
            404: esquemas.ERRO_ATENDIMENTOS,
            409: esquemas.ERRO_ATENDIMENTOS,
        },
        resumo="Cria um atendimento novo (1ª pergunta do fluxo)",
        tags=("atendimentos",),
    ),
)
