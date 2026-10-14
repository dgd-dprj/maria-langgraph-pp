"""Núcleo reaproveitável de "texto livre + lista de candidatos rotulados → candidato
escolhido via IA" (issues #8 e #28), traduzido de `src/ia/classificar.ts`.

Cada chamador mantém o próprio guard de teste/mock; este módulo só faz a chamada
real quando invocado.

A saída NÃO é validada contra o enum: um id fora da lista, ou de outro tipo,
passa como veio, exatamente como em develop @ 4e695f2. Defeito registrado em
https://github.com/dgd-dprj/maria-langgraph-pp/issues/212. Não "corrija"
validando aqui: isso muda desfecho de atendimento sem ninguém notar.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict, cast

from maria.ia._estruturado import criar_modelo, definir_tokens, erro_para_log, esquema_objeto, invocar_estruturado
from maria.shared import _js
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger

modelo = criar_modelo()


class ResultadoClassificacaoGenerica(TypedDict):
    # None = a IA não achou candidato com confiança ("nenhum"), ou a chamada
    # falhou. Ausente quando o modelo não devolveu a chave (undefined em develop).
    escolhaId: NotRequired[Any]
    viaIA: bool
    # Ausentes quando viaIA é False ou quando a resposta não trouxe `usage`.
    tokensEntrada: NotRequired[int]
    tokensSaida: NotRequired[int]
    tokensTotal: NotRequired[int]


class ResultadoClassificacaoMultipla(TypedDict):
    # Lista em develop pelo tipo, mas sem validação: pode vir string ou ausente.
    ids: NotRequired[Any]
    viaIA: bool
    tokensEntrada: NotRequired[int]
    tokensSaida: NotRequired[int]
    tokensTotal: NotRequired[int]


async def classificar_entre_opcoes(mensagem: str, sistema: str, ids: list[str]) -> ResultadoClassificacaoGenerica:
    try:
        if len(ids) == 0:
            return {"escolhaId": None, "viaIA": False}
        esquema = esquema_objeto(
            {
                "escolhaId": {
                    "type": "string",
                    "enum": ["nenhum", *ids],
                    "description": 'id do candidato que melhor atende, ou "nenhum" se não bater com confiança em nenhum',
                }
            },
            ["escolhaId"],
        )
        resultado = await invocar_estruturado(modelo, esquema, sistema, mensagem)
        escolha = _js.prop(resultado["parsed"], "escolhaId")
        saida: dict[str, Any] = {}
        _js.definir(saida, "escolhaId", None if escolha == "nenhum" else escolha)
        saida["viaIA"] = True
        definir_tokens(saida, resultado["raw"])
        return cast(ResultadoClassificacaoGenerica, saida)
    except Exception as erro:
        logger.error("[classificar] falha ao classificar, tratando como não identificado", **contexto_atual(), err=erro_para_log(erro))
        return {"escolhaId": None, "viaIA": False}


async def classificar_multiplo_entre_opcoes(mensagem: str, sistema: str, ids: list[str]) -> ResultadoClassificacaoMultipla:
    try:
        if len(ids) == 0:
            return {"ids": [], "viaIA": False}
        esquema = esquema_objeto(
            {
                "idsPlausiveis": {
                    "type": "array",
                    "items": {"type": "string", "enum": ids},
                    "description": (
                        "ids de TODOS os candidatos que plausivelmente atendem ao relato — lista vazia se nenhum bater"
                        " com confiança, 1 item se for claro, vários se o relato for genuinamente ambíguo entre mais de um."
                        " Nunca inventa id fora da lista."
                    ),
                }
            },
            ["idsPlausiveis"],
        )
        resultado = await invocar_estruturado(modelo, esquema, sistema, mensagem)
        saida: dict[str, Any] = {}
        _js.definir(saida, "ids", _js.prop(resultado["parsed"], "idsPlausiveis"))
        saida["viaIA"] = True
        definir_tokens(saida, resultado["raw"])
        return cast(ResultadoClassificacaoMultipla, saida)
    except Exception as erro:
        logger.error(
            "[classificar] falha ao classificar (múltiplo), tratando como não identificado", **contexto_atual(), err=erro_para_log(erro)
        )
        return {"ids": [], "viaIA": False}
