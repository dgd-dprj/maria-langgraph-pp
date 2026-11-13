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

import asyncio
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
    NAO_RETOMA,
    TEXTO_ASSUNTO_NOVO,
    TEXTO_ENCERRADA,
    TEXTO_ENCERRADA_GUARDADOS,
    TEXTO_SEM_ABERTOS,
    AssuntoAberto,
    AssuntoGuardado,
    AssuntoPendente,
    chat_do_assunto_pelo_id,
    chat_id_do_assunto,
    dados_do_relato,
    escolha_nos_abertos,
    id_do_assunto,
    opcoes_abertos,
    origem_do_chat,
    para_a_tykhe,
    texto_abertos,
    texto_comecando,
    texto_proximo_assunto,
    texto_retomada,
)
from maria.orquestrador.graph import assuntos_em_aberto, obter_grafo, usuario_do_chat
from maria.shared import _js
from maria.shared._js import AUSENTE
from maria.shared.atendimentos_db import AtendimentosStore, obter_atendimentos_store
from maria.shared.pendentes_db import Situacao, obter_pendentes_store

MENSAGEM_NAO_IDENTIFICADO = (
    "Não consegui identificar como te ajudar a partir do que você escreveu. "
    "Vou encaminhar seu atendimento pra um atendente humano confirmar."
)

# As perguntas do multi-fluxo (só no release) saem com a etapa no log. A desambiguação de sempre não tem etapa, e o
# log dela não muda. Nunca o conteúdo da pergunta.
MENSAGENS_DE_LOG_POR_ETAPA: dict[str, str] = {
    "ordem": "orquestrador: pergunta da ordem dos assuntos enviada",
    "primeiro": "orquestrador: pergunta da ordem dos assuntos enviada",
    "pendentes": "orquestrador: pergunta dos assuntos guardados enviada",
    "assuntoNovo": "orquestrador: pedido de assunto novo enviado",
}

# #450: um id da Tykhe maior que isto não é um id; é ignorado, como se não tivesse vindo.
TAMANHO_MAXIMO_ID_USUARIO = 200


def id_usuario_do_corpo(corpo: dict[str, Any]) -> str | None:
    """#450 (decisão da Nicole, 2026-11-10): o `idUsuario` da Tykhe, como texto. Aceita número (o id pode vir como
    número no JSON). Vazio, de outro tipo ou grande demais: None, e a conversa segue sem guardar os pendentes."""
    valor = corpo.get("idUsuario")
    if isinstance(valor, int) and not isinstance(valor, bool):
        valor = str(valor)
    if not isinstance(valor, str):
        return None
    valor = valor.strip()
    return valor if 0 < len(valor) <= TAMANHO_MAXIMO_ID_USUARIO else None


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
        id_usuario = id_usuario_do_corpo(corpo)
        if id_usuario is not None and fluxo_em_teste_liga():
            # #450: a chave dos assuntos guardados. Só no release, e nunca no log.
            entrada["idUsuario"] = id_usuario
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
            MENSAGENS_DE_LOG_POR_ETAPA.get(etapa, "orquestrador: pergunta da ordem dos assuntos enviada")
            if isinstance(etapa, str)
            else "orquestrador: pergunta de desambiguação enviada",
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
    if fluxo_em_teste_liga():
        # #450: os outros assuntos ficam guardados pelo idUsuario, para quando a pessoa voltar.
        await _guardar_pendentes(resultado, chat_id, pendentes)
        escolhido = resultado.get("pendenteEscolhido")
        if isinstance(escolhido, dict):
            return await _atender_assunto_guardado(ctx, chat_id, cast(AssuntoGuardado, escolhido), resultado, pendentes)
    # #450 (2026-11-11): o que a pessoa contou é um assunto que já estava guardado? A Maria retoma esse, sem abrir outro.
    retomado = _guardado_do_mesmo_assunto(resultado, flow_id) if fluxo_em_teste_liga() and status_final == "identificado" else None

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
        if retomado is not None:
            await _registrar_retomada(ctx, chat_id, retomado, "resolvido")
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
    novo_agora = retomado is not None and await (await obter_atendimentos_store()).buscar_atividade(chat_id) is None
    # viaOrquestrador como parâmetro, nunca dentro de dadosConhecidos (#191).
    resposta_fluxo = await criar_atendimento(fluxo, flow_id, chat_id, dados, ctx.log, via_orquestrador=True)
    if isinstance(resposta_fluxo.corpo, dict) and resposta_fluxo.status == 200:
        _com_pendentes(resposta_fluxo.corpo, pendentes)
        texto = resposta_fluxo.corpo.get("resposta")
        if retomado is not None and novo_agora:
            situacao: Situacao = "em_andamento" if resposta_fluxo.corpo.get("status") == "em_andamento" else "resolvido"
            await _registrar_retomada(ctx, chat_id, retomado, situacao)
            # O fim do fluxo marca o guardado como resolvido (assunto_guardado_do_chat).
            await grafo.aupdate_state(config, {"assuntoResgatado": retomado})
            if isinstance(texto, str):
                resposta_fluxo.corpo["resposta"] = f"{texto_retomada(retomado)}\n\n{texto}"
        elif resultado.get("ordemPerguntada") and fila and isinstance(texto, str):
            resposta_fluxo.corpo["resposta"] = f"{texto_comecando(fila[0])}\n\n{texto}"
    return resposta_fluxo


