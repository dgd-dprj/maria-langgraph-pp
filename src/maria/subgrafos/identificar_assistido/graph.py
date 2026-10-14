"""Subgrafo `identificar_assistido` (develop: `subgrafos/identificarAssistido/graph.ts`, issues #171, #172, #189, #191).

Pergunta o CPF, consulta o Verde e dá até 3 tentativas. Três desfechos, que o
pai decide olhando `dadosPessoa.encontrado` e `confirmaAssistido`:
- encontrado e confirmado;
- encontrado e não confirmado (#189);
- esgotado: não encontrado, ou "não" para tentar de novo, ou falha de infra.

Nenhum vira handoff aqui; isso fica com o fluxo pai.
"""

from __future__ import annotations

import re
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.ia.reescrever import preparar_pergunta
from maria.integracoes.verde import consultar_pessoa_por_cpf
from maria.shared import _js
from maria.shared.respostas import resposta_eh_sim
from maria.subgrafos.identificar_assistido.state import IdentificarAssistidoState

TEXTO_CPF = "Qual o seu CPF? Informe apenas os números."

Atualizacao = dict[str, Any]

# `\D` de JS sem a flag `u` é "não for 0-9 ASCII". O `\D` do Python aceita
# dígitos de qualquer alfabeto, por isso a classe explícita.
_NAO_DIGITO_ASCII = re.compile(r"[^0-9]")


def cpf_formato_valido(valor: str) -> bool:
    return len(_NAO_DIGITO_ASCII.sub("", valor)) == 11


def _tentativas(state: IdentificarAssistidoState) -> int:
    tentativas: int = _js.coalesce(state.get("tentativasCpf"), 0)
    return tentativas


def cpf_veio_de_dados_conhecidos(state: IdentificarAssistidoState) -> bool:
    # Bypass só na tentativa 0: um retry não pode reusar o CPF que falhou.
    # `state.cpf !== undefined` de develop: develop nunca grava undefined em
    # `cpf`, então a AUSÊNCIA da chave é o undefined, e `None` é um null vindo
    # da Tykhe (dadosConhecidos), que em develop também pula a pergunta e
    # consulta "" (regra de estado, tabela da spec do fluxos).
    return "cpf" in state and _tentativas(state) == 0


def texto_tentar_novamente(state: IdentificarAssistidoState) -> str:
    tentativa = _js.coalesce(state.get("tentativasCpf"), 1)
    return f"Não encontrei ninguém com esse CPF (tentativa {_js.texto_template(tentativa)} de 3). Quer tentar de novo?"


def texto_confirma_assistido(state: IdentificarAssistidoState) -> str:
    nome = _js.coalesce(_js.opt(state.get("dadosPessoa", _js.AUSENTE), "nome"), "você")
    return f"Confirma que seus dados são: {_js.texto_template(nome)}?"


def _dados_pessoa(state: IdentificarAssistidoState, chave: str) -> Any:
    # `state.dadosPessoa?.<chave>`
    return _js.opt(state.get("dadosPessoa", _js.AUSENTE), chave)


async def preparar_pergunta_cpf(state: IdentificarAssistidoState) -> Atualizacao:
    if cpf_veio_de_dados_conhecidos(state):
        return {}
    return dict(await preparar_pergunta("cpf", TEXTO_CPF))


async def pedir_cpf(state: IdentificarAssistidoState) -> Atualizacao:
    if cpf_veio_de_dados_conhecidos(state):
        return {}
    # Sem validação de formato: o valor é gravado como veio (achado A5).
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_CPF), "tipo": "texto"})
    return {"cpf": resposta}


async def consultar_pessoa(state: IdentificarAssistidoState) -> Atualizacao:
    dados = await consultar_pessoa_por_cpf(_js.coalesce(state.get("cpf"), ""))
    return {"dadosPessoa": dados, "tentativasCpf": _tentativas(state) + 1}


def depois_de_consultar_pessoa(state: IdentificarAssistidoState) -> str:
    if _js.verdadeiro(_dados_pessoa(state, "encontrado")):
        return "encontrado"
    # Issue #172: falha de infra sai direto, sem o "quer tentar de novo?".
    if _js.verdadeiro(_dados_pessoa(state, "falhaInfra")):
        return "esgotado"
    return "esgotado" if _tentativas(state) >= 3 else "tentarNovamente"


