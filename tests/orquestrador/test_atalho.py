"""Atalho por palavra antes da IA (#553): a função e o grafo do orquestrador, na produção e no release."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.types import Command

from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA
from maria.orquestrador.atalho import MOTIVO_PESSOA_PRESA, atalho_pela_palavra
from maria.orquestrador.graph import obter_grafo
from tests.fluxos.conftest import novo_config, pergunta
from tests.orquestrador.conftest import Modelo

ATALHO_PP = (ID_PESSOA_PRESA, MOTIVO_PESSOA_PRESA)


@pytest.mark.parametrize(
    "mensagem",
    [
        "preso",
        "presa",
        "Preso",
        "PRESA",
        "preso.",
        "Preso!!",
        "preso?",
        "  preso  ",
        "preso\n",
        "\tpresa ",
        "preso 🙏",
        "...preso...",
        "presos",
        "presas",
        "cadeia",
        "Cadeia.",
        "detento",
        "detenta",
        "detentos",
        "presidiário",
        "presidiaria",
        "Presidiários",
        "PRESIDIÁRIAS!",
    ],
)
def test_palavra_da_lista_sozinha_ativa(mensagem: str) -> None:
    assert atalho_pela_palavra(mensagem) == ATALHO_PP


@pytest.mark.parametrize(
    "mensagem",
    [
        "preso ao trabalho",
        "meu filho foi preso",
        "meu marido foi preso e quero me divorciar dele",
        "preso preso",
        "pre so",
        "preso-ontem",
        "presidio",
        "prisão",
        "presunto",
        "presente",
        "presa1",
        "",
        "   ",
        "...",
        "🙏",
    ],
)
def test_fora_da_lista_ou_com_mais_palavras_nao_ativa(mensagem: str) -> None:
    assert atalho_pela_palavra(mensagem) is None


@pytest.mark.parametrize("mensagem", [None, 123, ["preso"], {"mensagem": "preso"}])
def test_mensagem_que_nao_e_texto_nao_ativa(mensagem: Any) -> None:
    assert atalho_pela_palavra(mensagem) is None


@pytest.fixture(params=["producao", "release"])
def ambiente(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("MARIA_AMBIENTE", request.param)
    return str(request.param)


@pytest.mark.usefixtures("ambiente")
@pytest.mark.parametrize("mensagem", ["preso", "Presa!", "cadeia", "detento"])
async def test_relato_de_uma_palavra_vai_ao_fluxo_sem_busca_e_sem_ia(modelo: Modelo, mensagem: str) -> None:
    # A IA, se fosse chamada, mandaria para "outros": o atalho decide antes.
    modelo.classificacoes = [{"ids": ["tykhe:outros"], "tokensTotal": 99}]
    r: dict[str, Any] = await obter_grafo().ainvoke({"mensagem": mensagem}, novo_config("teste-orq-atalho"))
    assert r["statusFinal"] == "identificado"
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
    assert r["atalho"] == MOTIVO_PESSOA_PRESA
    assert modelo.textos_classificados == [], "o atalho não chama a IA"
    assert modelo.retrievals == 0, "nem a busca de candidatos"
    assert r.get("tokensGastosRodada") is None
    assert r["tokensGastosConversa"] == {"input": 0, "output": 0, "total": 0}


@pytest.mark.usefixtures("ambiente")
async def test_frase_com_contexto_segue_pela_ia(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": ["tykhe:novo-processo"]}]
    r: dict[str, Any] = await obter_grafo().ainvoke(
        {"mensagem": "meu marido foi preso e quero me divorciar dele"}, novo_config("teste-orq-atalho")
    )
    assert r["flowIdEscolhido"] == "tykhe:novo-processo"
    assert r.get("atalho") is None
    assert modelo.textos_classificados == ["meu marido foi preso e quero me divorciar dele"]


@pytest.mark.usefixtures("ambiente")
async def test_resposta_a_pergunta_de_esclarecimento_segue_pela_ia(modelo: Modelo) -> None:
    # Só o relato tem atalho: "preso" como resposta à desambiguação é classificado pela IA, dentro do que sobrou.
    modelo.classificacoes = [{"ids": [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA]}, {"ids": [ID_VIOLENCIA_DOMESTICA]}]
    grafo, config = obter_grafo(), novo_config("teste-orq-atalho")
    r: dict[str, Any] = await grafo.ainvoke({"mensagem": "preciso de ajuda com meu marido"}, config)
    assert pergunta(r) is not None
    r = await grafo.ainvoke(Command(resume="preso"), config)
    assert r["flowIdEscolhido"] == ID_VIOLENCIA_DOMESTICA
    assert r.get("atalho") is None
    assert len(modelo.textos_classificados) == 2
