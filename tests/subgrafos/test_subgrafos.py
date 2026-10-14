"""Testes novos da spec do módulo subgrafos (seção 7), com o Verde em modo mock,
salvo o teste 8, que passa pelo `cadastrar_pessoa` real com o transporte falso.
"""

import itertools
import json
from typing import Any, TypedDict

import pytest
from langgraph.graph.state import CompiledStateGraph

from maria.shared._js import trim_js
from maria.shared.respostas import resposta_eh_sim
from maria.shared.tokens_acumulados import CanalTokensGastos
from maria.shared.types import DadosPessoa
from maria.subgrafos.cadastro_pessoa.graph import grafo as cadastro_pessoa
from maria.subgrafos.cadastro_pessoa.state import CadastroPessoaState
from maria.subgrafos.coletar_endereco.graph import grafo as coletar_endereco
from maria.subgrafos.coletar_endereco.state import ColetarEnderecoState
from maria.subgrafos.identificar_assistido.graph import cpf_formato_valido
from maria.subgrafos.identificar_assistido.graph import grafo as identificar_assistido
from maria.subgrafos.identificar_assistido.state import IdentificarAssistidoState
from tests.integracoes.conftest import TransporteFalso
from tests.subgrafos.conftest import Conversa, envelope

SEMENTE = {"input": 100, "output": 50, "total": 150}

# ---- teste 1: topologia igual à de develop -------------------------------------


def _arestas(grafo: CompiledStateGraph[Any, Any, Any, Any]) -> set[tuple[str, str]]:
    return {(a.source, a.target) for a in grafo.get_graph().edges}


def test_1_topologia_identificar_assistido() -> None:
    assert _arestas(identificar_assistido) == {
        ("__start__", "prepararPerguntaCpf"),
        ("prepararPerguntaCpf", "pedirCpf"),
        ("pedirCpf", "consultarPessoa"),
        ("consultarPessoa", "prepararPerguntaConfirmaAssistido"),
        ("consultarPessoa", "__end__"),
        ("consultarPessoa", "prepararPerguntaTentarNovamenteCpf"),
        ("prepararPerguntaTentarNovamenteCpf", "perguntaTentarNovamenteCpf"),
        ("perguntaTentarNovamenteCpf", "prepararPerguntaCpf"),
        ("perguntaTentarNovamenteCpf", "__end__"),
        ("perguntaTentarNovamenteCpf", "consultarPessoa"),
        ("prepararPerguntaConfirmaAssistido", "pedirConfirmaAssistido"),
        ("pedirConfirmaAssistido", "__end__"),
    }


def test_1_topologia_cadastro_pessoa() -> None:
    assert _arestas(cadastro_pessoa) == {
        ("__start__", "prepararPerguntaNome"),
        ("prepararPerguntaNome", "pedirNome"),
        ("pedirNome", "prepararPerguntaDataNascimento"),
        ("prepararPerguntaDataNascimento", "pedirDataNascimento"),
        ("pedirDataNascimento", "coletarEndereco"),
        ("coletarEndereco", "cadastrarPessoa"),
        ("cadastrarPessoa", "prepararPerguntaConfirmaAssistido"),
        ("cadastrarPessoa", "__end__"),
        ("prepararPerguntaConfirmaAssistido", "pedirConfirmaAssistido"),
        ("pedirConfirmaAssistido", "__end__"),
    }


def test_1_topologia_coletar_endereco_linear() -> None:
    ordem = [
        "__start__",
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
        "__end__",
    ]
    assert _arestas(coletar_endereco) == set(itertools.pairwise(ordem))


# ---- teste 2: payload dos interrupts ---------------------------------------------


