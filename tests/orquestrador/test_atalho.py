"""Atalho por palavra antes da IA (#553): a função e o grafo do orquestrador, na produção e no release."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.types import Command

from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, catalogo_para_classificacao
from maria.orquestrador.atalho import ATALHOS, MOTIVO_PESSOA_PRESA, atalho_pela_palavra, expressao_normalizada
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


@pytest.mark.parametrize(
    ("mensagem", "destino"),
    [
        ("Violência doméstica", ID_VIOLENCIA_DOMESTICA),
        ("lei Maria da Penha!", ID_VIOLENCIA_DOMESTICA),
        ("medida protetiva", ID_VIOLENCIA_DOMESTICA),
        ("agressão", ID_VIOLENCIA_DOMESTICA),
        ("remédio", "tykhe:saude"),
        ("Vaga na UTI", "tykhe:saude"),
        ("fraldas", "tykhe:saude"),
        ("divórcio", "tykhe:novo-processo"),
        ("pensão alimentícia", "tykhe:novo-processo"),
        ("processo novo", "tykhe:novo-processo"),
        ("andamento do processo", "tykhe:andamento-processo"),
        ("número do processo?", "tykhe:andamento-processo"),
        ("meus agendamentos", "tykhe:agendamentos"),
        ("remarcar", "tykhe:agendamentos"),
        ("esqueci minha senha", "tykhe:ajuda-app"),
        ("App", "tykhe:ajuda-app"),
        ("tchau", "tykhe:sair"),
        ("não quero mais", "tykhe:sair"),
    ],
)
def test_expressao_curta_de_outros_destinos(mensagem: str, destino: str) -> None:
    atalho = atalho_pela_palavra(mensagem)
    assert atalho is not None and atalho[0] == destino


@pytest.mark.parametrize(
    "mensagem",
    # Pedem a pergunta da Maria: plano ou SUS, DNA ou saúde, custódia ou processo, novo ou andamento, agradecimento.
    ["cirurgia", "exame", "audiência", "processo", "pensão", "obrigado", "plano de saúde", "guarda", "consulta"],
)
def test_palavra_que_pede_a_pergunta_da_maria_nao_ativa(mensagem: str) -> None:
    assert atalho_pela_palavra(mensagem) is None


def test_cada_expressao_tem_um_destino_so() -> None:
    vistas: dict[str, str] = {}
    for atalho in ATALHOS:
        for expressao in atalho.expressoes:
            assert expressao == expressao_normalizada(expressao), f"{expressao!r} não está normalizada"
            assert expressao not in vistas, f"{expressao!r} em {vistas.get(expressao)} e em {atalho.destino}"
            vistas[expressao] = atalho.destino
    assert len({a.motivo for a in ATALHOS}) == len(ATALHOS)


@pytest.mark.usefixtures("ambiente")
async def test_todo_destino_esta_no_catalogo() -> None:
    ids = {c["id"] for c in await catalogo_para_classificacao()}
    assert {a.destino for a in ATALHOS} <= ids


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


@pytest.mark.usefixtures("ambiente")
@pytest.mark.parametrize(
    ("mensagem", "destino"), [("Lei Maria da Penha", ID_VIOLENCIA_DOMESTICA), ("remédio", "tykhe:saude"), ("tchau", "tykhe:sair")]
)
async def test_outros_destinos_pelo_grafo_sem_ia(modelo: Modelo, mensagem: str, destino: str) -> None:
    modelo.classificacoes = [{"ids": ["tykhe:outros"]}]
    r: dict[str, Any] = await obter_grafo().ainvoke({"mensagem": mensagem}, novo_config("teste-orq-atalho"))
    assert (r["statusFinal"], r["flowIdEscolhido"]) == ("identificado", destino)
    assert r["atalho"]
    assert modelo.textos_classificados == []
