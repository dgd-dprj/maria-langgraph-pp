"""/docs e /docs/json (spec 07, D-3: divergência aceita no conteúdo).

Em develop, o @fastify/swagger gera o OpenAPI dos schemas das rotas e o
@fastify/swagger-ui o serve em /docs, com o documento em /docs/json. Aqui o
documento sai das MESMAS definições de rota que o pipeline usa, e a página é o
Swagger UI do FastAPI. Não é contrato com a Tykhe: nenhuma fixture cobre essas
rotas, que ficam fora da autenticação, como em develop.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from maria.api.pipeline import Rota

DESCRICAO = (
    "Ponte Tykhe↔Verde pros fluxos de atendimento. Todo atendimento vive em /atendimentos — o campo flowId no body "
    "do POST de criação escolhe o fluxo (chamadas seguintes, GET e /respostas, resolvem sozinhas a partir do chatId); "
    "comece por GET /fluxos pra ver os ids disponíveis. Nível 3 de Richardson (HATEOAS) — siga os `_links` de cada resposta."
)


# Parâmetros de caminho (`:nome` no caminho da rota) e o que o /docs mostra de cada um.
PARAMETROS_CAMINHO: dict[str, str] = {
    "chatId": (
        "Identificador da conversa, o mesmo `chatId` usado ao criar o atendimento. "
        "Até 100 caracteres (acima disso a resposta é 414), sem `/`, `?`, `#` nem espaço."
    ),
}


def _caminho_openapi(caminho: str) -> tuple[str, list[dict[str, Any]]]:
    """`/atendimentos/:chatId` vira `/atendimentos/{chatId}`, mais a lista de `parameters` da operação."""
    segmentos: list[str] = []
    parametros: list[dict[str, Any]] = []
    for segmento in caminho.split("/"):
        if segmento.startswith(":"):
            nome = segmento[1:]
            segmentos.append("{" + nome + "}")
            parametros.append(
                {
                    "name": nome,
                    "in": "path",
                    "required": True,
                    "description": PARAMETROS_CAMINHO.get(nome, ""),
                    "schema": {"type": "string", "maxLength": 100},
                }
            )
        else:
            segmentos.append(segmento)
    return "/".join(segmentos), parametros


def montar_openapi(rotas: Iterable[Rota]) -> dict[str, Any]:
    caminhos: dict[str, Any] = {}
    for rota in rotas:
        if not rota.tags:  # /health fica fora, como o `hide: true` de develop
            continue
        caminho, parametros = _caminho_openapi(rota.caminho)
        operacao: dict[str, Any] = {"tags": list(rota.tags), "summary": rota.resumo}
        if rota.descricao:
            operacao["description"] = rota.descricao
        if parametros:
            operacao["parameters"] = parametros
        if rota.protegida:
            operacao["security"] = [{"bearerAuth": []}]
        if rota.corpo is not None:
            operacao["requestBody"] = {"content": {"application/json": {"schema": rota.corpo}}}
        operacao["responses"] = {
            str(status): {"description": "Default Response", "content": {"application/json": {"schema": schema}}}
            for status, schema in rota.respostas.items()
        }
        caminhos.setdefault(caminho, {})[rota.metodo.lower()] = operacao
    return {
        "openapi": "3.0.3",
        "info": {"title": "Maria — API (LangGraph nativo)", "description": DESCRICAO, "version": "0.2.0"},
        "tags": [
            {"name": "fluxos", "description": "Descoberta de quais fluxos existem e seus ids"},
            {"name": "atendimentos", "description": "Ciclo de vida de um atendimento (thread do grafo), pra qualquer fluxo"},
        ],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "description": "API_KEY — pedir no secret do ambiente"},
            }
        },
        "paths": caminhos,
    }


def registrar_docs(app: FastAPI, rotas: Iterable[Rota]) -> None:
    documento = montar_openapi(rotas)

    @app.get("/docs/json", include_in_schema=False)
    async def openapi_json() -> JSONResponse:
        return JSONResponse(documento)

    @app.get("/docs", include_in_schema=False)
    async def swagger() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/docs/json", title="Maria — API")
