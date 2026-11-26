"""Classificação por necessidades do multi-fluxo (#435), contra o Bedrock falso local."""

from __future__ import annotations

import json
from typing import Any

import pytest

from maria.ia import _estruturado
from maria.ia import classificar_necessidades as cn
from tests.ia.conftest import VALIDACAO_400, BedrockFalso, ferramenta

OPCOES: list[cn.OpcaoParaNecessidades] = [
    {"id": "pp", "nome": "pessoa-presa", "descricao": "alguém preso"},
    {"id": "plano", "nome": "problemas-plano-de-saude", "descricao": "cirurgia negada pelo plano"},
]


@pytest.fixture
def ia(bedrock: BedrockFalso, monkeypatch: pytest.MonkeyPatch) -> BedrockFalso:
    monkeypatch.setattr(cn, "modelo", _estruturado.criar_modelo())
    return bedrock


async def test_devolve_as_necessidades_validas_e_os_tokens(ia: BedrockFalso) -> None:
    ia.roteirizar(
        ferramenta(
            {
                "quantidade": "mais_de_uma",
                "haAmbiguidade": False,
                "necessidades": [
                    {"id": "pp", "evidencia": "meu irmao ta peso", "evidenciaClara": True, "urgente": False},
                    {"id": "plano", "evidencia": "a unimed negou", "evidenciaClara": True, "urgente": True},
                    {"id": "inventado", "evidencia": "x", "evidenciaClara": True, "urgente": False},
                    "não é objeto",
                    {"id": "fora_da_lista", "evidencia": "e a pensão", "evidenciaClara": False, "urgente": "sim"},
                ],
            }
        )
    )
    r = await cn.classificar_necessidades("relato", OPCOES)
    assert r["necessidades"] == [
        {"id": "pp", "evidencia": "meu irmao ta peso", "evidenciaClara": True, "urgente": False},
        {"id": "plano", "evidencia": "a unimed negou", "evidenciaClara": True, "urgente": True},
        # "urgente" que não é booleano conta como não urgente.
        {"id": "fora_da_lista", "evidencia": "e a pensão", "evidenciaClara": False, "urgente": False},
    ]
    assert r["idsEmAmbiguidade"] == []
    assert r["viaIA"] is True
    assert {"tokensEntrada", "tokensSaida", "tokensTotal"} <= set(r)


async def test_o_prompt_leva_as_opcoes_e_o_esquema_limita_os_ids(ia: BedrockFalso) -> None:
    ia.roteirizar(ferramenta({"quantidade": "sem_id_compativel", "haAmbiguidade": False, "necessidades": []}))
    await cn.classificar_necessidades("relato", OPCOES)
    corpo: dict[str, Any] = ia.requisicoes[0].corpo
    sistema = corpo["system"][0]["text"]
    assert '- id "pp" (pessoa-presa): alguém preso' in sistema
    assert '- id "plano" (problemas-plano-de-saude): cirurgia negada pelo plano' in sistema
    esquema = corpo["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"]
    assert esquema["properties"]["necessidades"]["items"]["properties"]["id"]["enum"] == ["pp", "plano", "fora_da_lista"]


async def test_duvida_so_com_ha_ambiguidade_e_so_com_ids_conhecidos(ia: BedrockFalso) -> None:
    ia.roteirizar(
        ferramenta(
            {"quantidade": "uma", "haAmbiguidade": True, "idsEmAmbiguidade": ["pp", "plano", "pp", "inventado"], "necessidades": []}
        ),
        ferramenta({"quantidade": "uma", "haAmbiguidade": False, "idsEmAmbiguidade": ["pp", "plano"], "necessidades": []}),
    )
    assert (await cn.classificar_necessidades("relato", OPCOES))["idsEmAmbiguidade"] == ["pp", "plano"]
    assert (await cn.classificar_necessidades("relato", OPCOES))["idsEmAmbiguidade"] == []


async def test_falha_da_ia_vira_nada_identificado(ia: BedrockFalso) -> None:
    ia.roteirizar(VALIDACAO_400)
    r = await cn.classificar_necessidades("relato", OPCOES)
    assert r == {"necessidades": [], "idsEmAmbiguidade": [], "viaIA": False}


async def test_sem_opcoes_nao_chama_a_ia(ia: BedrockFalso) -> None:
    assert await cn.classificar_necessidades("relato", []) == {"necessidades": [], "idsEmAmbiguidade": [], "viaIA": False}
    assert ia.requisicoes == []


# ---- o simulado dos testes (APP_ENV=test) --------------------------------------------


