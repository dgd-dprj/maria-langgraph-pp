"""Rotas de atendimento (develop: `rotas/atendimentos.ts` @ 1157a6d).

`POST /atendimentos` e o núcleo `criar_atendimento`, que a rota do orquestrador
usa, entraram no PR 1 do módulo api. `GET /atendimentos/:chatId` e
`POST /atendimentos/respostas`, com o TTL de inatividade (#166, #227, #234),
entram no PR 2 (spec 07, D-4).
"""

from __future__ import annotations

import math
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

from langgraph.types import Command

from maria.api import esquemas
from maria.api.pipeline import Contexto, LogRequisicao, Resposta, Rota
from maria.fluxos import ID_VIOLENCIA_DOMESTICA, FluxoConfig, buscar_fluxo
from maria.shared import _js
from maria.shared._js import AUSENTE, numero_js
from maria.shared.atendimentos_db import ConclusaoAtendimento, obter_atendimentos_store
from maria.shared.respostas import normalizar_resposta, resposta_eh_nao, resposta_eh_sim

# Formas naturais de responder à confirmação de TTL além de sim/não (#227), já
# normalizadas (sem acento, minúsculas: ver normalizar_resposta).
CONTINUAR_TTL = frozenset(("quero", "continuar", "quero continuar", "continua", "pode continuar"))
RECOMECAR_TTL = frozenset(("recomecar", "quero recomecar", "comecar de novo", "nao quero"))
TEXTO_CONFIRMACAO_TTL = "Já faz um tempo desde sua última mensagem. Quer continuar de onde você parou?"
MENSAGEM_EXPIRADO = "Essa conversa expirou por inatividade. Pra continuar, inicie um novo atendimento."
# #270: atendimento registrado cujo checkpoint não existe mais (no corte da migração,
# todas as conversas em andamento). Não é inatividade, por isso o texto é outro.
MENSAGEM_CONVERSA_SEM_CHECKPOINT = "Não consegui continuar essa conversa de onde ela parou. Pra seguir, inicie um novo atendimento."


class EmptyInputError(Exception):
    """O erro do LangGraph JS para `new Command({ resume: "" })` (`pregel/loop.js:663`).

    Decisão D-2 (spec 07): o LangGraph Python aceita `resume=""` e retoma o grafo
    com uma resposta vazia, que numa pergunta sim/não conta como "não", sem
    nenhum sinal. Develop responde 500. A guarda reproduz o 500, com a mesma
    mensagem e o mesmo `name` no log."""

    campos_log_js: ClassVar[dict[str, str]] = {"name": "EmptyInputError"}

    def __init__(self) -> None:
        super().__init__("Received empty Command input")


def ttl_inatividade_horas() -> float:
    """`Number(process.env.TTL_INATIVIDADE_HORAS ?? "24")`, lido a cada requisição:
    "abc" é NaN (o TTL nunca dispara) e "" é 0 (dispara sempre), como no JS."""
    return numero_js(os.environ.get("TTL_INATIVIDADE_HORAS", "24"))


def _arredondar_js(valor: float) -> int:
    # Math.round do JS: meio arredonda para cima (o round do Python vai para o par).
    return math.floor(valor + 0.5)


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
    await _registrar_rodada(fluxo_id, chat_id, interrupt, resultado, log)
    corpo = montar_resposta_atendimento(fluxo, fluxo_id, chat_id, interrupt, resultado)
    return Resposta(200, corpo, {"Location": f"/atendimentos/{chat_id}"})


async def _registrar_rodada(fluxo_id: str, chat_id: str, interrupt: Any, resultado: Mapping[str, Any], log: LogRequisicao) -> None:
    """Log da pergunta enviada ou do desfecho e, no desfecho, a gravação em
    `atendimentos` (#83, #90, #92). Mesmo trecho na criação e na resposta."""
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
        return
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
        store = await obter_atendimentos_store()
        await store.concluir(chat_id, ConclusaoAtendimento(**conclusao))  # type: ignore[typeddict-item]


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


async def _fluxo_do_chat(chat_id: Any) -> tuple[FluxoConfig, str] | Resposta:
    """flowId pela tabela `atendimentos` (o chatId basta; decisão de 2026-09-02)."""
    store = await obter_atendimentos_store()
    fluxo_id = await store.buscar_flow_id(chat_id)
    if not _js.verdadeiro(fluxo_id):
        return Resposta(404, {"erro": "atendimento não encontrado"})
    assert fluxo_id is not None
    fluxo = await buscar_fluxo(fluxo_id)
    if fluxo is None:
        return Resposta(404, {"erro": "fluxo não encontrado — ver GET /fluxos"})
    return fluxo, fluxo_id


