"""Subgrafo `identificar_assistido` (develop: `subgrafos/identificarAssistido/graph.ts`, issues #171, #172, #189, #191).

Pergunta o CPF, consulta o Verde e dá até 3 tentativas. Três desfechos, que o
pai decide olhando `dadosPessoa.encontrado` e `confirmaAssistido`:
- encontrado e confirmado;
- encontrado e não confirmado (#189);
- esgotado: não encontrado, ou "não" para tentar de novo, ou falha de infra.

A confirmação só existe pelo orquestrador (#191) e com o CPF digitado na
conversa. Com o CPF vindo da Tykhe, não há confirmação (#236, decisão de 03/11).

A confirmação mostra o nome mascarado (primeiro nome e iniciais) e prefere o
nome social (#393).

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
from maria.shared.contexto import contexto_atual
from maria.shared.cpf import cpf_valido
from maria.shared.logger import logger
from maria.shared.nomes import nome_mascarado
from maria.shared.respostas import resposta_eh_sim
from maria.subgrafos.identificar_assistido.state import IdentificarAssistidoState

TEXTO_CPF = "Qual o seu CPF? Informe apenas os números."
# #497 (decisão da Nicole, 2026-11-16): o CPF com a conta dos dígitos verificadores errada não vai ao Verde. O mesmo
# texto vai para a Tykhe usar no fluxo dela.
TEXTO_CPF_INVALIDO = "Esse CPF não está certo. Confira os 11 números e escreva de novo."

Atualizacao = dict[str, Any]

# `\D` de JS sem a flag `u` é "não for 0-9 ASCII". O `\D` do Python aceita
# dígitos de qualquer alfabeto, por isso a classe explícita.
_NAO_DIGITO_ASCII = re.compile(r"[^0-9]")


def cpf_formato_valido(valor: str) -> bool:
    return len(_NAO_DIGITO_ASCII.sub("", valor)) == 11


def cpf_digitado_invalido(state: IdentificarAssistidoState) -> bool:
    """#497: o CPF digitado na conversa não fecha a conta dos dígitos verificadores. Vale só para o que a pessoa
    digitou: o CPF que veio da Tykhe (`dadosConhecidos`) segue para o Verde como antes, sem mudar o contrato."""
    cpf = state.get("cpf")
    if state.get("cpfDaTykhe") or not isinstance(cpf, str):
        return False
    return not cpf_valido(_NAO_DIGITO_ASCII.sub("", cpf))


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
    # #393: quem digita o CPF de outra pessoa não pode ver o nome completo do titular. A
    # confirmação mostra o nome mascarado, e o nome social quando o Verde tiver um.
    dados = state.get("dadosPessoa", _js.AUSENTE)
    for campo in ("nomeSocial", "nome"):
        valor = _js.opt(dados, campo)
        if isinstance(valor, str) and valor.strip():
            return f"Confirma que seus dados são: {nome_mascarado(valor)}?"
    # Sem nome em texto, como antes: `nome ?? "você"`.
    nome = _js.coalesce(_js.opt(dados, "nome"), "você")
    return f"Confirma que seus dados são: {_js.texto_template(nome)}?"


def _dados_pessoa(state: IdentificarAssistidoState, chave: str) -> Any:
    # `state.dadosPessoa?.<chave>`
    return _js.opt(state.get("dadosPessoa", _js.AUSENTE), chave)


async def preparar_pergunta_cpf(state: IdentificarAssistidoState) -> Atualizacao:
    if cpf_veio_de_dados_conhecidos(state):
        return {}
    # #497: depois de um CPF recusado pela conta, a pergunta diz o que houve.
    return dict(await preparar_pergunta("cpf", TEXTO_CPF_INVALIDO if cpf_digitado_invalido(state) else TEXTO_CPF))


async def pedir_cpf(state: IdentificarAssistidoState) -> Atualizacao:
    if cpf_veio_de_dados_conhecidos(state):
        return {"cpfDaTykhe": True}
    # O valor é gravado como veio (achado A5); desde a #497, a conta dos dígitos verificadores decide se vai ao Verde.
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_CPF), "tipo": "texto"})
    return {"cpf": resposta, "cpfDaTykhe": False}


def depois_de_pedir_cpf(state: IdentificarAssistidoState) -> str:
    return "invalido" if cpf_digitado_invalido(state) else "consultar"


async def recusar_cpf(state: IdentificarAssistidoState) -> Atualizacao:
    """#497: conta a tentativa sem consultar o Verde e registra o evento, sem o número."""
    tentativa = _tentativas(state) + 1
    logger.info("CPF recusado pelos dígitos verificadores", **contexto_atual(), evento="cpf_digito_invalido", tentativa=tentativa)
    return {"tentativasCpf": tentativa}