async def test_2_interrupts_de_texto_sem_opcoes_e_sim_nao_com_opcoes() -> None:
    c = await Conversa(envelope(IdentificarAssistidoState, identificar_assistido)).iniciar({"viaOrquestrador": True})
    await c.responder("00000000000")  # não encontrado: pergunta de tentar de novo
    await c.responder("12345678901")  # CPF digitado direto: encontrado, confirmação
    cpf, tentar, confirma = c.perguntas
    assert cpf == {"pergunta": "Qual o seu CPF? Informe apenas os números.", "tipo": "texto"}
    assert "opcoes" not in cpf
    assert tentar["tipo"] == "sim_nao" and tentar["opcoes"] == ["Sim", "Não"]
    assert confirma["tipo"] == "sim_nao" and confirma["opcoes"] == ["Sim", "Não"]


# ---- testes 3, 4 e 5: texto ------------------------------------------------------


@pytest.mark.parametrize("resposta", ["true", "sim", "Sim", " s ", "SÍM", "yes", "﻿sim"])
def test_3_resposta_eh_sim_verdadeiro(resposta: str) -> None:
    assert resposta_eh_sim(resposta)


@pytest.mark.parametrize("resposta", ["sim.", "claro", "1", "", "não", "\x1csim"])
def test_3_resposta_eh_sim_falso(resposta: str) -> None:
    # "\x1csim": o trim() de JS não remove \x1c (o strip() do Python removeria).
    assert not resposta_eh_sim(resposta)


def test_4_trim_js() -> None:
    assert trim_js("﻿ a  ") == "a"
    assert trim_js("\x1ca\x1f") == "\x1ca\x1f"
    assert trim_js(" a　") == "a"


CPFS = [("123.456.789-01", True), ("12345678901", True), ("١٢٣٤٥٦٧٨٩٠١", False), ("1234567890", False)]


@pytest.mark.parametrize(("valor", "valido"), CPFS)
def test_5_cpf_formato_valido(valor: str, valido: bool) -> None:
    # Dígitos arábico-índicos: o \D de JS sem a flag u os remove; o \d do Python os aceitaria.
    assert cpf_formato_valido(valor) is valido


# ---- teste 8: o endereço no POST ao Verde ----------------------------------------


