"""Fluxo Problemas com plano de saúde (NUDECON, issue #329).

Etapa atual: canal ("aqui", e-mail ou presencial) e "para quem". Presencial
encerra com a orientação; "outra pessoa" encerra com o texto provisório e
`atendimento_humano` (coleta dos dados dela: #347). "Para mim" ainda conclui
com a mensagem provisória, porque imagens, renda e confirmação vêm nas próximas
etapas da #329.

A pergunta do canal é de texto, com as opções escritas na própria pergunta: o
tipo `opcoes` ainda está por confirmar com a Tykhe (#336).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.fluxos._fabrica import FabricaGrafo, GrafoCompilado
from maria.fluxos.plano_saude.api import (
    HORARIO_NUDECON,
    MENSAGEM_CANAL_NAO_ENTENDIDO,
    MENSAGEM_CONCLUIDO,
    MENSAGEM_OUTRA_PESSOA,
    MENSAGEM_PRESENCIAL,
)
from maria.fluxos.plano_saude.state import CanalAtendimento, PlanoSaudeState
from maria.ia.reescrever import preparar_pergunta
from maria.shared.respostas import resposta_eh_sim

MAXIMO_TENTATIVAS_CANAL = 3

TEXTO_CANAL = f"O NUDECON atende {HORARIO_NUDECON}. Como você prefere seguir o atendimento: por aqui, por e-mail ou presencialmente?"
TEXTO_CANAL_NOVAMENTE = "Não entendi. Você prefere seguir por aqui, por e-mail ou presencialmente?"
TEXTO_PARA_QUEM = "O atendimento é para você? Responda não se for para outra pessoa."

Atualizacao = dict[str, Any]


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def interpretar_canal(resposta: str) -> CanalAtendimento | None:
    """O canal escolhido na resposta livre, ou `None` quando não dá para saber.
    Mais de um canal citado também é `None`: a pessoa precisa escolher um."""
    texto = _sem_acento(resposta)
    achados: set[CanalAtendimento] = set()
    if re.search(r"presenc|pessoalmente|ir ate|na sede|no local", texto):
        achados.add("presencial")
    if re.search(r"e-?mail|correio eletronico", texto):
        achados.add("email")
    if re.search(r"\baqui\b|whats|zap|mensagem|conversa|chat", texto):
        achados.add("aqui")
    return next(iter(achados)) if len(achados) == 1 else None


def texto_canal(state: PlanoSaudeState) -> str:
    return TEXTO_CANAL if not state.get("tentativasCanal") else TEXTO_CANAL_NOVAMENTE


async def preparar_pergunta_canal(state: PlanoSaudeState) -> Atualizacao:
    return dict(await preparar_pergunta("canal", texto_canal(state)))


async def pedir_canal(state: PlanoSaudeState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": state.get("perguntaAtualTexto") or texto_canal(state), "tipo": "texto"})
    canal = interpretar_canal(resposta)
    if canal is not None:
        return {"canal": canal}
    return {"canal": None, "tentativasCanal": (state.get("tentativasCanal") or 0) + 1}


def depois_do_canal(state: PlanoSaudeState) -> str:
    canal = state.get("canal")
    if canal == "presencial":
        return "presencial"
    if canal is not None:
        return "paraQuem"
    if (state.get("tentativasCanal") or 0) >= MAXIMO_TENTATIVAS_CANAL:
        return "canalNaoEntendido"
    return "canal"


async def presencial(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "concluido", "mensagemFinal": MENSAGEM_PRESENCIAL}


async def canal_nao_entendido(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "canal_nao_entendido", "mensagemFinal": MENSAGEM_CANAL_NAO_ENTENDIDO}


async def preparar_pergunta_para_quem(state: PlanoSaudeState) -> Atualizacao:
    return dict(await preparar_pergunta("paraSi", TEXTO_PARA_QUEM))


async def pedir_para_quem(state: PlanoSaudeState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": state.get("perguntaAtualTexto") or TEXTO_PARA_QUEM, "tipo": "sim_nao", "opcoes": ["Sim", "Não"]})
    return {"paraSi": resposta_eh_sim(resposta)}


def depois_de_para_quem(state: PlanoSaudeState) -> str:
    return "concluir" if state.get("paraSi") else "outraPessoa"


async def outra_pessoa(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "outra_pessoa", "mensagemFinal": MENSAGEM_OUTRA_PESSOA}


async def concluir(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "concluido", "mensagemFinal": MENSAGEM_CONCLUIDO}


_construtor = StateGraph(PlanoSaudeState)
_construtor.add_node("prepararPerguntaCanal", preparar_pergunta_canal)
_construtor.add_node("pedirCanal", pedir_canal)
_construtor.add_node("presencial", presencial)
_construtor.add_node("canalNaoEntendido", canal_nao_entendido)
_construtor.add_node("prepararPerguntaParaQuem", preparar_pergunta_para_quem)
_construtor.add_node("pedirParaQuem", pedir_para_quem)
_construtor.add_node("outraPessoa", outra_pessoa)
_construtor.add_node("concluir", concluir)
_construtor.add_edge(START, "prepararPerguntaCanal")
_construtor.add_edge("prepararPerguntaCanal", "pedirCanal")
_construtor.add_conditional_edges(
    "pedirCanal",
    depois_do_canal,
    {
        "presencial": "presencial",
        "paraQuem": "prepararPerguntaParaQuem",
        "canalNaoEntendido": "canalNaoEntendido",
        "canal": "prepararPerguntaCanal",
    },
)
_construtor.add_edge("prepararPerguntaParaQuem", "pedirParaQuem")
_construtor.add_conditional_edges("pedirParaQuem", depois_de_para_quem, {"concluir": "concluir", "outraPessoa": "outraPessoa"})
for _fim in ("presencial", "canalNaoEntendido", "outraPessoa", "concluir"):
    _construtor.add_edge(_fim, END)

_fabrica = FabricaGrafo(_construtor)
criar_grafo = _fabrica.criar


def obter_grafo() -> GrafoCompilado:
    return _fabrica.obter()