def _guardado_do_mesmo_assunto(resultado: dict[str, Any], flow_id: Any) -> AssuntoGuardado | None:
    """O assunto guardado do mesmo tipo que o identificado agora (o mais urgente, se houver mais de um). "Outros" e
    "sair" não se retomam: não dizem qual era o assunto."""
    if not isinstance(flow_id, str) or flow_id in NAO_RETOMA:
        return None
    for guardado in resultado.get("pendentesGuardados") or []:
        if isinstance(guardado, dict) and id_do_assunto(guardado) == flow_id:
            return cast(AssuntoGuardado, guardado)
    return None


async def _registrar_retomada(ctx: Contexto, chat_id: str, retomado: AssuntoGuardado, situacao: Situacao) -> None:
    await (await obter_pendentes_store()).marcar(chat_id_do_assunto(retomado["chatIdOrigem"], retomado["posicao"]), situacao)
    ctx.log.info(
        "orquestrador: assunto guardado retomado",
        chatId=chat_id,
        evento="assunto_guardado_retomado",
        **({"flowId": retomado["flowId"]} if "flowId" in retomado else {"tipoCaso": retomado.get("tipoCaso")}),
    )


async def _guardar_pendentes(resultado: dict[str, Any], chat_id: str, pendentes: list[AssuntoPendente]) -> None:
    """#450: com o `idUsuario` da Tykhe, os outros assuntos da conversa ficam guardados por 30 dias. Sem ele, nada é
    guardado. Idempotente: chamar de novo não duplica."""
    id_usuario = resultado.get("idUsuario")
    if not pendentes or not isinstance(id_usuario, str) or not id_usuario:
        return
    store = await obter_pendentes_store()
    await store.guardar(id_usuario, chat_id, pendentes)


