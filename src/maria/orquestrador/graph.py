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
from typing import Any, Literal, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.fluxos import catalogo_para_classificacao
from maria.fluxos._fabrica import FabricaGrafo, GrafoCompilado
from maria.ia.classificar_fluxos import classificar_fluxos_plausiveis
from maria.ia.desambiguar import CandidatoParaDesambiguar, gerar_pergunta_desambiguacao
from maria.ia.sumarizar import sumarizar_relato
from maria.orquestrador.state import CandidatoOrquestrador, OrquestradorState
from maria.shared import _js
from maria.shared.embeddings_fluxos import buscar_candidatos
from maria.shared.perguntas_db import OpcaoPergunta, PerguntaArvore, obter_perguntas_store
from maria.shared.tokens_acumulados import TokensGastos

# Mesmo valor de antes da issue #28 (era CANDIDATOS_MAXIMOS em
# rotas/orquestrador.ts): quantos candidatos entram no prompt de
# classificação/retrieval na 1ª rodada.
CANDIDATOS_MAXIMOS = 10

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
    resultado = await classificar_fluxos_plausiveis(texto_para_classificacao(state), pool)
    por_id: dict[str, CandidatoOrquestrador] = {c["id"]: c for c in catalogo_completo}
    # `Map.get` com um valor que não é chave devolve undefined; `dict.get` com
    # lista ou objeto lançaria. Item que não é string não acha nada.
    plausiveis = [por_id[i] for i in _lista_de_ids(resultado.get("ids", _js.AUSENTE)) if isinstance(i, str) and i in por_id]
    # Sempre o 1º nó da rodada: sobrescreve (não soma) de propósito, é o início
    # da contagem desta rodada (issue #34). tokensGastosConversa tem reducer de
    # soma; aqui vai só o DELTA desta chamada.
    return {
        "candidatosRestantes": plausiveis,
        "tokensGastosRodada": resultado.get("tokensTotal"),
        "tokensGastosConversa": _delta_tokens(resultado),
    }


def depois_de_classificar(state: OrquestradorState) -> Literal["nenhum", "um", "muitos"]:
    """Esgotar o limite de rodadas com mais de 1 candidato vira "nenhum"."""
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


def mesmo_conjunto_de_opcoes(a: list[OpcaoPergunta], b: list[OpcaoPergunta]) -> bool:
    """Mesmo conjunto de respostas, sem depender de ordem (issue #32).

    A ordenação do JS (code units UTF-16) e a do Python (code points) diferem
    fora do BMP, mas não muda o resultado: com os dois lados ordenados do mesmo
    jeito, comparar posição a posição é comparar multiconjuntos."""
    if len(a) != len(b):
        return False
    textos_a = sorted(_js.trim_js(o["resposta"]).upper() for o in a)
    textos_b = sorted(_js.trim_js(o["resposta"]).upper() for o in b)
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


_construtor = StateGraph(OrquestradorState)
_construtor.add_node("classificar", classificar)
_construtor.add_node("identificado", identificado)
_construtor.add_node("naoIdentificado", nao_identificado)
_construtor.add_node("prepararPerguntaDesambiguacao", preparar_pergunta_desambiguacao)
_construtor.add_node("pedirDesambiguacao", pedir_desambiguacao)
_construtor.add_edge(START, "classificar")
_construtor.add_conditional_edges(
    "classificar",
    depois_de_classificar,
    {"nenhum": "naoIdentificado", "um": "identificado", "muitos": "prepararPerguntaDesambiguacao"},
)
_construtor.add_edge("prepararPerguntaDesambiguacao", "pedirDesambiguacao")
_construtor.add_edge("pedirDesambiguacao", "classificar")
_construtor.add_edge("identificado", END)
_construtor.add_edge("naoIdentificado", END)

_fabrica = FabricaGrafo(_construtor)
criar_grafo = _fabrica.criar


def obter_grafo() -> GrafoCompilado:
    return _fabrica.obter()