async def test_8_post_pessoa_sem_null_dentro_do_endereco(verde_real: TransporteFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    from maria.integracoes import verde

    # Endereço montado pelo subgrafo com o Verde em mock; o POST, com o Verde "real".
    monkeypatch.setattr(verde, "VERDE_JWT_TOKEN", "")
    c = await (await Conversa(envelope(ColetarEnderecoState, coletar_endereco)).iniciar({})).responder("20000000", "10", "não")
    endereco = (await c.estado())["endereco"]
    monkeypatch.setattr(verde, "VERDE_JWT_TOKEN", "token-de-teste")

    async def responder(requisicao: Any) -> Any:
        import httpx

        return httpx.Response(201, json={"dados": {"idPessoa": 7}})

    verde_real.tratador = responder
    await verde.cadastrar_pessoa({"nome": "Fulano", "cpf": "12345678901", "dataNascimento": "01/01/1990", "endereco": endereco})
    corpo = json.loads(verde_real.corpos[-1])
    assert "complemento" not in corpo["endereco"]
    assert None not in corpo["endereco"].values()
    assert b"null" not in verde_real.corpos[-1]


# ---- teste 9: tokens -------------------------------------------------------------


class _Pai(TypedDict, total=False):
    cpf: str | None
    nome: str | None
    dataNascimento: str | None
    dadosPessoa: DadosPessoa
    cadastroErro: str | None
    confirmaAssistido: bool | None
    viaOrquestrador: bool | None
    tentativasCpf: int | None
    querTentarNovamenteCpf: bool | None
    digitouCpfDireto: bool | None
    perguntaAtualTexto: str | None
    perguntaAtualViaIA: bool
    perguntaAtualTokensTotal: int | None
    tokensGastos: CanalTokensGastos


# A soma de tokens dos subgrafos se compõe: É DEFEITO DE DEVELOP REPRODUZIDO DE
# PROPÓSITO, com os números medidos em develop @ 4e695f2 (spec, seção 0.1).
# https://github.com/dgd-dprj/maria-langgraph-pp/issues/230
# Não "corrija" aqui: o painel de tokens mudaria sem ninguém notar. A correção
# é feita naquela issue, que substitui este teste.


async def test_9_tokens_identificar_assistido_dobra() -> None:
    c = await Conversa(envelope(_Pai, identificar_assistido)).iniciar(
        {"cpf": "12345678901", "viaOrquestrador": False, "tokensGastos": SEMENTE}
    )
    assert (await c.estado())["tokensGastos"]["total"] == 300


async def test_9_tokens_cadastro_aninhado_triplica() -> None:
    c = await Conversa(envelope(_Pai, cadastro_pessoa)).iniciar({"cpf": "12345678901", "viaOrquestrador": False, "tokensGastos": SEMENTE})
    await c.responder("Fulano de Tal", "01/01/1990", "20000000", "10", "não")
    assert (await c.estado())["tokensGastos"] == {"input": 300, "output": 150, "total": 450}


async def test_9_tokens_identificar_e_cadastro_seis_vezes() -> None:
    c = await Conversa(envelope(_Pai, identificar_assistido, cadastro_pessoa)).iniciar(
        {"cpf": "00000000000", "viaOrquestrador": False, "tokensGastos": SEMENTE}
    )
    await c.responder("não", "Fulano de Tal", "01/01/1990", "20000000", "10", "não")
    assert (await c.estado())["tokensGastos"] == {"input": 600, "output": 300, "total": 900}


# ---- teste 10: fluxo do CPF ------------------------------------------------------


def _identificar() -> Conversa:
    return Conversa(envelope(IdentificarAssistidoState, identificar_assistido))


async def test_10_cpf_conhecido_pula_a_pergunta() -> None:
    c = await _identificar().iniciar({"cpf": "12345678901", "viaOrquestrador": False})
    assert c.perguntas == []
    estado = await c.estado()
    assert estado["dadosPessoa"]["encontrado"] is True
    assert estado["tentativasCpf"] == 1  # o CPF conhecido conta como a tentativa 1


async def test_10_tres_tentativas_e_esgotado() -> None:
    c = await _identificar().iniciar({})
    await c.responder("00000000000", "sim", "00000000000", "sim", "00000000000")
    estado = await c.estado()
    assert c.pendente is None
    assert estado["tentativasCpf"] == 3
    assert estado["dadosPessoa"] == {"encontrado": False}
    assert c.perguntas[1]["pergunta"] == "Não encontrei ninguém com esse CPF (tentativa 1 de 3). Quer tentar de novo?"


async def test_10_nao_ao_retry_na_primeira_tentativa_esgota() -> None:
    c = await (await _identificar().iniciar({})).responder("00000000000", "não")
    estado = await c.estado()
    assert c.pendente is None
    assert estado["tentativasCpf"] == 1
    assert estado["querTentarNovamenteCpf"] is False


async def test_10_cpf_digitado_direto_no_retry_consulta_e_grava_pontuado() -> None:
    c = await (await _identificar().iniciar({})).responder("00000000000", "123.456.789-01")
    estado = await c.estado()
    assert len(c.perguntas) == 2  # não pergunta o CPF de novo
    assert estado["cpf"] == "123.456.789-01"
    assert estado["tentativasCpf"] == 2
    assert estado["digitouCpfDireto"] is True
    assert estado["dadosPessoa"]["encontrado"] is True


async def test_10_falha_de_infra_esgota_sem_retry() -> None:
    c = await (await _identificar().iniciar({})).responder("66666666666")
    estado = await c.estado()
    assert c.pendente is None
    assert estado["dadosPessoa"] == {"encontrado": False, "falhaInfra": True}


# ---- teste 11: cadastro ----------------------------------------------------------


def _cadastro() -> Conversa:
    return Conversa(envelope(CadastroPessoaState, cadastro_pessoa))


async def test_11_cadastro_com_sucesso() -> None:
    c = await (await _cadastro().iniciar({"cpf": "12345678901"})).responder("Fulano de Tal", "01/01/1990", "20000000", "10", "não")
    estado = await c.estado()
    assert c.pendente is None
    assert estado["dadosPessoa"] == {"encontrado": True, "idPessoa": 888888, "nome": "Fulano de Tal"}
    assert "cadastroErro" not in estado


async def test_11_cadastro_com_falha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CADASTRO_FALHA", "true")
    c = await (await _cadastro().iniciar({"cpf": "12345678901", "viaOrquestrador": True})).responder(
        "Fulano de Tal", "01/01/1990", "20000000", "10", "não"
    )
    estado = await c.estado()
    assert c.pendente is None  # "falhou" vai direto para END, sem confirmação
    assert estado["cadastroErro"] == "falha simulada (mock)"


# ---- teste 12: confirmação -------------------------------------------------------


def test_12_confirmacao_sem_nome_diz_voce() -> None:
    # `state.dadosPessoa?.nome ?? "você"`: o mock do Verde sempre traz nome, então
    # o caso sem nome é conferido na função que monta o texto, nos dois subgrafos.
    from maria.subgrafos.cadastro_pessoa.graph import texto_confirma_assistido as texto_cadastro
    from maria.subgrafos.identificar_assistido.graph import texto_confirma_assistido as texto_identificar

    for texto in (texto_identificar, texto_cadastro):
        assert texto({"dadosPessoa": {"encontrado": True}}) == "Confirma que seus dados são: você?"
        assert texto({}) == "Confirma que seus dados são: você?"


async def test_12_confirmacao_com_nome_e_resposta() -> None:
    c = await (await _identificar().iniciar({"cpf": "12345678901", "viaOrquestrador": True})).responder("Sim")
    assert c.perguntas[0]["pergunta"] == "Confirma que seus dados são: Pessoa de Teste (mock)?"
    assert (await c.estado())["confirmaAssistido"] is True


# ---- regra de estado: null da Tykhe e do Verde (spec do fluxos, tabela 0.2) ----


async def test_cpf_null_da_tykhe_pula_a_pergunta_como_em_develop() -> None:
    # Executado em develop: {cpf: null} não pergunta o CPF, consulta "" (o mock
    # encontra), tentativasCpf 1 e o cpf continua null. Develop nunca grava
    # undefined em `cpf`, então só a ausência da chave pede a pergunta.
    c = await _identificar().iniciar({"cpf": None, "viaOrquestrador": False})
    estado = await c.estado()
    assert c.perguntas == []
    assert estado["cpf"] is None
    assert estado["tentativasCpf"] == 1
    assert estado["dadosPessoa"]["encontrado"] is True


async def test_cpf_ausente_pergunta() -> None:
    c = await _identificar().iniciar({"viaOrquestrador": False})
    assert c.perguntas[0]["pergunta"] == "Qual o seu CPF? Informe apenas os números."


async def test_cadastro_com_id_pessoa_null_do_verde_mantem_null(verde_real: TransporteFalso) -> None:
    # Develop: o guarda do cadastro é `=== undefined`, então `"idPessoa": null`
    # é sucesso e o dadosPessoa fica com idPessoa null (o JSON mantém o null).
    import httpx

    async def responder(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path.endswith("/pessoa"):
            return httpx.Response(201, json={"dados": {"idPessoa": None}})
        return httpx.Response(
            200,
            json={
                "dados": {
                    "uf": {"id": 19, "sigla": "RJ"},
                    "bairro": {"id": 1, "nome": "Centro"},
                    "municipio": {"id": 2, "nome": "Rio"},
                    "logradouro": "Rua A",
                }
            },
        )

    verde_real.tratador = responder
    c = await (await _cadastro().iniciar({"cpf": "12345678901"})).responder("Fulano de Tal", "01/01/1990", "20000000", "10", "não")
    estado = await c.estado()
    assert estado["dadosPessoa"] == {"encontrado": True, "idPessoa": None, "nome": "Fulano de Tal"}
    assert "cadastroErro" not in estado