async def _get_atendimento(ctx: Contexto) -> Resposta:
    """`GET /atendimentos/:chatId`: lê o checkpoint, sem avançar o fluxo."""
    chat_id = ctx.parametros["chatId"]
    achado = await _fluxo_do_chat(chat_id)
    if isinstance(achado, Resposta):
        return achado
    fluxo, fluxo_id = achado
    # fluxoId no configurable: é ele que correlaciona os logs de dentro dos nós.
    config: Any = {"configurable": {"thread_id": chat_id, "fluxoId": fluxo_id}}
    estado = await fluxo.obter_grafo().aget_state(config)
    # `estado.tasks?.[0]?.interrupts?.[0]?.value`: só a primeira tarefa.
    interrupt = estado.tasks[0].interrupts[0].value if estado.tasks and estado.tasks[0].interrupts else None
    valores = dict(estado.values or {})
    if not _js.verdadeiro(interrupt) and len(valores) == 0:
        return Resposta(404, {"erro": "atendimento não encontrado"})
    return Resposta(200, montar_resposta_atendimento(fluxo, fluxo_id, chat_id, interrupt, valores))


def _expirado(
    fluxo: FluxoConfig, fluxo_id: str, chat_id: str, valores: Mapping[str, Any], mensagem: str = MENSAGEM_EXPIRADO
) -> dict[str, Any]:
    return montar_resposta_atendimento(fluxo, fluxo_id, chat_id, None, {**valores, "statusFinal": "expirado", "mensagemFinal": mensagem})