def depois_de_recusar_cpf(state: IdentificarAssistidoState) -> str:
    return "esgotado" if _tentativas(state) >= 3 else "pedirCpf"


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
        return {"querTentarNovamenteCpf": True, "cpf": resposta, "digitouCpfDireto": True, "cpfDaTykhe": False}
    return {"querTentarNovamenteCpf": resposta_eh_sim(resposta), "digitouCpfDireto": False}


def depois_de_pergunta_tentar_cpf(state: IdentificarAssistidoState) -> str:
    if not _js.verdadeiro(state.get("querTentarNovamenteCpf", _js.AUSENTE)):
        return "esgotado"
    if not _js.verdadeiro(state.get("digitouCpfDireto", _js.AUSENTE)):
        return "pedirCpf"
    # #497: os 11 dígitos digitados direto passam pela mesma conta.
    return "recusarCpf" if cpf_digitado_invalido(state) else "consultarPessoa"


def pergunta_confirma_assistido(state: IdentificarAssistidoState) -> bool:
    # Issue #191: só pergunta quando veio do orquestrador.
    # Issue #236 (decisão de 03/11): com o CPF vindo da Tykhe, não pergunta.
    # A pessoa já se identificou lá, e a pergunta mostraria o nome do titular.
    # Com o CPF digitado na conversa, a confirmação continua como antes.
    return _js.verdadeiro(state.get("viaOrquestrador", _js.AUSENTE)) and not state.get("cpfDaTykhe", False)


async def preparar_pergunta_confirma_assistido(state: IdentificarAssistidoState) -> Atualizacao:
    if not pergunta_confirma_assistido(state):
        return {}
    return dict(await preparar_pergunta("confirmaAssistido", texto_confirma_assistido(state)))


async def pedir_confirma_assistido(state: IdentificarAssistidoState) -> Atualizacao:
    if not pergunta_confirma_assistido(state):
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
_construtor.add_node("recusarCpf", recusar_cpf)
_construtor.add_node("consultarPessoa", consultar_pessoa)
_construtor.add_node("prepararPerguntaTentarNovamenteCpf", preparar_pergunta_tentar_novamente_cpf)
_construtor.add_node("perguntaTentarNovamenteCpf", pergunta_tentar_novamente_cpf)
_construtor.add_node("prepararPerguntaConfirmaAssistido", preparar_pergunta_confirma_assistido)
_construtor.add_node("pedirConfirmaAssistido", pedir_confirma_assistido)
_construtor.add_edge(START, "prepararPerguntaCpf")
_construtor.add_edge("prepararPerguntaCpf", "pedirCpf")
_construtor.add_conditional_edges("pedirCpf", depois_de_pedir_cpf, {"consultar": "consultarPessoa", "invalido": "recusarCpf"})
_construtor.add_conditional_edges("recusarCpf", depois_de_recusar_cpf, {"pedirCpf": "prepararPerguntaCpf", "esgotado": END})
_construtor.add_conditional_edges(
    "consultarPessoa",
    depois_de_consultar_pessoa,
    {"encontrado": "prepararPerguntaConfirmaAssistido", "esgotado": END, "tentarNovamente": "prepararPerguntaTentarNovamenteCpf"},
)
_construtor.add_edge("prepararPerguntaTentarNovamenteCpf", "perguntaTentarNovamenteCpf")
_construtor.add_conditional_edges(
    "perguntaTentarNovamenteCpf",
    depois_de_pergunta_tentar_cpf,
    {"pedirCpf": "prepararPerguntaCpf", "esgotado": END, "consultarPessoa": "consultarPessoa", "recusarCpf": "recusarCpf"},
)
_construtor.add_edge("prepararPerguntaConfirmaAssistido", "pedirConfirmaAssistido")
_construtor.add_edge("pedirConfirmaAssistido", END)

# Sem checkpointer próprio: embutido como nó, herda o do pai (como develop).
grafo = _construtor.compile()
