"""Grafo do orquestrador (develop: `orquestrador/graph.ts` @ 1157a6d, issues #28, #32, #34, #43, #47).

Classifica o relato livre entre as opções de `catalogo_para_classificacao` e,
quando sobra mais de uma, pergunta até convergir. O que fazer com o desfecho
(seguir para o fluxo ou devolver à Tykhe) é da rota, no módulo `api`.

Pontos onde a tradução ingênua muda o comportamento (spec 06, seção 3):
- a saída do modelo não é validada (#212): `ids` que não é lista lança
  `TypeError`, como o `ids.map` de develop, em vez de ser iterado; item que
  não é string não acha nada, como o `Map.get` do JS, em vez de lançar;
- `candidatosRestantes` e `resumoRelato` são testados contra `None`, nunca por
  truthiness: `""` é um resumo válido;
- a pergunta tirada do banco devolve só `perguntaAtualTexto`; escrever os
  tokens ali apagaria o que o `classificar` gravou;
- `${...}` de JS é `_js.texto_template`, não `str()`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Hashable
from typing import Any, Literal, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.fluxos import ID_PROBLEMAS_PLANO_SAUDE, catalogo_para_classificacao, fluxo_em_teste_liga
from maria.fluxos._fabrica import FabricaGrafo, GrafoCompilado
from maria.ia.classificar_fluxos import classificar_fluxos_plausiveis
from maria.ia.classificar_necessidades import classificar_necessidades
from maria.ia.desambiguar import CandidatoParaDesambiguar, gerar_pergunta_desambiguacao
from maria.ia.sumarizar import sumarizar_relato
from maria.orquestrador import fila as _fila
from maria.orquestrador.state import CandidatoOrquestrador, OrquestradorState
from maria.shared import _js
from maria.shared.embeddings_fluxos import buscar_candidatos
from maria.shared.pendentes_db import obter_pendentes_store
from maria.shared.perguntas_db import OpcaoPergunta, PerguntaArvore, obter_perguntas_store
from maria.shared.tokens_acumulados import TokensGastos

# Quantos candidatos entram no prompt de classificação/retrieval na 1ª rodada.
# Era 10 desde antes da issue #28 (CANDIDATOS_MAXIMOS em rotas/orquestrador.ts).
# #353 (2026-10-27): 15, medido com as 74 categorias ligadas fora do ar. A
# conversa chega ao destino certo em 95% dos relatos, contra 90% com 10, por
# ~900 tokens a mais por chamada e o mesmo tempo. Com até 15 opções no
# catálogo, a busca não corta nada (hoje são 9).
CANDIDATOS_MAXIMOS = 15

# Quantas rodadas de desambiguação no máximo antes de desistir e cair para
# "não identificado". Subido de 3 para 5 (issue #43, 2026-09-14), quando o
# catálogo tinha 76 categorias e relatos ambíguos entre categorias parecidas
# levavam mais idas e vindas para convergir.
LIMITE_RODADAS = 5

# Issue #47: a partir desta rodada (inclusive), a classificação e a
# desambiguação usam resumo + última resposta em vez do histórico bruto.
LIMITE_RODADAS_SUMARIZACAO = 3

TEXTO_PEDIR_DESAMBIGUACAO_PADRAO = "Pra te ajudar melhor, pode contar com mais detalhes o que você precisa?"


def texto_para_classificacao(state: OrquestradorState) -> Any:
    """Enquanto não sumarizou (`resumoRelato` None), o histórico bruto; depois,
    resumo (do que veio ANTES) + última resposta (verbatim)."""
    # `=== undefined`: "" é resumo válido. O `null` do modelo também cai aqui
    # (divergência aceita, spec 06 D-1).
    resumo = state.get("resumoRelato")
    if resumo is None:
        return state.get("mensagem", _js.AUSENTE)
    return f"{_js.texto_template(resumo)}\n{_js.texto_template(_js.coalesce(state.get('ultimaResposta'), ''))}"


def _lista_de_ids(ids: Any) -> list[Any]:
    """O `ids.map` de develop: lança `TypeError` se `ids` não for lista, com a
    mesma mensagem do JS. Sem isso, o Python iteraria os caracteres de uma
    string ou as chaves de um objeto e seguiria."""
    if isinstance(ids, list):
        return ids
    if ids is None or ids is _js.AUSENTE:
        raise TypeError(f"Cannot read properties of {'null' if ids is None else 'undefined'} (reading 'map')")
    raise TypeError("ids.map is not a function")


def _delta_tokens(resultado: Any) -> TokensGastos:
    return {
        "input": _js.coalesce(resultado.get("tokensEntrada"), 0),
        "output": _js.coalesce(resultado.get("tokensSaida"), 0),
        "total": _js.coalesce(resultado.get("tokensTotal"), 0),
    }


# Issue #419 (decisão do Ícaro, 2026-11-05): quando os candidatos são só estes dois, o orquestrador não pergunta
# nada e segue direto para o fluxo desenhado com o NUDECON (a cirurgia pelo SUS não tem pergunta própria).
# A chave é o conjunto de ids (a ordem não importa); o valor é o fluxo escolhido.
ESCOLHA_DIRETA: dict[frozenset[str], str] = {frozenset({ID_PROBLEMAS_PLANO_SAUDE, "tykhe:saude"}): ID_PROBLEMAS_PLANO_SAUDE}


def resolver_escolha_direta(candidatos: list[CandidatoOrquestrador]) -> list[CandidatoOrquestrador]:
    escolhido = ESCOLHA_DIRETA.get(frozenset(c["id"] for c in candidatos))
    return [c for c in candidatos if c["id"] == escolhido] if escolhido else candidatos


async def classificar(state: OrquestradorState) -> dict[str, Any]:
    """1ª rodada: retrieval no catálogo completo (issue #8) e classificação.
    Rodadas seguintes: classifica de novo, só DENTRO do que já sobrou."""
    # Lookup contra o catálogo INTEIRO, não só o pool do retrieval: em teste, o
    # mock devolve um id fixo sem olhar o pool (embedding falso, sem significado).
    catalogo_completo = await catalogo_para_classificacao()
    pool: list[CandidatoOrquestrador] | None = state.get("candidatosRestantes")
    if pool is None:
        # A rota sempre manda `mensagem` no 1º invoke (`body.mensagem ?? ""`).
        pool = await buscar_candidatos(cast(str, state.get("mensagem", _js.AUSENTE)), CANDIDATOS_MAXIMOS, catalogo_completo)
    if fluxo_em_teste_liga():
        return await _classificar_por_necessidades(state, catalogo_completo, pool)
    resultado = await classificar_fluxos_plausiveis(texto_para_classificacao(state), pool)
    por_id: dict[str, CandidatoOrquestrador] = {c["id"]: c for c in catalogo_completo}
    # `Map.get` com um valor que não é chave devolve undefined; `dict.get` com
    # lista ou objeto lançaria. Item que não é string não acha nada.
    plausiveis = [por_id[i] for i in _lista_de_ids(resultado.get("ids", _js.AUSENTE)) if isinstance(i, str) and i in por_id]
    plausiveis = resolver_escolha_direta(plausiveis)
    # Sempre o 1º nó da rodada: sobrescreve (não soma) de propósito, é o início
    # da contagem desta rodada (issue #34). tokensGastosConversa tem reducer de
    # soma; aqui vai só o DELTA desta chamada.
    return {
        "candidatosRestantes": plausiveis,
        "tokensGastosRodada": resultado.get("tokensTotal"),
        "tokensGastosConversa": _delta_tokens(resultado),
    }


async def _classificar_por_necessidades(
    state: OrquestradorState, catalogo_completo: list[CandidatoOrquestrador], pool: list[CandidatoOrquestrador]
) -> dict[str, Any]:
    """Multi-fluxo, fase 1a (#435), só no release.

    - 2 assuntos ou mais: monta a fila, e a Maria pergunta a ordem.
    - Dúvida entre opções para um mesmo assunto: o caminho de hoje (escolha direta da #419 e desambiguação).
    - 1 assunto: segue direto, como hoje."""
    resultado = await classificar_necessidades(texto_para_classificacao(state), pool)
    por_id: dict[str, CandidatoOrquestrador] = {c["id"]: c for c in catalogo_completo}
    fila = _fila.montar_fila(resultado["necessidades"])
    tokens = {"tokensGastosRodada": resultado.get("tokensTotal"), "tokensGastosConversa": _delta_tokens(resultado)}
    if len(fila) >= 2:
        return {"fila": fila, **tokens}
    if len(resultado["idsEmAmbiguidade"]) >= 2:
        candidatos = [por_id[i] for i in resultado["idsEmAmbiguidade"] if i in por_id]
    else:
        candidatos = [por_id[i["id"]] for i in fila if i["id"] in por_id]
    return {"candidatosRestantes": resolver_escolha_direta(candidatos), "fila": None, **tokens}


RotaDaClassificacao = Literal["nenhum", "um", "muitos", "fila"]
ROTAS_DA_CLASSIFICACAO: dict[Hashable, str] = {
    "nenhum": "naoIdentificado",
    "um": "identificado",
    "muitos": "prepararPerguntaDesambiguacao",
    "fila": "perguntarOrdem",
}


def depois_de_classificar(state: OrquestradorState) -> Literal[RotaDaClassificacao, "buscarPendentes"]:
    """#450 (só no release): com o `idUsuario` da Tykhe, antes de seguir, os assuntos guardados da pessoa, uma vez
    por conversa."""
    if precisa_buscar_pendentes(state):
        return "buscarPendentes"
    return rota_da_classificacao(state)


def rota_da_classificacao(state: OrquestradorState) -> RotaDaClassificacao:
    """Esgotar o limite de rodadas com mais de 1 candidato vira "nenhum"."""
    if len(state.get("fila") or []) >= 2:
        return "fila"
    n = len(_js.coalesce(state.get("candidatosRestantes"), []))
    if n == 0:
        return "nenhum"
    if n == 1:
        return "um"
    if _js.coalesce(state.get("rodada"), 0) >= LIMITE_RODADAS:
        return "nenhum"
    return "muitos"


async def identificado(state: OrquestradorState) -> dict[str, Any]:
    candidatos = _js.coalesce(state.get("candidatosRestantes"), [])
    return {"statusFinal": "identificado", "flowIdEscolhido": candidatos[0]["id"] if candidatos else None}


async def nao_identificado(state: OrquestradorState) -> dict[str, Any]:
    return {"statusFinal": "nao_identificado"}


def _resposta_normalizada(o: OpcaoPergunta) -> str:
    """`o.resposta.trim().toUpperCase()`, com as exceções do JS quando a resposta
    do banco não é texto (achado na varredura: `resposta` nula dava
    AttributeError no Python e TypeError em develop)."""
    resposta: Any = _js.prop(o, "resposta")
    if resposta is None or resposta is _js.AUSENTE:
        raise TypeError(f"Cannot read properties of {'null' if resposta is None else 'undefined'} (reading 'trim')")
    if not isinstance(resposta, str):
        raise TypeError("o.resposta.trim is not a function")
    return _js.trim_js(resposta).upper()


def mesmo_conjunto_de_opcoes(a: list[OpcaoPergunta], b: list[OpcaoPergunta]) -> bool:
    """Mesmo conjunto de respostas, sem depender de ordem (issue #32).

    A ordenação do JS (code units UTF-16) e a do Python (code points) diferem
    fora do BMP, mas não muda o resultado: com os dois lados ordenados do mesmo
    jeito, comparar posição a posição é comparar multiconjuntos."""
    if len(a) != len(b):
        return False
    textos_a = sorted(_resposta_normalizada(o) for o in a)
    textos_b = sorted(_resposta_normalizada(o) for o in b)
    return textos_a == textos_b


async def buscar_pergunta_real_compartilhada(candidatos: list[CandidatoOrquestrador]) -> str | None:
    """Issue #32: quando TODOS os candidatos restantes têm a mesma pergunta raiz
    do Verde (mesmo texto e mesmas opções), usa o texto real em vez de gerar
    uma pergunta por IA. Só olha `ordem = 0` (raiz)."""
    if len(candidatos) < 2:
        return None
    store = await obter_perguntas_store()
    raizes: list[PerguntaArvore | None] = list(await asyncio.gather(*(store.buscar_pergunta_raiz(c["id"]) for c in candidatos)))
    primeira = raizes[0]
    if primeira is None:
        return None
    todas_iguais = all(
        r is not None and r["textoPergunta"] == primeira["textoPergunta"] and mesmo_conjunto_de_opcoes(r["opcoes"], primeira["opcoes"])
        for r in raizes
    )
    return primeira["textoPergunta"] if todas_iguais else None


def somar_tokens_rodada(a: int | None, b: int | None) -> int | None:
    """undefined + undefined = undefined ("não sei", não "custou 0"); só soma
    quando pelo menos 1 dos 2 lados teve chamada de IA (issue #34)."""
    if a is None and b is None:
        return None
    return cast(int, _js.coalesce(a, 0)) + cast(int, _js.coalesce(b, 0))


async def preparar_pergunta_desambiguacao(state: OrquestradorState) -> dict[str, Any]:
    candidatos = _js.coalesce(state.get("candidatosRestantes"), [])
    pergunta_do_banco = await buscar_pergunta_real_compartilhada(candidatos)
    # Match no banco não chama IA: devolve SÓ a pergunta, e o
    # tokensGastosRodada do `classificar` fica como está.
    if _js.verdadeiro(pergunta_do_banco):
        return {"perguntaAtualTexto": pergunta_do_banco}
    resultado = await gerar_pergunta_desambiguacao(texto_para_classificacao(state), cast(list[CandidatoParaDesambiguar], candidatos))
    return {
        # Chave ausente no retorno da IA é o undefined de develop: grava None.
        "perguntaAtualTexto": resultado.get("pergunta"),
        "tokensGastosRodada": somar_tokens_rodada(state.get("tokensGastosRodada"), resultado.get("tokensTotal")),
        "tokensGastosConversa": _delta_tokens(resultado),
    }


async def pedir_desambiguacao(state: OrquestradorState) -> dict[str, Any]:
    # Tipo "texto" (não "opcoes") de propósito, decisão de 2026-09-11: os nomes
    # internos dos candidatos como menu soavam técnicos. Sem a chave `opcoes`.
    resposta = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_PEDIR_DESAMBIGUACAO_PADRAO), "tipo": "texto"})
    nova_rodada = cast(int, _js.coalesce(state.get("rodada"), 0)) + 1
    # candidatosRestantes NÃO é tocado: a próxima rodada reaproveita o mesmo
    # subconjunto. `mensagem` continua acumulando SEMPRE (issue #47). Este código
    # roda depois do interrupt resolver: só o que vem ANTES dele reexecuta.
    mensagem = f"{_js.texto_template(state.get('mensagem', _js.AUSENTE))}\n{_js.texto_template(resposta)}"
    if nova_rodada < LIMITE_RODADAS_SUMARIZACAO:
        return {"mensagem": mensagem, "rodada": nova_rodada}
    # A partir do limite: sumariza o que veio ANTES desta resposta; a resposta
    # atual fica fora do resumo, guardada verbatim em ultimaResposta.
    resultado = await sumarizar_relato(texto_para_classificacao(state))
    return {
        "mensagem": mensagem,
        "resumoRelato": resultado.get("resumo"),
        "ultimaResposta": resposta,
        "rodada": nova_rodada,
        "tokensGastosRodada": somar_tokens_rodada(state.get("tokensGastosRodada"), resultado.get("tokensTotal")),
        "tokensGastosConversa": _delta_tokens(resultado),
    }


# ── Multi-fluxo, fase 1a (#435): a ordem dos assuntos ─────────────────────────
async def perguntar_ordem(state: OrquestradorState) -> dict[str, Any]:
    """ "Pode ser assim?" (decisão da Nicole, 06/11).

    Sim: segue a ordem. Não, com 2 assuntos: troca. Não, com 3 ou mais: pergunta qual primeiro.
    O nome de um assunto ("o do meu filho") põe esse assunto na frente. Resposta que a Maria não
    entende segue a ordem proposta, sem perguntar de novo."""
    fila = cast(list[_fila.ItemFila], state.get("fila") or [])
    resposta = cast(str, interrupt({"pergunta": _fila.texto_ordem(fila), "tipo": "sim_nao", "opcoes": ["Sim", "Não"], "etapa": "ordem"}))
    escolher = False
    if _fila.aceitou(resposta):
        pass
    elif _fila.recusou(resposta):
        if len(fila) == 2:
            fila = _fila.para_frente(fila, 1)
        else:
            escolher = True
    else:
        posicao = _fila.assunto_escolhido(resposta, fila)
        if posicao is not None:
            fila = _fila.para_frente(fila, posicao)
    return {"fila": fila, "ordemPerguntada": True, "escolherPrimeiro": escolher}


def depois_da_ordem(state: OrquestradorState) -> Literal["escolher", "comecar"]:
    return "escolher" if state.get("escolherPrimeiro") else "comecar"


async def perguntar_primeiro(state: OrquestradorState) -> dict[str, Any]:
    """ "Qual você quer resolver primeiro?" Sem entender a resposta, segue a ordem proposta."""
    fila = cast(list[_fila.ItemFila], state.get("fila") or [])
    resposta = cast(str, interrupt({"pergunta": _fila.texto_qual_primeiro(fila), "tipo": "texto", "etapa": "primeiro"}))
    posicao = _fila.assunto_escolhido(resposta, fila)
    return {"fila": _fila.para_frente(fila, posicao) if posicao is not None else fila, "escolherPrimeiro": False}


async def comecar_fila(state: OrquestradorState) -> dict[str, Any]:
    """O primeiro assunto da fila segue como um relato de um assunto só; os outros ficam pendentes."""
    fila = cast(list[_fila.ItemFila], state.get("fila") or [])
    por_id = {c["id"]: c for c in await catalogo_para_classificacao()}
    primeiro = por_id.get(fila[0]["id"]) if fila else None
    return {
        "candidatosRestantes": [primeiro] if primeiro is not None else [],
        "assuntosPendentes": [_fila.pendente(i) for i in fila[1:]],
    }


def depois_de_comecar(state: OrquestradorState) -> Literal["um", "nenhum"]:
    return "um" if state.get("candidatosRestantes") else "nenhum"


# ── #450 (multi-fluxo, só no release): os assuntos guardados da pessoa ──
# Decisão da Nicole (2026-11-10): a pessoa é identificada pelo `idUsuario` que a Tykhe manda na 1ª chamada, e não
# mais pelo CPF pedido logo depois da 1ª mensagem. Sem `idUsuario`, nada é buscado nem guardado, e a conversa segue
# como antes. O CPF volta a ser pedido pelos fluxos que precisam dele.


def precisa_buscar_pendentes(state: OrquestradorState) -> bool:
    # #299 (futuro): com sinal de risco no relato, o aviso de segurança sai primeiro. A detecção de risco ainda não
    # existe; quando existir, ela entra aqui, antes da pergunta dos guardados.
    if not fluxo_em_teste_liga() or state.get("pendentesBuscados") or not state.get("idUsuario"):
        return False
    # Quem só quer sair da conversa não recebe a pergunta dos guardados.
    so_sair = not state.get("fila") and [c["id"] for c in state.get("candidatosRestantes") or []] == [_fila.ID_SAIR]
    return not so_sair


async def buscar_pendentes(state: OrquestradorState, config: RunnableConfig) -> dict[str, Any]:
    """Os assuntos guardados de OUTRAS conversas desta pessoa (pelo `idUsuario`), os urgentes primeiro. A consulta
    apaga os vencidos (sem contato por 30 dias, ou 60 com a prorrogação)."""
    id_usuario = state.get("idUsuario")
    if not id_usuario:
        return {"pendentesGuardados": None, "pendentesBuscados": True}
    chat_id = str(config.get("configurable", {}).get("thread_id", "")).removeprefix("orquestrador:")
    store = await obter_pendentes_store()
    guardados: list[_fila.AssuntoGuardado] = []
    nomes: set[str] = set()
    for p in await store.listar_ativos(id_usuario):
        if p["chatIdOrigem"] == chat_id or p["nome"] in nomes:
            continue  # o mesmo assunto guardado duas vezes aparece uma vez só (o mais antigo)
        nomes.add(p["nome"])
        guardado: _fila.AssuntoGuardado = {
            "chatIdOrigem": p["chatIdOrigem"],
            "posicao": p["posicao"],
            "nome": p["nome"],
            "urgente": p["urgente"],
            "urgencia": p["urgencia"],
        }
        if "flowId" in p:
            guardado["flowId"] = p["flowId"]
        if "tipoCaso" in p:
            guardado["tipoCaso"] = p["tipoCaso"]
        guardados.append(guardado)
    return {"pendentesGuardados": _fila.em_ordem_de_urgencia(guardados) or None, "pendentesBuscados": True}


def depois_de_buscar_pendentes(state: OrquestradorState) -> Literal[RotaDaClassificacao, "perguntar"]:
    return "perguntar" if state.get("pendentesGuardados") else rota_da_classificacao(state)


def assuntos_do_relato(state: OrquestradorState) -> list[_fila.AssuntoPendente]:
    """Quando a pessoa escolhe um assunto guardado, o que ela acabou de contar vira pendente desta conversa.
    Relato que a Maria não entendeu (nenhuma opção, ou dúvida entre opções) não vira pendente: não há o que guardar."""
    fila = state.get("fila") or []
    if len(fila) >= 2:
        return [_fila.pendente(i) for i in fila]
    candidatos = state.get("candidatosRestantes") or []
    if len(candidatos) != 1:
        return []
    id_ = candidatos[0]["id"]
    relato = _js.texto_template(state.get("mensagem", "")).strip()
    item: _fila.ItemFila = {"id": id_, "nome": _fila.NOME_SIMPLES.get(id_, "o outro assunto"), "urgente": False, "evidencia": relato}
    return [_fila.pendente(item)]


async def perguntar_pendentes(state: OrquestradorState) -> dict[str, Any]:
    """ "Quer falar dele agora ou do que você acabou de contar?" Sem entender a resposta, segue com o que a pessoa
    acabou de contar."""
    guardados = cast(list[_fila.AssuntoGuardado], state.get("pendentesGuardados") or [])
    resposta = cast(
        str,
        interrupt(
            {
                "pergunta": _fila.texto_pendentes(guardados),
                "tipo": "opcoes",
                "opcoes": _fila.opcoes_pendentes(guardados),
                "etapa": "pendentes",
            }
        ),
    )
    indice = _fila.pendente_escolhido(_js.texto_template(resposta), guardados)
    if indice is None:
        return {"pendenteEscolhido": None, "tokensGastosRodada": None}
    return {"pendenteEscolhido": guardados[indice], "assuntosPendentes": assuntos_do_relato(state), "tokensGastosRodada": None}


def depois_dos_pendentes(state: OrquestradorState) -> Literal[RotaDaClassificacao, "escolhido"]:
    return "escolhido" if state.get("pendenteEscolhido") else rota_da_classificacao(state)


_construtor = StateGraph(OrquestradorState)
_construtor.add_node("classificar", classificar)
_construtor.add_node("identificado", identificado)
_construtor.add_node("naoIdentificado", nao_identificado)
_construtor.add_node("prepararPerguntaDesambiguacao", preparar_pergunta_desambiguacao)
_construtor.add_node("pedirDesambiguacao", pedir_desambiguacao)
_construtor.add_node("perguntarOrdem", perguntar_ordem)
_construtor.add_node("perguntarPrimeiro", perguntar_primeiro)
_construtor.add_node("comecarFila", comecar_fila)
_construtor.add_node("buscarPendentes", buscar_pendentes)
_construtor.add_node("perguntarPendentes", perguntar_pendentes)
_construtor.add_edge(START, "classificar")
_construtor.add_conditional_edges(
    "classificar",
    depois_de_classificar,
    {**ROTAS_DA_CLASSIFICACAO, "buscarPendentes": "buscarPendentes"},
)
# #450: a pergunta dos assuntos guardados (só alcançada no release, com o idUsuario da Tykhe).
_construtor.add_conditional_edges(
    "buscarPendentes", depois_de_buscar_pendentes, {**ROTAS_DA_CLASSIFICACAO, "perguntar": "perguntarPendentes"}
)
_construtor.add_conditional_edges("perguntarPendentes", depois_dos_pendentes, {**ROTAS_DA_CLASSIFICACAO, "escolhido": END})
_construtor.add_edge("prepararPerguntaDesambiguacao", "pedirDesambiguacao")
_construtor.add_edge("pedirDesambiguacao", "classificar")
_construtor.add_conditional_edges("perguntarOrdem", depois_da_ordem, {"escolher": "perguntarPrimeiro", "comecar": "comecarFila"})
_construtor.add_edge("perguntarPrimeiro", "comecarFila")
_construtor.add_conditional_edges("comecarFila", depois_de_comecar, {"um": "identificado", "nenhum": "naoIdentificado"})
_construtor.add_edge("identificado", END)
_construtor.add_edge("naoIdentificado", END)

_fabrica = FabricaGrafo(_construtor)
criar_grafo = _fabrica.criar


def obter_grafo() -> GrafoCompilado:
    return _fabrica.obter()


async def assuntos_pendentes_do_chat(chat_id: str) -> list[_fila.AssuntoPendente] | None:
    """Os outros assuntos que o orquestrador guardou para esta conversa (#435), para a resposta final
    do fluxo. Só no release: na produção, nem lê o checkpoint."""
    if not fluxo_em_teste_liga():
        return None
    # #450: num assunto aberto pela rota do próximo assunto (`<chatId>-assunto-N`), os pendentes são os da
    # conversa de origem que vêm depois dele.
    origem, posicao = _fila.origem_do_chat(chat_id)
    estado = await obter_grafo().aget_state({"configurable": {"thread_id": f"orquestrador:{origem}"}})
    pendentes = (estado.values or {}).get("assuntosPendentes") or []
    return pendentes[posicao - 1 :] or None


async def assunto_guardado_do_chat(chat_id: str) -> str | None:
    """#450: o id (o `chatId` do assunto) da linha de `assuntos_pendentes` que este atendimento atende.

    Um assunto aberto pela rota do próximo assunto (`<chatId>-assunto-N`) é ele mesmo. Um assunto guardado que a
    pessoa escolheu numa conversa nova está no estado do orquestrador dessa conversa. Só no release: na produção,
    nem lê o checkpoint."""
    if not fluxo_em_teste_liga():
        return None
    _, posicao = _fila.origem_do_chat(chat_id)
    if posicao >= 2:
        return chat_id
    estado = await obter_grafo().aget_state({"configurable": {"thread_id": f"orquestrador:{chat_id}"}})
    escolhido = (estado.values or {}).get("pendenteEscolhido")
    if isinstance(escolhido, dict) and "flowId" in escolhido:
        return _fila.chat_id_do_assunto(str(escolhido["chatIdOrigem"]), int(escolhido["posicao"]))
    return None


async def usuario_do_chat(chat_id: str) -> str | None:
    """#450: o `idUsuario` que a Tykhe mandou na conversa deste atendimento. Com ele, os pendentes ficam guardados
    e o fim do assunto avisa os 30 dias. Só no release."""
    if not fluxo_em_teste_liga():
        return None
    origem, _ = _fila.origem_do_chat(chat_id)
    estado = await obter_grafo().aget_state({"configurable": {"thread_id": f"orquestrador:{origem}"}})
    id_usuario = (estado.values or {}).get("idUsuario")
    return id_usuario if isinstance(id_usuario, str) and id_usuario else None