async def _post_respostas(ctx: Contexto) -> Resposta:
    """`POST /atendimentos/respostas`: avança o fluxo, com o TTL de inatividade
    checado antes de tocar no grafo (#166). O checkpoint nunca sabe de
    "expirado": isso é só controle da tabela `atendimentos`."""
    corpo: dict[str, Any] = ctx.corpo
    chat_id = corpo.get("chatId", AUSENTE)
    if not _js.verdadeiro(chat_id):
        return Resposta(400, {"erro": "chatId obrigatório"})
    resposta = corpo.get("resposta", AUSENTE)
    # #185: resposta vazia viraria Command(resume="") lá embaixo.
    if not _js.verdadeiro(resposta):
        return Resposta(400, {"erro": "resposta obrigatório"})
    achado = await _fluxo_do_chat(chat_id)
    if isinstance(achado, Resposta):
        return achado
    fluxo, fluxo_id = achado
    store = await obter_atendimentos_store()

    config: Any = {"configurable": {"thread_id": chat_id, "fluxoId": fluxo_id}}
    grafo = fluxo.obter_grafo()
    estado_anterior = await grafo.aget_state(config)
    retomando = len(estado_anterior.next or ()) > 0
    valores_atuais = dict(estado_anterior.values or {})

    async def processar(texto: str) -> Resposta:
        # A resposta vai como texto cru: nos sim_nao, a Tykhe manda "true"/"false".
        if texto == "":
            raise EmptyInputError()
        resultado: dict[str, Any] = await grafo.ainvoke(Command(resume=texto), config)
        await store.marcar_atividade(chat_id)
        interrupt = extrair_interrupt(resultado)
        await _registrar_rodada(fluxo_id, chat_id, interrupt, resultado, ctx.log)
        return Resposta(200, montar_resposta_atendimento(fluxo, fluxo_id, chat_id, interrupt, resultado))

    atividade = await store.buscar_atividade(chat_id)
    if atividade is not None and atividade.get("statusFinal") == "expirado":
        erro = {"erro": "atendimento expirado por inatividade — inicie um novo atendimento"}
        return Resposta(409, {**erro, **_expirado(fluxo, fluxo_id, chat_id, valores_atuais)})

    # Resposta à pergunta "quer continuar?", e não à pergunta de negócio.
    if atividade is not None and atividade["aguardandoConfirmacaoTtl"]:
        # #227: a tolerância dos nós sim_nao, mais as formas naturais desta pergunta.
        quis_continuar = resposta_eh_sim(resposta) or normalizar_resposta(resposta) in CONTINUAR_TTL
        quis_recomecar = resposta_eh_nao(resposta) or normalizar_resposta(resposta) in RECOMECAR_TTL
        if not quis_continuar and not quis_recomecar:
            # Nem sim nem não: pergunta de novo, sem expirar e sem perder a resposta guardada.
            ctx.log.info(
                "resposta à confirmação de TTL não reconhecida — perguntando de novo",
                fluxoId=fluxo_id,
                chatId=chat_id,
                evento="ttl_confirmacao_repetida",
            )
            pergunta = {"pergunta": TEXTO_CONFIRMACAO_TTL, "tipo": "sim_nao"}
            return Resposta(200, montar_resposta_atendimento(fluxo, fluxo_id, chat_id, pergunta, valores_atuais))
        if quis_recomecar:
            destino = destino_do_log(fluxo_id, "expirado")
            conclusao: ConclusaoAtendimento = {"statusFinal": "expirado"}
            if destino is not None:
                conclusao["destino"] = destino
            await store.concluir(chat_id, conclusao)
            ctx.log.info(
                "atendimento marcado como expirado — pessoa optou por recomeçar",
                fluxoId=fluxo_id,
                chatId=chat_id,
                evento="atendimento_expirado",
            )
            return Resposta(200, _expirado(fluxo, fluxo_id, chat_id, valores_atuais))
        # Continuar: processa a resposta ORIGINAL guardada quando a confirmação foi pedida.
        original = _js.coalesce(await store.resolver_confirmacao_ttl_continuar(chat_id), "")
        ctx.log.info("resposta recebida (retomada após confirmação de TTL)", fluxoId=fluxo_id, chatId=chat_id, evento="resposta_recebida")
        return await processar(original)

    if not retomando and len(valores_atuais) == 0:
        # #270 (melhoria sobre develop, decisão 3 do corte, #268): o atendimento existe
        # na tabela, mas o checkpoint não. Sem esta guarda, o estado vazio virava
        # "concluido" com a mensagem de sucesso do fluxo ("Já confirmei os dados…"),
        # sem que nada tivesse acontecido. Develop responde igual (controle executado
        # em 2026-10-21): é herdado, e o corte o faria acontecer com toda conversa em
        # andamento. Reaproveita a resposta de expirado do TTL: 409, status expirado.
        destino_sem_checkpoint = destino_do_log(fluxo_id, "expirado")
        conclusao_sem_checkpoint: ConclusaoAtendimento = {"statusFinal": "expirado"}
        if destino_sem_checkpoint is not None:
            conclusao_sem_checkpoint["destino"] = destino_sem_checkpoint
        await store.concluir(chat_id, conclusao_sem_checkpoint)
        ctx.log.warn(
            "atendimento sem checkpoint — a conversa não continua, tratado como expirado",
            fluxoId=fluxo_id,
            chatId=chat_id,
            evento="atendimento_sem_checkpoint",
        )
        erro = {"erro": "atendimento sem conversa em andamento — inicie um novo atendimento"}
        return Resposta(409, {**erro, **_expirado(fluxo, fluxo_id, chat_id, valores_atuais, MENSAGEM_CONVERSA_SEM_CHECKPOINT)})

    if not retomando:
        # Já concluiu: 409 com os dados coletados, como um GET.
        erro = {"erro": "atendimento já foi concluído — nada esperando resposta"}
        return Resposta(409, {**erro, **montar_resposta_atendimento(fluxo, fluxo_id, chat_id, None, valores_atuais)})

    # Passou o TTL desde a última atividade: pergunta antes, guardando a resposta.
    horas_inativo = (datetime.now(UTC) - atividade["atualizadoEm"]).total_seconds() / 3600 if atividade is not None else 0.0
    if horas_inativo > ttl_inatividade_horas():
        await store.marcar_aguardando_confirmacao_ttl(chat_id, resposta)
        ctx.log.info(
            "TTL de inatividade excedido — perguntando se quer continuar",
            fluxoId=fluxo_id,
            chatId=chat_id,
            evento="ttl_confirmacao_solicitada",
            horasInativo=_arredondar_js(horas_inativo),
        )
        pergunta = {"pergunta": TEXTO_CONFIRMACAO_TTL, "tipo": "sim_nao"}
        return Resposta(200, montar_resposta_atendimento(fluxo, fluxo_id, chat_id, pergunta, valores_atuais))

    ctx.log.info("resposta recebida", fluxoId=fluxo_id, chatId=chat_id, evento="resposta_recebida")
    return await processar(resposta)


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
    Rota(
        "GET",
        "/atendimentos/:chatId",
        _get_atendimento,
        respostas={200: esquemas.RESPOSTA_ATENDIMENTO, 404: esquemas.ERRO_ATENDIMENTOS},
        resumo="Consulta o estado atual (sem avançar o fluxo)",
        tags=("atendimentos",),
    ),
    Rota(
        "POST",
        "/atendimentos/respostas",
        _post_respostas,
        corpo=esquemas.CORPO_RESPOSTAS,
        respostas={
            200: esquemas.RESPOSTA_ATENDIMENTO,
            400: esquemas.ERRO_ATENDIMENTOS,
            404: esquemas.ERRO_ATENDIMENTOS,
            409: esquemas.ERRO_ATENDIMENTOS,
        },
        resumo="Envia uma resposta, avança o fluxo pra próxima pergunta (ou conclui)",
        tags=("atendimentos",),
    ),
)
