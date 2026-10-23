"""Subgrafo `coletar_endereco` (develop: `subgrafos/coletarEndereco/graph.ts`, issue #176).

Pergunta o CEP, consulta o Verde e pergunta só o que o CEP não trouxe. Número e
complemento são sempre perguntados. O bypass fica dentro dos nós (devolvem `{}`),
e não nas arestas, como em develop: a topologia é linear.

Regra de estado (#208): quando develop grava `undefined` num canal, aqui é
`None`; `None` conta como "ausente" nos testes de bypass (`!== undefined` em
develop). Dentro do `endereco`, que vai inteiro no POST ao Verde, o `undefined`
de develop é chave ausente, porque o `JSON.stringify` a remove.
"""

from __future__ import annotations

import itertools
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.ia.reescrever import preparar_pergunta
from maria.integracoes.verde import consultar_cep as consultar_cep_verde
from maria.shared import _js
from maria.shared._js import trim_js
from maria.subgrafos.coletar_endereco.state import ColetarEnderecoState

TEXTO_CEP = "Qual o CEP do seu endereço?"
TEXTO_LOGRADOURO = "Qual o nome da rua/avenida?"
TEXTO_NUMERO = "Qual o número?"
TEXTO_COMPLEMENTO = 'Tem complemento (apartamento, bloco, etc)? Se não tiver, pode responder "não".'
TEXTO_BAIRRO = "Qual o bairro?"
TEXTO_MUNICIPIO = "Qual o município?"
TEXTO_UF = "Qual o estado (UF, ex: RJ)?"

Atualizacao = dict[str, Any]


def _perguntar_texto(state: ColetarEnderecoState, padrao: str) -> str:
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), padrao), "tipo": "texto"})
    return resposta


async def preparar_pergunta_cep(state: ColetarEnderecoState) -> Atualizacao:
    return dict(await preparar_pergunta("cep", TEXTO_CEP))


async def pedir_cep(state: ColetarEnderecoState) -> Atualizacao:
    return {"cep": _perguntar_texto(state, TEXTO_CEP)}


async def consultar_cep(state: ColetarEnderecoState) -> Atualizacao:
    dados = await consultar_cep_verde(_js.coalesce(state.get("cep"), ""))
    if not dados["encontrado"]:
        return {}
    # Chave ausente no resultado do Verde = undefined em develop, que é
    # gravado no canal: aqui vira None.
    return {
        "logradouro": dados.get("logradouro"),
        "bairro": dados.get("bairro"),
        "municipio": dados.get("municipio"),
        "uf": dados.get("uf"),
    }


async def preparar_pergunta_logradouro(state: ColetarEnderecoState) -> Atualizacao:
    if state.get("logradouro") is not None:
        return {}
    return dict(await preparar_pergunta("logradouro", TEXTO_LOGRADOURO))


async def pedir_logradouro(state: ColetarEnderecoState) -> Atualizacao:
    if state.get("logradouro") is not None:
        return {}
    return {"logradouro": _perguntar_texto(state, TEXTO_LOGRADOURO)}


async def preparar_pergunta_numero(state: ColetarEnderecoState) -> Atualizacao:
    return dict(await preparar_pergunta("numero", TEXTO_NUMERO))


async def pedir_numero(state: ColetarEnderecoState) -> Atualizacao:
    return {"numero": _perguntar_texto(state, TEXTO_NUMERO)}


async def preparar_pergunta_complemento(state: ColetarEnderecoState) -> Atualizacao:
    return dict(await preparar_pergunta("complemento", TEXTO_COMPLEMENTO))


def sem_complemento(resposta: str) -> bool:
    """`resposta.trim().toLowerCase()` em {"não", "nao", "n", ""}, SEM normalização
    NFD (ao contrário de `resposta_eh_sim`): um "não" decomposto não casa."""
    return trim_js(resposta).lower() in ("não", "nao", "n", "")