async def _atender_assunto_guardado(
    ctx: Contexto, chat_id: str, escolhido: AssuntoGuardado, resultado: dict[str, Any], pendentes: list[AssuntoPendente]
) -> Resposta:
    """#450: na conversa nova, a pessoa escolheu um assunto guardado de outra conversa. Ele é atendido agora, com o
    `chatId` desta conversa; o que ela acabou de contar fica pendente (`assuntosPendentes`).

    Assunto da Maria: abre o fluxo, com os `dadosConhecidos` da Tykhe, e a linha fica `em_andamento`.
    Assunto da Tykhe: volta como `redirecionado`, e a linha fica `resolvida`."""
    pendentes_store = await obter_pendentes_store()
    tokens_conversa = resultado.get("tokensGastosConversa")
    no_log_pendentes = {"assuntosPendentes": len(pendentes)} if pendentes else {}
    id_assunto = chat_id_do_assunto(escolhido["chatIdOrigem"], escolhido["posicao"])
    tipo_caso = escolhido.get("tipoCaso")
    if tipo_caso is not None:
        await pendentes_store.marcar(id_assunto, "resolvido")
        ctx.log.info(
            "orquestrador: assunto guardado é da Tykhe, redirecionado",
            chatId=chat_id,
            evento="assunto_guardado_redirecionado",
            status="concluido",
            destino="tykhe",
            tipoCaso=tipo_caso,
            **no_log_pendentes,
        )
        tipo = tipo_tykhe_por_caso(cast(TipoCasoTykhe, tipo_caso))
        return Resposta(200, _com_pendentes(_resposta_redirecionada(chat_id, tipo, tokens_conversa), pendentes))

    flow_id = escolhido.get("flowId")
    fluxo = await buscar_fluxo(flow_id) if flow_id else None
    if fluxo is None or flow_id is None:
        ctx.log.error(
            "orquestrador: assunto guardado com flowId que não existe em nenhum catálogo (inconsistência)",
            chatId=chat_id,
            flowId=flow_id,
            evento="orquestrador_inconsistencia",
            status="concluido",
            destino="atendimento_humano",
        )
        return Resposta(200, _resposta_handoff_sem_fluxo(chat_id))

    atendimentos = await obter_atendimentos_store()
    novo_agora = await atendimentos.buscar_atividade(chat_id) is None
    guardados = resultado.get("dadosConhecidos")
    dados = {**(guardados if isinstance(guardados, dict) else {}), **(ctx.corpo.get("dadosConhecidos") or {})}
    # O relato desta conversa é de outro assunto; o do assunto guardado nunca é guardado. O fluxo pergunta o que precisar.
    dados.pop("relato", None)
    dados["tokensGastos"] = _js.coalesce(tokens_conversa, {"input": 0, "output": 0, "total": 0})
    if novo_agora:
        ctx.log.info(
            "orquestrador: assunto guardado aberto",
            chatId=chat_id,
            evento="assunto_guardado_aberto",
            flowId=flow_id,
            **no_log_pendentes,
        )
    resposta_fluxo = await criar_atendimento(fluxo, flow_id, chat_id, dados, ctx.log, via_orquestrador=True)
    if isinstance(resposta_fluxo.corpo, dict) and resposta_fluxo.status == 200:
        texto = resposta_fluxo.corpo.get("resposta")
        if novo_agora:
            situacao: Situacao = "em_andamento" if resposta_fluxo.corpo.get("status") == "em_andamento" else "resolvido"
            await pendentes_store.marcar(id_assunto, situacao)
            if isinstance(texto, str):
                resposta_fluxo.corpo["resposta"] = f"{texto_proximo_assunto(escolhido)}\n\n{texto}"
        _com_pendentes(resposta_fluxo.corpo, pendentes)
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
    """#450 (multi-fluxo, fase 1b, só no release): abre um assunto pendente, com o `chatId` gerado pela Maria
    (`<chatId>-assunto-N`).

    - Só `chatId`: o próximo assunto pendente da conversa, na ordem.
    - Com `flowId` (assunto da Maria) ou `tipoCaso` (assunto da Tykhe), os mesmos campos de um item de
      `assuntosEmAberto` (decisão da Nicole de 2026-11-13): esse assunto, desta conversa ou guardado de outra conversa
      da mesma pessoa (2026-11-11). O campo `assunto`, com um desses valores ou com o id interno (`<chatId>-assunto-N`),
      ainda é aceito, para quem já usava.
    - Com `resposta` (a resposta da pessoa à lista dos assuntos em aberto): o assunto escolhido; "Nenhum, quero um
      assunto novo" pede o relato novo; uma resposta que a Maria não entende repete a lista.

    Idempotente: um assunto da Maria já aberto e não encerrado volta como está; um encerrado é pulado.
    Um assunto da Tykhe (`tipoCaso`) é devolvido uma vez, como `redirecionado`, e fica marcado."""
    chat_id = ctx.corpo.get("chatId", AUSENTE)
    if not isinstance(chat_id, str) or not chat_id:
        return Resposta(400, {"erro": "chatId obrigatório"})
    if not fluxo_em_teste_liga():
        return Resposta(404, {"erro": "rota disponível só no ambiente de teste (release)"})
    origem, _ = origem_do_chat(chat_id)
    # O assunto pelos campos da lista (`flowId` ou `tipoCaso`, 13/11) ou pelo campo `assunto`, de antes.
    assunto = next(
        (valor for valor in (ctx.corpo.get(c) for c in ("flowId", "tipoCaso", "assunto")) if isinstance(valor, str) and valor), None
    )
    resposta = ctx.corpo.get("resposta")
    # Duas chamadas ao mesmo tempo para a mesma conversa (um retry da Tykhe) esperam a vez: sem a trava, a
    # 2ª via o atendimento já registrado, mas ainda sem conversa, e devolvia a mensagem de sucesso do fluxo
    # (achado do teste de consistência, 2026-11-09). A API roda num processo só, como a ponte do WhatsApp.
    async with _TRAVAS_PROXIMO.setdefault(origem, asyncio.Lock()):
        if not (isinstance(assunto, str) and assunto) and isinstance(resposta, str) and resposta.strip():
            abertos = await assuntos_em_aberto(chat_id)
            escolha = escolha_nos_abertos(resposta, abertos)
            if escolha == "encerrar":
                ctx.log.info(
                    "orquestrador: conversa encerrada pela pessoa", chatId=chat_id, evento="conversa_encerrada", emAberto=len(abertos)
                )
                return Resposta(200, _resposta_encerrada(chat_id, guardados=any("venceEm" in a for a in abertos)))
            if escolha == "nenhum" or not abertos:
                return Resposta(200, _resposta_assunto_novo(chat_id, sem_abertos=not abertos))
            if escolha is None:
                return Resposta(200, _resposta_lista(chat_id, abertos))
            assunto = abertos[escolha]["chatIdAssunto"]
        elif isinstance(assunto, str) and assunto:
            # O `flowId` ou o `tipoCaso` vira o id interno do assunto em aberto. Um id que não está em aberto segue
            # como veio: o id interno de antes abre o assunto; qualquer outro dá 404.
            assunto = chat_do_assunto_pelo_id(assunto, await assuntos_em_aberto(chat_id)) or assunto
        if isinstance(assunto, str) and assunto:
            origem_do_alvo, posicao = origem_do_chat(assunto)
            if origem_do_alvo == origem and posicao >= 2:
                return await _abrir_proximo_assunto(ctx, origem, posicao)
            return await _abrir_guardado(ctx, chat_id, assunto)
        return await _abrir_proximo_assunto(ctx, origem)


