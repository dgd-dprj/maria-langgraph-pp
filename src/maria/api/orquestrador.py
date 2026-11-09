"""POST /atendimentos/orquestrador (develop: `rotas/orquestrador.ts` @ 1157a6d, #28, #225).

Para quem não sabe de antemão qual `flowId` usar: manda um relato livre
(`mensagem`), o orquestrador classifica e, se converge para um fluxo da Maria,
cria o atendimento nele (`criar_atendimento`). Os tipos que a Tykhe atende
voltam como `redirecionado` + `tipoCaso`, sem criar atendimento. Enquanto
desambigua, a pessoa responde com `resposta` (não `mensagem`) nesta mesma rota.

O checkpoint do orquestrador usa o `thread_id` `orquestrador:<chatId>`, separado
do fluxo escolhido depois (que usa o `chatId` puro).
"""

from __future__ import annotations

import os
import uuid
from typing import Any, cast

from langgraph.types import Command

from maria.api import esquemas
from maria.api.atendimentos import criar_atendimento, extrair_interrupt
from maria.api.pipeline import Contexto, Resposta, Rota
from maria.fluxos import buscar_fluxo, fluxo_em_teste_liga
from maria.fluxos.tipos_tykhe import TipoCasoTykhe, TipoTykhe, tipo_tykhe_por_caso, tipo_tykhe_por_id
from maria.orquestrador.fila import (
    AssuntoPendente,
    chat_id_do_assunto,
    dados_do_relato,
    origem_do_chat,
    texto_comecando,
    texto_proximo_assunto,
)
from maria.orquestrador.graph import obter_grafo
from maria.shared import _js
from maria.shared._js import AUSENTE
from maria.shared.atendimentos_db import AtendimentosStore, obter_atendimentos_store

MENSAGEM_NAO_IDENTIFICADO = (
    "Não consegui identificar como te ajudar a partir do que você escreveu. "
    "Vou encaminhar seu atendimento pra um atendente humano confirmar."
)


def _resposta_redirecionada(chat_id: str, tipo: TipoTykhe, tokens_gastos: Any) -> dict[str, Any]:
    # #225: sem _links.responder, sem flowId e sem metadados; tokensGastos sempre presente.
    return {
        "resposta": tipo.mensagem,
        "tipoResposta": "texto",
        "status": "redirecionado",
        "tipoCaso": tipo.tipo_caso,
        "tokensGastos": _js.coalesce(tokens_gastos, {"input": 0, "output": 0, "total": 0}),
        "_links": {"self": {"href": f"/atendimentos/{chat_id}"}},
    }


def _resposta_handoff_sem_fluxo(chat_id: str) -> dict[str, Any]:
    return {
        "resposta": MENSAGEM_NAO_IDENTIFICADO,
        "tipoResposta": "texto",
        "status": "handoff_humano",
        "motivoHandoff": "nao_identificado",
        "_links": {"self": {"href": f"/atendimentos/{chat_id}"}},
    }


async def _retomar(grafo: Any, resposta: str, config: Any) -> dict[str, Any]:
    """`grafo.invoke(new Command({ resume }))` de develop.

    Sem pergunta pendente na thread (conversa que nunca existiu, ou que já
    terminou), o LangGraph JS não executa nada e devolve o estado como está: na
    rota, isso vira "não identificado" (fixture `orquestrador-resposta-sem-pendencia-200`).
    O LangGraph Python, com `Command(resume=…)` numa thread sem checkpoint, roda o
    grafo do começo. Achado na conferência contra as fixtures (#246)."""
    estado = await grafo.aget_state(config)
    if not estado.next:
        return dict(estado.values or {})
    resultado: dict[str, Any] = await grafo.ainvoke(Command(resume=resposta), config)
    return resultado