async def preparar_pergunta_tentar_novamente_cpf(state: IdentificarAssistidoState) -> Atualizacao:
    return dict(await preparar_pergunta("tentarNovamenteCpf", texto_tentar_novamente(state)))


async def pergunta_tentar_novamente_cpf(state: IdentificarAssistidoState) -> Atualizacao:
    resposta: str = interrupt(
        {
            "pergunta": _js.coalesce(state.get("perguntaAtualTexto"), texto_tentar_novamente(state)),
            "tipo": "sim_nao",
            "opcoes": ["Sim", "Não"],
        }
    )
    if cpf_formato_valido(resposta):
        # CPF digitado direto no retry: gravado como veio, com pontuação.
        return {"querTentarNovamenteCpf": True, "cpf": resposta, "digitouCpfDireto": True}
    return {"querTentarNovamenteCpf": resposta_eh_sim(resposta), "digitouCpfDireto": False}


def depois_de_pergunta_tentar_cpf(state: IdentificarAssistidoState) -> str:
    if not _js.verdadeiro(state.get("querTentarNovamenteCpf", _js.AUSENTE)):
        return "esgotado"
    return "consultarPessoa" if _js.verdadeiro(state.get("digitouCpfDireto", _js.AUSENTE)) else "pedirCpf"


async def preparar_pergunta_confirma_assistido(state: IdentificarAssistidoState) -> Atualizacao:
    # Issue #191: só pergunta quando veio do orquestrador.
    if not _js.verdadeiro(state.get("viaOrquestrador", _js.AUSENTE)):
        return {}
    return dict(await preparar_pergunta("confirmaAssistido", texto_confirma_assistido(state)))


async def pedir_confirma_assistido(state: IdentificarAssistidoState) -> Atualizacao:
    if not _js.verdadeiro(state.get("viaOrquestrador", _js.AUSENTE)):
        return {}
    resposta: str = interrupt(
        {
            "pergunta": _js.coalesce(state.get("perguntaAtualTexto"), texto_confirma_assistido(state)),
            "tipo": "sim_nao",
            "opcoes": ["Sim", "Não"],
        }
    )
    return {"confirmaAssistido": resposta_eh_sim(resposta)}


_construtor = StateGraph(IdentificarAssistidoState)
_construtor.add_node("prepararPerguntaCpf", preparar_pergunta_cpf)
_construtor.add_node("pedirCpf", pedir_cpf)
_construtor.add_node("consultarPessoa", consultar_pessoa)
_construtor.add_node("prepararPerguntaTentarNovamenteCpf", preparar_pergunta_tentar_novamente_cpf)
_construtor.add_node("perguntaTentarNovamenteCpf", pergunta_tentar_novamente_cpf)
_construtor.add_node("prepararPerguntaConfirmaAssistido", preparar_pergunta_confirma_assistido)
_construtor.add_node("pedirConfirmaAssistido", pedir_confirma_assistido)
_construtor.add_edge(START, "prepararPerguntaCpf")
_construtor.add_edge("prepararPerguntaCpf", "pedirCpf")
_construtor.add_edge("pedirCpf", "consultarPessoa")
_construtor.add_conditional_edges(
    "consultarPessoa",
    depois_de_consultar_pessoa,
    {"encontrado": "prepararPerguntaConfirmaAssistido", "esgotado": END, "tentarNovamente": "prepararPerguntaTentarNovamenteCpf"},
)
_construtor.add_edge("prepararPerguntaTentarNovamenteCpf", "perguntaTentarNovamenteCpf")
_construtor.add_conditional_edges(
    "perguntaTentarNovamenteCpf",
    depois_de_pergunta_tentar_cpf,
    {"pedirCpf": "prepararPerguntaCpf", "esgotado": END, "consultarPessoa": "consultarPessoa"},
)
_construtor.add_edge("prepararPerguntaConfirmaAssistido", "pedirConfirmaAssistido")
_construtor.add_edge("pedirConfirmaAssistido", END)

# Sem checkpointer próprio: embutido como nó, herda o do pai (como develop).
grafo = _construtor.compile()
