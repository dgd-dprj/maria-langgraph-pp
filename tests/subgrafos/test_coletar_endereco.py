"""Tradução dos 3 testes de `subgrafos/coletarEndereco/graph.test.ts` (develop @ 4e695f2),
mais os testes 6 e 7 da spec do módulo subgrafos (complemento e regra de estado).

Em develop, o teste 3 restaurava a variável com `process.env.X = original`, o
que grava a string "undefined" quando ela não existia (defeito do teste, sem
efeito no comportamento). Aqui, `monkeypatch`.
"""

import re

import pytest

from maria.subgrafos.coletar_endereco.graph import grafo, sem_complemento
from maria.subgrafos.coletar_endereco.state import ColetarEnderecoState
from tests.subgrafos.conftest import Conversa, envelope


def _conversa() -> Conversa:
    return Conversa(envelope(ColetarEnderecoState, grafo))


async def test_cep_completo_pula_logradouro_bairro_municipio_e_uf() -> None:
    c = await (await _conversa().iniciar({})).responder("20000000", "123", "não")
    assert [bool(re.search(p, q["pergunta"])) for p, q in zip(("CEP", "número", "complemento"), c.perguntas, strict=True)] == [True] * 3
    assert c.pendente is None
    endereco = (await c.estado())["endereco"]
    assert endereco["logradouro"] == "Rua de Teste (mock)"
    assert endereco["bairro"] == "Bairro de Teste (mock)"
    assert endereco["municipio"] == "Rio de Janeiro (mock)"
    assert endereco["uf"] == "RJ"
    assert endereco["numero"] == "123"
    # `complemento === undefined` em develop: aqui, chave ausente no objeto
    # aninhado (regra de estado, limite para objetos aninhados).
    assert "complemento" not in endereco


async def test_cep_nao_encontrado_pergunta_todos_os_campos() -> None:
    c = await (await _conversa().iniciar({})).responder("00000000", "Rua Sem CEP", "45", "não", "Bairro Sem CEP", "Cidade Sem CEP", "rj")
    padroes = ("CEP", "rua/avenida", "número", "complemento", "bairro", "município", "estado")
    assert [bool(re.search(p, q["pergunta"])) for p, q in zip(padroes, c.perguntas, strict=True)] == [True] * len(padroes)
    assert c.pendente is None
    endereco = (await c.estado())["endereco"]
    assert endereco["uf"] == "RJ"  # toUpperCase
    assert endereco["logradouro"] == "Rua Sem CEP"
    assert endereco["municipio"] == "Cidade Sem CEP"


async def test_cep_incompleto_pergunta_so_o_que_falta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CEP_INCOMPLETO", "true")
    c = await (await _conversa().iniciar({})).responder("20000000", "Rua Nova", "10", "não", "Centro", "Rio de Janeiro")
    padroes = ("CEP", "rua/avenida", "número", "complemento", "bairro", "município")
    assert [bool(re.search(p, q["pergunta"])) for p, q in zip(padroes, c.perguntas, strict=True)] == [True] * len(padroes)
    assert not any("estado" in q["pergunta"] for q in c.perguntas)
    endereco = (await c.estado())["endereco"]
    assert endereco == {
        "cep": "20000000",
        "uf": "RJ",
        "logradouro": "Rua Nova",
        "numero": "10",
        "bairro": "Centro",
        "municipio": "Rio de Janeiro",
    }


# ---- teste 6 da spec: complemento ----------------------------------------------


@pytest.mark.parametrize("resposta", ["não", "nao", " N ", "", "NÃO"])
def test_6_sem_complemento(resposta: str) -> None:
    assert sem_complemento(resposta)


@pytest.mark.parametrize("resposta", ["não", "Apto 101", "não."])
def test_6_com_complemento(resposta: str) -> None:
    # "não" é "não" decomposto (NFD): develop NÃO normaliza aqui, e o texto
    # vira complemento literal.
    assert not sem_complemento(resposta)


async def test_6_complemento_grava_a_resposta_original_sem_trim() -> None:
    c = await (await _conversa().iniciar({})).responder("20000000", "1", "  Apto 101 ")
    assert (await c.estado())["endereco"]["complemento"] == "  Apto 101 "


# ---- teste 7 da spec: regra de estado em dois passos ----------------------------


async def test_7_complemento_none_no_canal_nao_deixa_o_valor_anterior() -> None:
    # Dois passes pelo subgrafo no mesmo thread: o primeiro grava um
    # complemento, o segundo responde "não". Develop grava undefined no canal;
    # omitir a chave manteria "Apto 1" do primeiro passe.
    c = await (await _conversa().iniciar({})).responder("20000000", "1", "Apto 1")
    assert (await c.estado())["endereco"]["complemento"] == "Apto 1"
    await c.iniciar({})
    await c.responder("20000000", "2", "não")
    assert "complemento" not in (await c.estado())["endereco"]