async def _post_orquestrador(ctx: Contexto) -> Resposta:
    corpo: dict[str, Any] = ctx.corpo
    mensagem = corpo.get("mensagem", AUSENTE)
    resposta = corpo.get("resposta", AUSENTE)
    # #185: resposta "" barrada ANTES do "algum dos dois", senão chegaria a Command(resume="").
    if resposta is not AUSENTE and resposta == "":
        return Resposta(400, {"erro": "resposta não pode ser vazia"})
    if mensagem is AUSENTE and resposta is AUSENTE:
        return Resposta(400, {"erro": "mensagem (1ª chamada) ou resposta (continuação de desambiguação) obrigatório"})

    chat_id_corpo = corpo.get("chatId", AUSENTE)
    if not _js.verdadeiro(chat_id_corpo) and os.environ.get("APP_ENV") != "test":
        return Resposta(400, {"erro": "chatId obrigatório"})
    chat_id: str = chat_id_corpo if _js.verdadeiro(chat_id_corpo) else str(uuid.uuid4())

    config: Any = {"configurable": {"thread_id": f"orquestrador:{chat_id}"}}
    grafo = obter_grafo()
    if resposta is not AUSENTE:
        resultado = await _retomar(grafo, resposta, config)
    else:
        entrada: dict[str, Any] = {"mensagem": _js.coalesce(mensagem, "")}
        conhecidos = corpo.get("dadosConhecidos")
        if isinstance(conhecidos, dict) and conhecidos:
            # #442: guardados para o fluxo aberto depois da desambiguação ou da pergunta da ordem.
            entrada["dadosConhecidos"] = conhecidos
        resultado = await grafo.ainvoke(entrada, config)

    tokens_rodada = resultado.get("tokensGastosRodada")
    tokens_conversa = resultado.get("tokensGastosConversa")
    rodada = resultado.get("rodada")

    interrupt = extrair_interrupt(resultado)
    if interrupt is not None:
        # #435: a pergunta da ordem dos assuntos ("ordem", "primeiro") sai com a etapa no log; a
        # desambiguação de sempre não tem etapa, e o log dela não muda.
        etapa = _js.opt(interrupt, "etapa")
        ctx.log.info(
            "orquestrador: pergunta de desambiguação enviada"
            if etapa is AUSENTE
            else "orquestrador: pergunta da ordem dos assuntos enviada",
            chatId=chat_id,
            evento="orquestrador_pergunta_enviada",
            status="em_andamento",
            tipoResposta=_js.opt(interrupt, "tipo"),
            tokensGastosTotal=tokens_rodada,
            rodada=rodada,
            **({} if etapa is AUSENTE else {"etapa": etapa}),
        )
        return Resposta(
            200,
            {
                "resposta": _js.opt(interrupt, "pergunta"),
                "tipoResposta": _js.opt(interrupt, "tipo"),
                "opcoes": _js.opt(interrupt, "opcoes"),
                "status": "em_andamento",
                "_links": {
                    "self": {"href": f"/atendimentos/{chat_id}"},
                    "responder": {"href": "/atendimentos/orquestrador", "method": "POST"},
                },
            },
        )

    status_final = resultado.get("statusFinal")
    flow_id: Any = resultado.get("flowIdEscolhido")
    # #435 (multi-fluxo, só no release): os outros assuntos do relato, para a Tykhe seguir com eles.
    pendentes = resultado.get("assuntosPendentes") or []
    no_log_pendentes = {"assuntosPendentes": len(pendentes)} if pendentes else {}

    # #225: relato que não bate com nenhuma opção vai para "outros" da Tykhe.
    if status_final != "identificado" or not _js.verdadeiro(flow_id):
        ctx.log.info(
            "orquestrador: fluxo não identificado, redirecionado para a Tykhe (outros)",
            chatId=chat_id,
            evento="orquestrador_finalizado_sem_fluxo",
            status="concluido",
            destino="tykhe",
            tipoCaso="outros",
            tokensGastosTotal=tokens_rodada,
            rodada=rodada,
            **no_log_pendentes,
        )
        return Resposta(200, _com_pendentes(_resposta_redirecionada(chat_id, tipo_tykhe_por_caso("outros"), tokens_conversa), pendentes))

    tipo = tipo_tykhe_por_id(flow_id)
    if tipo is not None:
        ctx.log.info(
            "orquestrador: caso de um tipo atendido pela Tykhe, redirecionado",
            chatId=chat_id,
            evento="orquestrador_redirecionado",
            status="concluido",
            destino="tykhe",
            tipoCaso=tipo.tipo_caso,
            tokensGastosTotal=tokens_rodada,
            rodada=rodada,
            **no_log_pendentes,
        )
        return Resposta(200, _com_pendentes(_resposta_redirecionada(chat_id, tipo, tokens_conversa), pendentes))

    fluxo = await buscar_fluxo(flow_id)
    if fluxo is None:
        # Não deveria acontecer: o id veio do catálogo. É inconsistência entre catálogos.
        ctx.log.error(
            "orquestrador: flowId identificado não existe em nenhum catálogo (inconsistência)",
            chatId=chat_id,
            flowId=flow_id,
            evento="orquestrador_inconsistencia",
            status="concluido",
            destino="atendimento_humano",
        )
        return Resposta(200, _resposta_handoff_sem_fluxo(chat_id))

    ctx.log.info(
        "orquestrador: fluxo identificado",
        chatId=chat_id,
        evento="orquestrador_fluxo_identificado",
        flowId=flow_id,
        tokensGastosTotal=tokens_rodada,
        rodada=rodada,
        **no_log_pendentes,
    )
    # O gasto da triagem vira o ponto de partida do acumulador do fluxo (#35).
    # #442: os dados da 1ª chamada, com o que vier nesta por cima (a Tykhe pode mandar de novo).
    guardados = resultado.get("dadosConhecidos")
    dados = {**(guardados if isinstance(guardados, dict) else {}), **(corpo.get("dadosConhecidos") or {})}
    dados["tokensGastos"] = _js.coalesce(tokens_conversa, {"input": 0, "output": 0, "total": 0})
    fila = resultado.get("fila") or []
    relato = _js.texto_template(resultado.get("mensagem", "")).strip()
    # #435: com vários assuntos, o fluxo recebe só o trecho do assunto dele, e não o relato
    # inteiro (achado do teste de 06/11: a "Situação" do e-mail ao NUDECON levava a pessoa presa junto).
    trecho = fila[0].get("evidencia", "").strip() if len(fila) >= 2 else ""
    if trecho:
        relato = trecho
    if fluxo.usa_relato:
        # #334: o relato só vem da triagem, num canal próprio; um `relato` em dadosConhecidos (da Tykhe) não vale.
        dados.pop("relato", None)
        if relato:
            dados["relato"] = relato
    # #438: o que o relato já diz entra nos dados do fluxo. Sem log próprio: os logs gravados de develop
    # (fixtures de contrato) seguem iguais, e o efeito aparece nas perguntas que o fluxo deixa de fazer.
    dados.update(dados_do_relato(flow_id, relato, dados))
    # viaOrquestrador como parâmetro, nunca dentro de dadosConhecidos (#191).
    resposta_fluxo = await criar_atendimento(fluxo, flow_id, chat_id, dados, ctx.log, via_orquestrador=True)
    if isinstance(resposta_fluxo.corpo, dict) and resposta_fluxo.status == 200:
        _com_pendentes(resposta_fluxo.corpo, pendentes)
        texto = resposta_fluxo.corpo.get("resposta")
        if resultado.get("ordemPerguntada") and fila and isinstance(texto, str):
            resposta_fluxo.corpo["resposta"] = f"{texto_comecando(fila[0])}\n\n{texto}"
    return resposta_fluxo


