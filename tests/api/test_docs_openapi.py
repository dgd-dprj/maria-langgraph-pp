"""O /docs diz o que é obrigatório e onde vai o chatId (issue #283), sem mudar a validação."""

from __future__ import annotations

from typing import Any

import httpx


async def _documento(cliente: httpx.AsyncClient) -> dict[str, Any]:
    r = await cliente.get("/docs/json")
    assert r.status_code == 200
    documento: dict[str, Any] = r.json()
    return documento


def _corpo(documento: dict[str, Any], caminho: str) -> dict[str, Any]:
    schema: dict[str, Any] = documento["paths"][caminho]["post"]["requestBody"]["content"]["application/json"]["schema"]
    return schema


async def test_orquestrador_documenta_obrigatorios(cliente: httpx.AsyncClient) -> None:
    corpo = _corpo(await _documento(cliente), "/atendimentos/orquestrador")
    assert corpo["required"] == ["chatId"]
    assert corpo["anyOf"] == [{"required": ["mensagem"]}, {"required": ["resposta"]}]
    assert "cpf" in corpo["properties"]["dadosConhecidos"]["description"]
    assert corpo["properties"]["mensagem"]["description"]


async def test_demais_corpos_documentam_obrigatorios(cliente: httpx.AsyncClient) -> None:
    documento = await _documento(cliente)
    assert _corpo(documento, "/atendimentos")["required"] == ["flowId"]
    assert _corpo(documento, "/atendimentos/respostas")["required"] == ["chatId", "resposta"]


async def test_get_atendimento_declara_chat_id_no_caminho(cliente: httpx.AsyncClient) -> None:
    documento = await _documento(cliente)
    assert "/atendimentos/:chatId" not in documento["paths"]
    operacao = documento["paths"]["/atendimentos/{chatId}"]["get"]
    assert [(p["name"], p["in"], p["required"]) for p in operacao["parameters"]] == [("chatId", "path", True)]


async def test_dados_coletados_tem_a_mesma_definicao_nas_duas_respostas(cliente: httpx.AsyncClient) -> None:
    documento = await _documento(cliente)
    orquestrador = documento["paths"]["/atendimentos/orquestrador"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    atendimento = documento["paths"]["/atendimentos"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert orquestrador["properties"]["dadosColetados"] == atendimento["properties"]["dadosColetados"]
    assert "redirecionado" in orquestrador["properties"]["tipoCaso"]["description"]


async def test_rotas_protegidas_documentam_401(cliente: httpx.AsyncClient) -> None:
    documento = await _documento(cliente)
    for caminho, operacoes in documento["paths"].items():
        for operacao in operacoes.values():
            assert ("401" in operacao["responses"]) == ("security" in operacao), caminho