async def pedir_complemento(state: ColetarEnderecoState) -> Atualizacao:
    resposta = _perguntar_texto(state, TEXTO_COMPLEMENTO)
    # Grava a resposta original (sem trim), como develop; "não" grava undefined.
    return {"complemento": None if sem_complemento(resposta) else resposta}


async def preparar_pergunta_bairro(state: ColetarEnderecoState) -> Atualizacao:
    if state.get("bairro") is not None:
        return {}
    return dict(await preparar_pergunta("bairro", TEXTO_BAIRRO))


async def pedir_bairro(state: ColetarEnderecoState) -> Atualizacao:
    if state.get("bairro") is not None:
        return {}
    return {"bairro": _perguntar_texto(state, TEXTO_BAIRRO)}


async def preparar_pergunta_municipio(state: ColetarEnderecoState) -> Atualizacao:
    if state.get("municipio") is not None:
        return {}
    return dict(await preparar_pergunta("municipio", TEXTO_MUNICIPIO))


async def pedir_municipio(state: ColetarEnderecoState) -> Atualizacao:
    if state.get("municipio") is not None:
        return {}
    return {"municipio": _perguntar_texto(state, TEXTO_MUNICIPIO)}


async def preparar_pergunta_uf(state: ColetarEnderecoState) -> Atualizacao:
    if state.get("uf") is not None:
        return {}
    return dict(await preparar_pergunta("uf", TEXTO_UF))


async def pedir_uf(state: ColetarEnderecoState) -> Atualizacao:
    if state.get("uf") is not None:
        return {}
    return {"uf": trim_js(_perguntar_texto(state, TEXTO_UF)).upper()}


async def montar_endereco(state: ColetarEnderecoState) -> Atualizacao:
    endereco: dict[str, Any] = {}
    for chave in ("cep", "logradouro", "numero", "complemento", "bairro", "municipio", "uf"):
        valor = state.get(chave)
        # Dentro do objeto aninhado, undefined de develop = chave ausente
        # (some no JSON.stringify do POST /pessoa). Ver o MIGRACAO.md.
        _js.definir(endereco, chave, _js.AUSENTE if valor is None else valor)
    return {"endereco": endereco}


_construtor = StateGraph(ColetarEnderecoState)
for _nome, _no in (
    ("prepararPerguntaCep", preparar_pergunta_cep),
    ("pedirCep", pedir_cep),
    ("consultarCep", consultar_cep),
    ("prepararPerguntaLogradouro", preparar_pergunta_logradouro),
    ("pedirLogradouro", pedir_logradouro),
    ("prepararPerguntaNumero", preparar_pergunta_numero),
    ("pedirNumero", pedir_numero),
    ("prepararPerguntaComplemento", preparar_pergunta_complemento),
    ("pedirComplemento", pedir_complemento),
    ("prepararPerguntaBairro", preparar_pergunta_bairro),
    ("pedirBairro", pedir_bairro),
    ("prepararPerguntaMunicipio", preparar_pergunta_municipio),
    ("pedirMunicipio", pedir_municipio),
    ("prepararPerguntaUf", preparar_pergunta_uf),
    ("pedirUf", pedir_uf),
    ("montarEndereco", montar_endereco),
):
    _construtor.add_node(_nome, _no)

_ORDEM = (
    START,
    "prepararPerguntaCep",
    "pedirCep",
    "consultarCep",
    "prepararPerguntaLogradouro",
    "pedirLogradouro",
    "prepararPerguntaNumero",
    "pedirNumero",
    "prepararPerguntaComplemento",
    "pedirComplemento",
    "prepararPerguntaBairro",
    "pedirBairro",
    "prepararPerguntaMunicipio",
    "pedirMunicipio",
    "prepararPerguntaUf",
    "pedirUf",
    "montarEndereco",
    END,
)
for _origem, _destino in itertools.pairwise(_ORDEM):
    _construtor.add_edge(_origem, _destino)

# Sem checkpointer próprio: embutido como nó, herda o do pai (como develop).
grafo = _construtor.compile()