def _com_pendentes(corpo: dict[str, Any], pendentes: list[Any]) -> dict[str, Any]:
    """#435: `assuntosPendentes` só aparece quando há outro assunto. Sem ele, o corpo é o de sempre."""
    if pendentes:
        corpo["assuntosPendentes"] = pendentes
    return corpo


async def _cpf_da_conversa(origem: str, valores_orquestrador: dict[str, Any], total: int, store: AtendimentosStore) -> str | None:
    """#442/#450: o CPF já informado na conversa, para o próximo assunto não pedir de novo. Vem dos
    `dadosConhecidos` da 1ª chamada ou de um atendimento anterior da mesma conversa."""
    conhecidos = valores_orquestrador.get("dadosConhecidos")
    if isinstance(conhecidos, dict) and isinstance(conhecidos.get("cpf"), str) and conhecidos["cpf"]:
        return str(conhecidos["cpf"])
    for posicao in range(1, total + 1):
        chat = origem if posicao == 1 else chat_id_do_assunto(origem, posicao)
        flow_id = await store.buscar_flow_id(chat)
        fluxo = await buscar_fluxo(flow_id) if flow_id else None
        if fluxo is None:
            continue
        estado = await fluxo.obter_grafo().aget_state({"configurable": {"thread_id": chat, "fluxoId": flow_id}})
        cpf = (estado.values or {}).get("cpf")
        if isinstance(cpf, str) and cpf:
            return cpf
    return None


def _com_cpf(pendentes: list[AssuntoPendente], cpf: str | None) -> list[AssuntoPendente]:
    if not cpf:
        return pendentes
    return [{**p, "dadosConhecidos": {"cpf": cpf, **p.get("dadosConhecidos", {})}} if "flowId" in p else p for p in pendentes]


