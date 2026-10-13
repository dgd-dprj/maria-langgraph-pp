"""Sumariza o relato acumulado do orquestrador (issue #47), traduzido de
`src/ia/sumarizar.ts`.

Usado quando a desambiguação passa do limite de rodadas, para não reenviar o
histórico bruto inteiro a cada classificação. Se a IA falhar, mantém o texto
original: nunca perde contexto por causa de uma falha de resumo.
"""

from __future__ import annotations

import os
from typing import Any, NotRequired, TypedDict, cast

from maria.ia._estruturado import criar_modelo, definir_tokens, erro_para_log, esquema_objeto, invocar_estruturado
from maria.shared import _js
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger

modelo = criar_modelo()

ESQUEMA_RESUMO = esquema_objeto(
    {
        "resumo": {
            "type": "string",
            "description": (
                "resumo curto e objetivo do relato até agora, preservando os fatos relevantes pra identificar que tipo"
                " de atendimento a pessoa precisa — sem perder detalhes que ajudem a classificação"
            ),
        }
    },
    ["resumo"],
)

SISTEMA = """Você resume o relato de alguém buscando atendimento na Defensoria Pública do RJ.
Regras: preserve os fatos relevantes pra identificar que tipo de caso é (pessoas envolvidas, situação, o que a pessoa quer) — resumo curto e objetivo, sem invenção de informação nova."""  # noqa: E501


class ResultadoResumo(TypedDict):
    resumo: NotRequired[Any]
    viaIA: bool
    tokensEntrada: NotRequired[int]
    tokensSaida: NotRequired[int]
    tokensTotal: NotRequired[int]


async def sumarizar_relato(texto_acumulado: str) -> ResultadoResumo:
    if os.environ.get("APP_ENV") == "test":
        # `??` de develop: a string vazia É um resumo válido.
        mock = os.environ.get("MOCK_SUMARIZACAO_RESUMO")
        return {"resumo": texto_acumulado if mock is None else mock, "viaIA": False}
    try:
        resultado = await invocar_estruturado(modelo, ESQUEMA_RESUMO, SISTEMA, texto_acumulado)
        saida: dict[str, Any] = {}
        _js.definir(saida, "resumo", _js.prop(resultado["parsed"], "resumo"))
        saida["viaIA"] = True
        definir_tokens(saida, resultado["raw"])
        return cast(ResultadoResumo, saida)
    except Exception as erro:
        logger.error("[sumarizar] falha ao sumarizar, mantendo texto original", **contexto_atual(), err=erro_para_log(erro))
        return {"resumo": texto_acumulado, "viaIA": False}
