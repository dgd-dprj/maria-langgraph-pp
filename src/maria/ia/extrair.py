"""Extrai dados estruturados do relato livre sobre uma pessoa presa, traduzido de
`src/ia/extrair.ts`.

O resultado espalha os `args` da ferramenta como vieram (`{...resultado.parsed}`
em develop): chaves a mais, tipos errados e `null` passam sem validação (#212).
Espalhar `null` em JS não lança erro, então uma resposta sem a ferramenta dá
`{viaIA: true}` com os tokens, e NÃO o fallback.
"""

from __future__ import annotations

import os
from typing import Any, NotRequired, TypedDict, cast

from maria.ia._estruturado import criar_modelo, definir_tokens, erro_para_log, esquema_objeto, invocar_estruturado
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger

modelo = criar_modelo()

# Em develop, `description` vem antes de `type` em cada propriedade
# (`.optional().describe(...)` no zod).
ESQUEMA_EXTRACAO = esquema_objeto(
    {
        "temProcesso": {
            "description": "true se a pessoa mencionou ter processo, false se mencionou não ter, ausente se não falou nada sobre isso",
            "type": "boolean",
        },
        "numeroProcesso": {
            "description": "número do processo, só os dígitos/formato como foi informado, ausente se não mencionado",
            "type": "string",
        },
        "rg": {"description": "RG da pessoa presa, só os dígitos, ausente se não mencionado", "type": "string"},
        "parentesco": {
            "description": "parentesco de quem está falando com a pessoa presa (ex: esposa, mãe, irmão), ausente se não mencionado",
            "type": "string",
        },
    },
    None,
)

SISTEMA = """Você extrai dados estruturados do relato livre de alguém buscando informação sobre uma pessoa presa, pra Defensoria Pública do RJ.
Regras: extraia APENAS o que foi dito explicitamente — nunca invente, nunca infira além do texto. Campo não mencionado fica ausente (não force um valor).
"temProcesso" só é true/false se a pessoa falou EXPLICITAMENTE sobre ter ou não processo — não deduza da presença/ausência de "numeroProcesso" no texto."""  # noqa: E501


class CamposExtraidos(TypedDict):
    temProcesso: NotRequired[Any]
    numeroProcesso: NotRequired[Any]
    rg: NotRequired[Any]
    parentesco: NotRequired[Any]
    viaIA: bool
    tokensEntrada: NotRequired[int]
    tokensSaida: NotRequired[int]
    tokensTotal: NotRequired[int]


async def extrair_campos_livre(texto: str) -> CamposExtraidos:
    # Defesa em profundidade: o guard principal é o roteamento no START do
    # grafo de pessoa presa.
    if os.environ.get("APP_ENV") == "test" or os.environ.get("EXTRACAO_LIVRE_IA") != "true":
        return {"viaIA": False}
    try:
        resultado = await invocar_estruturado(modelo, ESQUEMA_EXTRACAO, SISTEMA, texto)
        parsed = resultado["parsed"]
        # {...parsed, viaIA, tokens...}: as chaves seguintes sobrescrevem as do
        # modelo, inclusive com undefined (que aqui é a chave removida).
        saida: dict[str, Any] = dict(parsed) if isinstance(parsed, dict) else {}
        saida.pop("viaIA", None)
        saida["viaIA"] = True
        for chave in ("tokensEntrada", "tokensSaida", "tokensTotal"):
            saida.pop(chave, None)
        definir_tokens(saida, resultado["raw"])
        return cast(CamposExtraidos, saida)
    except Exception as erro:
        logger.error("[extrair] falha ao extrair campos, seguindo sem nada extraído", **contexto_atual(), err=erro_para_log(erro))
        return {"viaIA": False}
