"""O /docs/json descreve os corpos e o parâmetro de caminho que a Tykhe precisa (issue #283).

Só documentação: nenhum teste aqui muda o que a API aceita ou devolve.
"""

from typing import Any

import httpx
import pytest


@pytest.fixture
async def openapi(cliente: httpx.AsyncClient) -> dict[str, Any]:
    r = await cliente.get("/docs/json")
    assert r.status_code == 200
    documento: dict[str, Any] = r.json()
    return documento


def _corpo(openapi: dict[str, Any], caminho: str) -> dict[str, Any]:
    schema: dict[str, Any] = openapi["paths"][caminho]["post"]["requestBody"]["content"]["application/json"]["schema"]
    return schema


def test_orquestrador_documenta_obrigatorios_e_opcionais(openapi: dict[str, Any]) -> None:
    corpo = _corpo(openapi, "/atendimentos/orquestrador")
    assert corpo["required"] == ["chatId"]
    # `mensagem` na 1ª chamada ou `resposta` nas seguintes: um dos dois.
    assert corpo["anyOf"] == [{"required": ["mensagem"]}, {"required": ["resposta"]}]
    assert set(corpo["properties"]) == {"chatId", "mensagem", "resposta", "dadosConhecidos"}
    assert "dadosConhecidos" not in corpo["required"]
    for nome, propriedade in corpo["properties"].items():
        assert propriedade["description"], nome


def test_orquestrador_explica_os_tres_desfechos(openapi: dict[str, Any]) -> None:
    descricao = openapi["paths"]["/atendimentos/orquestrador"]["post"]["description"]
    for termo in ("em_andamento", "redirecionado", "tipoCaso", "flowId", "desambiguação"):
        assert termo in descricao


def test_criar_atendimento_e_respostas_declaram_obrigatorios(openapi: dict[str, Any]) -> None:
    assert _corpo(openapi, "/atendimentos")["required"] == ["chatId", "flowId"]
    assert _corpo(openapi, "/atendimentos/respostas")["required"] == ["chatId", "resposta"]


def test_get_atendimento_declara_chat_id_como_parametro_de_caminho(openapi: dict[str, Any]) -> None:
    assert "/atendimentos/:chatId" not in openapi["paths"]
    parametros = openapi["paths"]["/atendimentos/{chatId}"]["get"]["parameters"]
    assert len(parametros) == 1
    assert parametros[0]["name"] == "chatId"
    assert parametros[0]["in"] == "path"
    assert parametros[0]["required"] is True
    assert "100" in parametros[0]["description"]


def test_rotas_sem_parametro_de_caminho_nao_ganham_parameters(openapi: dict[str, Any]) -> None:
    assert "parameters" not in openapi["paths"]["/atendimentos/orquestrador"]["post"]
    assert "parameters" not in openapi["paths"]["/atendimentos"]["post"]
