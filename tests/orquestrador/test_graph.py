"""Traduzido de `src/orquestrador/graph.test.ts` (develop @ 1157a6d).

Whitebox: inspeciona o ESTADO diretamente (mensagem, resumoRelato,
ultimaResposta), diferente dos testes de rota (módulo api, caixa-preta). Precisa
disso para confirmar a issue #47: o texto que VAI para a classificação encolhe
depois do limite de rodadas, não só o comportamento externo.
"""

from typing import Any

import pytest
from langgraph.types import Command

from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA
from maria.orquestrador.graph import obter_grafo
from tests.fluxos.conftest import novo_config


@pytest.fixture
def mock_ambiguo(monkeypatch: pytest.MonkeyPatch) -> None:
    """2 candidatos que NUNCA convergem para 1: "muitos" rodada após rodada."""
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", f"{ID_PESSOA_PRESA},{ID_VIOLENCIA_DOMESTICA}")
    monkeypatch.delenv("MOCK_CLASSIFICACAO_FLOWID", raising=False)


@pytest.mark.usefixtures("mock_ambiguo")
async def test_historico_curto_abaixo_do_limite_nao_sumariza() -> None:
    grafo = obter_grafo()
    config = novo_config("teste-orq-graph")
    await grafo.ainvoke({"mensagem": "relato ambíguo"}, config)  # 1ª pausa, rodada ainda 0
    estado: dict[str, Any] = await grafo.ainvoke(Command(resume="resposta 1"), config)  # rodada 0 → 1 (< limite 3)
    assert estado["rodada"] == 1
    assert estado.get("resumoRelato") is None, "abaixo do limite, ainda não deveria ter sumarizado"
    assert "relato ambíguo" in estado["mensagem"] and estado["mensagem"].index("relato ambíguo") < estado["mensagem"].index("resposta 1"), (
        "mensagem bruta continua acumulando normalmente"
    )


@pytest.mark.usefixtures("mock_ambiguo")
async def test_historico_longo_no_limite_sumariza_e_o_resumo_e_menor_que_o_bruto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_SUMARIZACAO_RESUMO", "resumo curto")
    grafo = obter_grafo()
    config = novo_config("teste-orq-graph")
    relato_longo = "a" * 200  # relato inicial grande, para ficar óbvio que o resumo é menor
    await grafo.ainvoke({"mensagem": relato_longo}, config)  # 1ª pausa, rodada ainda 0
    await grafo.ainvoke(Command(resume="resposta 1"), config)  # rodada 0 → 1
    await grafo.ainvoke(Command(resume="resposta 2"), config)  # rodada 1 → 2
    estado: dict[str, Any] = await grafo.ainvoke(Command(resume="resposta 3"), config)  # rodada 2 → 3 (atinge o limite)

    assert estado["rodada"] == 3
    assert estado["resumoRelato"] == "resumo curto", "a partir do limite, deveria ter chamado sumarizar_relato (mock)"
    assert estado["ultimaResposta"] == "resposta 3", "última resposta fica de fora do resumo, guardada verbatim"
    # mensagem bruta continua crescendo para registro (issue #47), mas resumo +
    # última resposta é bem menor que ela.
    texto_que_iria_para_classificacao = f"{estado['resumoRelato']}\n{estado['ultimaResposta']}"
    assert len(texto_que_iria_para_classificacao) < len(estado["mensagem"]), (
        "texto usado para classificar (resumo + última resposta) deveria ser menor que o histórico bruto completo"
    )