_TRAVAS_PROXIMO: dict[str, asyncio.Lock] = {}


def _resposta_lista(chat_id: str, abertos: list[AssuntoAberto]) -> dict[str, Any]:
    """ "Qual você quer resolver agora?": a resposta da pessoa volta para a rota do próximo assunto, que também entende o
    encerrar (decisão da Nicole, 2026-11-13: quem não quer continuar com os assuntos em aberto pode encerrar)."""
    return {
        "resposta": texto_abertos(abertos, com_encerrar=True),
        "tipoResposta": "opcoes",
        "opcoes": opcoes_abertos(abertos, com_encerrar=True),
        "status": "em_andamento",
        "assuntosEmAberto": para_a_tykhe(abertos),
        "_links": {"self": {"href": f"/atendimentos/{chat_id}"}, "responder": {"href": "/atendimentos/proximo-assunto", "method": "POST"}},
    }


def _resposta_encerrada(chat_id: str, *, guardados: bool) -> dict[str, Any]:
    """ "Encerrar a conversa", no fim: a despedida. Os assuntos em aberto continuam guardados."""
    return {
        "resposta": TEXTO_ENCERRADA_GUARDADOS if guardados else TEXTO_ENCERRADA,
        "tipoResposta": "texto",
        "status": "concluido",
        "_links": {"self": {"href": f"/atendimentos/{chat_id}"}},
    }


def _resposta_assunto_novo(chat_id: str, *, sem_abertos: bool) -> dict[str, Any]:
    """ "Pode me contar o que você precisa?": a resposta da pessoa abre uma conversa nova no orquestrador."""
    return {
        "resposta": TEXTO_SEM_ABERTOS if sem_abertos else TEXTO_ASSUNTO_NOVO,
        "tipoResposta": "texto",
        "status": "em_andamento",
        "_links": {"self": {"href": f"/atendimentos/{chat_id}"}, "responder": {"href": "/atendimentos/orquestrador", "method": "POST"}},
    }


async def _post_assuntos_em_aberto(ctx: Contexto) -> Resposta:
    """#450 (2026-11-11, só no release): a lista dos assuntos em aberto da pessoa, quando ela toca em "Ver os
    assuntos em aberto" no fim de um assunto. Sem nenhum, pede o que ela precisa."""
    chat_id = ctx.corpo.get("chatId", AUSENTE)
    if not isinstance(chat_id, str) or not chat_id:
        return Resposta(400, {"erro": "chatId obrigatório"})
    if not fluxo_em_teste_liga():
        return Resposta(404, {"erro": "rota disponível só no ambiente de teste (release)"})
    abertos = await assuntos_em_aberto(chat_id)
    ctx.log.info("orquestrador: assuntos em aberto listados", chatId=chat_id, evento="assuntos_em_aberto_listados", quantos=len(abertos))
    if not abertos:
        return Resposta(200, _resposta_assunto_novo(chat_id, sem_abertos=True))
    return Resposta(200, _resposta_lista(chat_id, abertos))


