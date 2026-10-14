"""Subgrafo `cadastro_pessoa` (develop: `subgrafos/cadastroPessoa/graph.ts`, issues #171, #176, #189).

Cadastra no Verde quem não foi encontrado pelo CPF: pergunta nome e data de
nascimento, coleta o endereço (subgrafo `coletar_endereco` embutido como nó) e
faz o POST `/pessoa`. Quando vem do orquestrador, confirma os dados.

Reproduzido de develop, com issues abertas para depois da migração:
- o endereço coletado não volta ao pai: o `dadosPessoa` do cadastro não tem
  `enderecoDetalhado` (#231);
- a soma de tokens se compõe com o subgrafo aninhado (#230).
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.ia.reescrever import preparar_pergunta
from maria.integracoes.verde import DadosCadastroPessoa
from maria.integracoes.verde import cadastrar_pessoa as cadastrar_pessoa_verde
from maria.shared import _js
from maria.shared.respostas import resposta_eh_sim
from maria.subgrafos.cadastro_pessoa.state import CadastroPessoaState
from maria.subgrafos.coletar_endereco.graph import grafo as subgrafo_coletar_endereco

TEXTO_NOME = "Não encontrei seu cadastro no sistema. Pra criar um novo, qual o seu nome completo?"
TEXTO_DATA_NASCIMENTO = "Qual a sua data de nascimento? (dd/mm/aaaa)"

Atualizacao = dict[str, Any]


def texto_confirma_assistido(state: CadastroPessoaState) -> str:
    # `state.dadosPessoa?.nome ?? "você"` de develop.
    nome = _js.coalesce(_js.opt(state.get("dadosPessoa", _js.AUSENTE), "nome"), "você")
    return f"Confirma que seus dados são: {_js.texto_template(nome)}?"


async def preparar_pergunta_nome(state: CadastroPessoaState) -> Atualizacao:
    return dict(await preparar_pergunta("nome", TEXTO_NOME))


async def pedir_nome(state: CadastroPessoaState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_NOME), "tipo": "texto"})
    return {"nome": resposta}


async def preparar_pergunta_data_nascimento(state: CadastroPessoaState) -> Atualizacao:
    return dict(await preparar_pergunta("dataNascimento", TEXTO_DATA_NASCIMENTO))


async def pedir_data_nascimento(state: CadastroPessoaState) -> Atualizacao:
    # Sem validação de formato, como develop (achado A5 da spec).
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_DATA_NASCIMENTO), "tipo": "texto"})
    return {"dataNascimento": resposta}


async def cadastrar_pessoa(state: CadastroPessoaState) -> Atualizacao:
    dados: DadosCadastroPessoa = {
        "nome": _js.coalesce(state.get("nome"), ""),
        "cpf": _js.coalesce(state.get("cpf"), ""),
        "dataNascimento": _js.coalesce(state.get("dataNascimento"), ""),
    }
    # `endereco: state.endereco` em develop; o Verde só inclui a chave no corpo
    # quando o endereço é verdadeiro, então ausente aqui = ausente lá.
    endereco = state.get("endereco")
    if endereco is not None:
        dados["endereco"] = endereco
    resultado = await cadastrar_pessoa_verde(dados)
    if not resultado["sucesso"]:
        return {"cadastroErro": _js.coalesce(resultado.get("erro"), "erro desconhecido")}
    # Mesmo formato que o identificar_assistido preenche quando encontra; sem
    # enderecoDetalhado (#231). Objeto aninhado: undefined de develop é chave
    # ausente, e null continua null (regra de estado, MIGRACAO.md).
    # - idPessoa: no sucesso, o Verde sempre traz a chave; `"idPessoa": null`
    #   continua None, como o null de develop (o guarda lá é `=== undefined`).
    # - nome: develop nunca grava undefined no canal; ausência da chave é o
    #   undefined (não vai para o objeto), e None é null (vai como null).
    dados_pessoa: dict[str, Any] = {"encontrado": True, "idPessoa": resultado.get("idPessoa")}
    if "nome" in state:
        dados_pessoa["nome"] = state["nome"]
    return {"dadosPessoa": dados_pessoa}


def depois_de_cadastrar(state: CadastroPessoaState) -> str:
    # `state.cadastroErro !== undefined`
    return "falhou" if state.get("cadastroErro") is not None else "sucesso"


async def preparar_pergunta_confirma_assistido(state: CadastroPessoaState) -> Atualizacao:
    if not _js.verdadeiro(state.get("viaOrquestrador", _js.AUSENTE)):
        return {}
    return dict(await preparar_pergunta("confirmaAssistido", texto_confirma_assistido(state)))


async def pedir_confirma_assistido(state: CadastroPessoaState) -> Atualizacao:
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


_construtor = StateGraph(CadastroPessoaState)
_construtor.add_node("prepararPerguntaNome", preparar_pergunta_nome)
_construtor.add_node("pedirNome", pedir_nome)
_construtor.add_node("prepararPerguntaDataNascimento", preparar_pergunta_data_nascimento)
_construtor.add_node("pedirDataNascimento", pedir_data_nascimento)
# Subgrafo aninhado (issue #176), como em develop.
_construtor.add_node("coletarEndereco", subgrafo_coletar_endereco)
_construtor.add_node("cadastrarPessoa", cadastrar_pessoa)
_construtor.add_node("prepararPerguntaConfirmaAssistido", preparar_pergunta_confirma_assistido)
_construtor.add_node("pedirConfirmaAssistido", pedir_confirma_assistido)
_construtor.add_edge(START, "prepararPerguntaNome")
_construtor.add_edge("prepararPerguntaNome", "pedirNome")
_construtor.add_edge("pedirNome", "prepararPerguntaDataNascimento")
_construtor.add_edge("prepararPerguntaDataNascimento", "pedirDataNascimento")
_construtor.add_edge("pedirDataNascimento", "coletarEndereco")
_construtor.add_edge("coletarEndereco", "cadastrarPessoa")
_construtor.add_conditional_edges("cadastrarPessoa", depois_de_cadastrar, {"sucesso": "prepararPerguntaConfirmaAssistido", "falhou": END})
_construtor.add_edge("prepararPerguntaConfirmaAssistido", "pedirConfirmaAssistido")
_construtor.add_edge("pedirConfirmaAssistido", END)

# Sem checkpointer próprio, como identificar_assistido.
grafo = _construtor.compile()
