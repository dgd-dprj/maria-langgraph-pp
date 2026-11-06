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