async def _post_proximo_assunto(ctx: Contexto) -> Resposta:
    """#450 (multi-fluxo, fase 1b, só no release): abre o próximo assunto pendente da conversa, com o
    `chatId` gerado pela Maria (`<chatId>-assunto-N`). A Tykhe só manda o `chatId` da conversa.

    Idempotente: um assunto da Maria já aberto e não encerrado volta como está; um encerrado é pulado.
    Um assunto da Tykhe (`tipoCaso`) é devolvido uma vez, como `redirecionado`, e fica marcado."""
    chat_id = ctx.corpo.get("chatId", AUSENTE)
    if not isinstance(chat_id, str) or not chat_id:
        return Resposta(400, {"erro": "chatId obrigatório"})
    if not fluxo_em_teste_liga():
        return Resposta(404, {"erro": "rota disponível só no ambiente de teste (release)"})
    origem, _ = origem_do_chat(chat_id)
    config: Any = {"configurable": {"thread_id": f"orquestrador:{origem}"}}
    grafo = obter_grafo()
    valores = dict((await grafo.aget_state(config)).values or {})
    pendentes: list[AssuntoPendente] = valores.get("assuntosPendentes") or []
    encaminhados = set(valores.get("assuntosEncaminhados") or [])
    store = await obter_atendimentos_store()
    cpf = await _cpf_da_conversa(origem, valores, len(pendentes) + 1, store) if pendentes else None

    for indice, item in enumerate(pendentes):
        posicao = indice + 2
        novo = chat_id_do_assunto(origem, posicao)
        restantes = _com_cpf(pendentes[indice + 1 :], cpf)
        tipo_caso = item.get("tipoCaso")
        if tipo_caso is not None:
            if posicao in encaminhados:
                continue
            await grafo.aupdate_state(config, {"assuntosEncaminhados": sorted(encaminhados | {posicao})})
            ctx.log.info(
                "orquestrador: próximo assunto é da Tykhe, redirecionado",
                chatId=novo,
                evento="proximo_assunto_redirecionado",
                tipoCaso=tipo_caso,
                posicao=posicao,
            )
            corpo = _resposta_redirecionada(novo, tipo_tykhe_por_caso(cast(TipoCasoTykhe, tipo_caso)), None)
            corpo["chatId"] = novo
            return Resposta(200, _com_pendentes(corpo, restantes))

        flow_id = item.get("flowId")
        atividade = await store.buscar_atividade(novo)
        if atividade is not None and atividade.get("statusFinal"):
            continue  # já encerrado (concluído, atendimento humano ou expirado)
        fluxo = await buscar_fluxo(flow_id) if flow_id else None
        if fluxo is None or flow_id is None:
            continue
        novo_agora = atividade is None
        dados: dict[str, Any] = dict(item.get("dadosConhecidos") or {})
        if cpf and "cpf" not in dados:
            dados["cpf"] = cpf
        if novo_agora:
            ctx.log.info(
                "orquestrador: próximo assunto aberto",
                chatId=novo,
                evento="proximo_assunto_aberto",
                flowId=flow_id,
                posicao=posicao,
            )
        resposta_fluxo = await criar_atendimento(fluxo, flow_id, novo, dados, ctx.log, via_orquestrador=True)
        if isinstance(resposta_fluxo.corpo, dict) and resposta_fluxo.status == 200:
            texto = resposta_fluxo.corpo.get("resposta")
            if novo_agora and isinstance(texto, str):
                resposta_fluxo.corpo["resposta"] = f"{texto_proximo_assunto(item)}\n\n{texto}"
            resposta_fluxo.corpo["chatId"] = novo
            _com_pendentes(resposta_fluxo.corpo, restantes)
        return resposta_fluxo

    return Resposta(404, {"erro": "nenhum assunto pendente nesta conversa"})


ROTAS: tuple[Rota, ...] = (
    Rota(
        "POST",
        "/atendimentos/orquestrador",
        _post_orquestrador,
        corpo=esquemas.CORPO_ORQUESTRADOR,
        respostas={
            200: esquemas.RESPOSTA_ORQUESTRADOR,
            400: esquemas.ERRO_ORQUESTRADOR,
            409: esquemas.ERRO_ORQUESTRADOR,
        },
        resumo=(
            "Cria um atendimento identificando o fluxo automaticamente a partir de um relato livre "
            "(com possíveis perguntas de desambiguação antes)"
        ),
        tags=("atendimentos",),
    ),
    Rota(
        "POST",
        "/atendimentos/proximo-assunto",
        _post_proximo_assunto,
        corpo=esquemas.CORPO_PROXIMO_ASSUNTO,
        respostas={
            200: esquemas.RESPOSTA_PROXIMO_ASSUNTO,
            400: esquemas.ERRO_ORQUESTRADOR,
            404: esquemas.ERRO_ORQUESTRADOR,
            409: esquemas.ERRO_ORQUESTRADOR,
        },
        resumo="Abre o próximo assunto pendente da conversa, com o chatId gerado pela Maria (multi-fluxo, só no release)",
        tags=("atendimentos",),
    ),
)