@pytest.fixture
def simulado(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("APP_ENV", "test")
    for variavel in ("MOCK_NECESSIDADES", "MOCK_CLASSIFICACAO_FLOWIDS", "MOCK_CLASSIFICACAO_FLOWID"):
        monkeypatch.delenv(variavel, raising=False)
    return monkeypatch


async def test_simulado_com_mock_necessidades(simulado: pytest.MonkeyPatch) -> None:
    simulado.setenv("MOCK_NECESSIDADES", json.dumps(["pp", {"id": "plano", "evidencia": "a unimed negou", "urgente": True}]))
    r = await cn.classificar_necessidades("relato", OPCOES)
    assert r["necessidades"] == [
        {"id": "pp", "evidencia": "", "evidenciaClara": True, "urgente": False},
        {"id": "plano", "evidencia": "a unimed negou", "evidenciaClara": True, "urgente": True},
    ]


@pytest.mark.parametrize(
    ("ids", "necessidades", "duvida"),
    [("pp", ["pp"], []), ("pp,plano", [], ["pp", "plano"]), ("", [], [])],
)
async def test_simulado_de_antes_mantem_o_sentido(
    simulado: pytest.MonkeyPatch, ids: str, necessidades: list[str], duvida: list[str]
) -> None:
    """MOCK_CLASSIFICACAO_FLOWIDS: 1 id é uma necessidade; mais de 1 é dúvida entre opções."""
    simulado.setenv("MOCK_CLASSIFICACAO_FLOWIDS", ids)
    r = await cn.classificar_necessidades("relato", OPCOES)
    assert [n["id"] for n in r["necessidades"]] == necessidades
    assert r["idsEmAmbiguidade"] == duvida


# ── #553: "há assunto" sem nenhuma necessidade válida repete a chamada uma vez ──

INCOERENTE_VAZIA = {"quantidade": "uma", "haAmbiguidade": False, "necessidades": []}
INCOERENTE_ID_INVENTADO = {
    "quantidade": "uma",
    "haAmbiguidade": False,
    "necessidades": [{"id": "pensao", "evidencia": "pensão", "evidenciaClara": True, "urgente": False}],
}
COERENTE = {
    "quantidade": "uma",
    "haAmbiguidade": False,
    "necessidades": [{"id": "pp", "evidencia": "preso", "evidenciaClara": True, "urgente": False}],
}


@pytest.mark.parametrize("incoerente", [INCOERENTE_VAZIA, INCOERENTE_ID_INVENTADO], ids=["lista-vazia", "id-inventado"])
async def test_saida_incoerente_repete_uma_vez_e_soma_os_tokens(
    ia: BedrockFalso, capsys: pytest.CaptureFixture[str], incoerente: dict[str, Any]
) -> None:
    ia.roteirizar(ferramenta(incoerente), ferramenta(COERENTE))
    capsys.readouterr()
    r = await cn.classificar_necessidades("relato-que-nao-vai-para-o-log", OPCOES)
    assert len(ia.requisicoes) == 2
    assert [n["id"] for n in r["necessidades"]] == ["pp"]
    assert (r["tokensEntrada"], r["tokensSaida"], r["tokensTotal"]) == (22, 14, 36), "as duas chamadas contam"
    saida = capsys.readouterr().out
    [aviso] = [json.loads(x) for x in saida.splitlines() if '"classificacao_incoerente_repetida"' in x]
    assert aviso["quantidade"] == "uma"
    assert "relato-que-nao-vai-para-o-log" not in saida


async def test_incoerente_duas_vezes_para_na_segunda_e_vira_nada_identificado(ia: BedrockFalso) -> None:
    ia.roteirizar(ferramenta(INCOERENTE_VAZIA))
    r = await cn.classificar_necessidades("relato", OPCOES)
    assert len(ia.requisicoes) == 2, "uma repetição só"
    assert (r["necessidades"], r["idsEmAmbiguidade"], r["viaIA"]) == ([], [], True)
    assert r["tokensTotal"] == 36


@pytest.mark.parametrize(
    "saida",
    [
        {"quantidade": "sem_id_compativel", "haAmbiguidade": False, "necessidades": []},
        {"quantidade": "uma", "haAmbiguidade": True, "idsEmAmbiguidade": ["pp", "plano"], "necessidades": []},
        {
            "quantidade": "uma",
            "haAmbiguidade": False,
            "necessidades": [{"id": "fora_da_lista", "evidencia": "x", "evidenciaClara": True, "urgente": False}],
        },
        COERENTE,
    ],
    ids=["sem-id-compativel", "duvida-entre-duas", "fora-da-lista", "coerente"],
)
async def test_saida_coerente_nao_repete(ia: BedrockFalso, saida: dict[str, Any]) -> None:
    ia.roteirizar(ferramenta(saida))
    await cn.classificar_necessidades("relato", OPCOES)
    assert len(ia.requisicoes) == 1