async def _abrir_guardado(ctx: Contexto, chat_id: str, assunto: str) -> Resposta:
    """Um assunto guardado de outra conversa da mesma pessoa, aberto com o `chatId` dele. Só da mesma pessoa (pelo
    `idUsuario` da conversa) e ainda no prazo."""
    id_usuario = await usuario_do_chat(chat_id)
    guardado = await (await obter_pendentes_store()).buscar_da_pessoa(id_usuario, assunto) if id_usuario else None
    if guardado is None:
        return Resposta(404, {"erro": "assunto não encontrado para esta pessoa"})
    if guardado["situacao"] == "resolvido":
        return Resposta(409, {"erro": "assunto já atendido"})
    tipo_caso = guardado.get("tipoCaso")
    if tipo_caso is not None:
        await (await obter_pendentes_store()).marcar(assunto, "resolvido")
        ctx.log.info(
            "orquestrador: assunto guardado é da Tykhe, redirecionado",
            chatId=assunto,
            evento="assunto_guardado_redirecionado",
            tipoCaso=tipo_caso,
        )
        corpo = _resposta_redirecionada(assunto, tipo_tykhe_por_caso(cast(TipoCasoTykhe, tipo_caso)), None)
        corpo["chatId"] = assunto
        return Resposta(200, corpo)
    flow_id = guardado.get("flowId")
    fluxo = await buscar_fluxo(flow_id) if flow_id else None
    if fluxo is None or flow_id is None:
        return Resposta(404, {"erro": "assunto não encontrado para esta pessoa"})
    atividade = await (await obter_atendimentos_store()).buscar_atividade(assunto)
    if atividade is not None and atividade.get("statusFinal"):
        return Resposta(409, {"erro": "assunto já atendido"})
    novo_agora = atividade is None
    if novo_agora:
        ctx.log.info("orquestrador: assunto guardado aberto", chatId=assunto, evento="assunto_guardado_aberto", flowId=flow_id)
    resposta_fluxo = await criar_atendimento(fluxo, flow_id, assunto, {}, ctx.log, via_orquestrador=True)
    if isinstance(resposta_fluxo.corpo, dict) and resposta_fluxo.status == 200:
        texto = resposta_fluxo.corpo.get("resposta")
        if novo_agora:
            situacao: Situacao = "em_andamento" if resposta_fluxo.corpo.get("status") == "em_andamento" else "resolvido"
            await (await obter_pendentes_store()).marcar(assunto, situacao)
            if isinstance(texto, str):
                resposta_fluxo.corpo["resposta"] = f"{texto_proximo_assunto(guardado)}\n\n{texto}"
        resposta_fluxo.corpo["chatId"] = assunto
    return resposta_fluxo


async def _abrir_proximo_assunto(ctx: Contexto, origem: str, so_posicao: int | None = None) -> Resposta:
    config: Any = {"configurable": {"thread_id": f"orquestrador:{origem}"}}
    grafo = obter_grafo()
    valores = dict((await grafo.aget_state(config)).values or {})
    pendentes: list[AssuntoPendente] = valores.get("assuntosPendentes") or []
    encaminhados = set(valores.get("assuntosEncaminhados") or [])
    store = await obter_atendimentos_store()
    cpf = await _cpf_da_conversa(origem, valores, len(pendentes) + 1, store) if pendentes else None

    for indice, item in enumerate(pendentes):
        posicao = indice + 2
        if so_posicao is not None and posicao != so_posicao:
            continue
        novo = chat_id_do_assunto(origem, posicao)
        restantes = _com_cpf(pendentes[indice + 1 :], cpf)
        tipo_caso = item.get("tipoCaso")
        if tipo_caso is not None:
            if posicao in encaminhados:
                continue
            await grafo.aupdate_state(config, {"assuntosEncaminhados": sorted(encaminhados | {posicao})})
            await (await obter_pendentes_store()).marcar(novo, "resolvido")
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
            if novo_agora:
                # #450: a linha guardada (se a Tykhe mandou o idUsuario) acompanha o assunto, pelo id dele.
                situacao: Situacao = "em_andamento" if resposta_fluxo.corpo.get("status") == "em_andamento" else "resolvido"
                await (await obter_pendentes_store()).marcar(novo, situacao)
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
    Rota(
        "POST",
        "/atendimentos/assuntos-em-aberto",
        _post_assuntos_em_aberto,
        corpo=esquemas.CORPO_ASSUNTOS_EM_ABERTO,
        respostas={200: esquemas.RESPOSTA_ASSUNTOS_EM_ABERTO, 400: esquemas.ERRO_ORQUESTRADOR, 404: esquemas.ERRO_ORQUESTRADOR},
        resumo="Lista os assuntos em aberto da pessoa, para ela escolher qual resolver (multi-fluxo, só no release)",
        tags=("atendimentos",),
    ),
)
