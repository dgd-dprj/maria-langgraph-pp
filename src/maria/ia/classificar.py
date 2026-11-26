"""Núcleo reaproveitável de "texto livre + lista de candidatos rotulados → candidato
escolhido via IA" (issues #8 e #28), traduzido de `src/ia/classificar.ts`.

Cada chamador mantém o próprio guard de teste/mock; este módulo só faz a chamada
real quando invocado.

A saída é validada contra a lista desde a #212 (decisão da Nicole, 2026-11-17). Em develop @ 4e695f2,
um id fora da lista, ou de outro tipo, passava como veio.
- Escolha única: id fora da lista, de outro tipo ou ausente vira "nenhum" (`escolhaId: None`).
- Escolha múltipla: saem só os ids de fora da lista, e os válidos seguem (a escolha certa não é perdida
  por causa de um id inventado junto); o que não é lista vira nenhum candidato.
- Em todos os casos, um aviso no log (`ia_saida_invalida`), sem o valor, e os tokens continuam
  contados, porque a chamada aconteceu.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict, cast

from maria.ia._estruturado import avisar_saida_invalida, criar_modelo, definir_tokens, erro_para_log, esquema_objeto, invocar_estruturado
from maria.shared import _js
from maria.shared._js import AUSENTE
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger

modelo = criar_modelo()


class ResultadoClassificacaoGenerica(TypedDict):
    # None = a IA não achou candidato com confiança ("nenhum"), a saída não era um id da lista, ou a chamada falhou.
    escolhaId: NotRequired[Any]
    viaIA: bool
    # Ausentes quando viaIA é False ou quando a resposta não trouxe `usage`.
    tokensEntrada: NotRequired[int]
    tokensSaida: NotRequired[int]
    tokensTotal: NotRequired[int]


class ResultadoClassificacaoMultipla(TypedDict):
    # Sempre lista, só com ids dos candidatos (#212).
    ids: NotRequired[Any]
    viaIA: bool
    tokensEntrada: NotRequired[int]
    tokensSaida: NotRequired[int]
    tokensTotal: NotRequired[int]


def _indice_de_array(chave: str) -> bool:
    """Chave que o JS trata como índice de array: inteiro canônico de 0 a 2³²-2."""
    return chave.isascii() and chave.isdigit() and str(int(chave)) == chave and int(chave) < 2**32 - 1


def _sem_repetidos(valores: list[str]) -> list[str]:
    """O `enum` que o `z.enum([...])` de develop gera. O zod guarda as entradas
    num objeto, e o JSON Schema sai de `Object.values`, então valem as duas regras
    de ordem de propriedade do JS: valores repetidos saem (fica a 1ª ocorrência),
    e chaves que parecem índice de array ("7") vêm primeiro, em ordem numérica.
    Achados na conferência diferencial do orquestrador: com id repetido nos
    candidatos, ou com um id numérico no catálogo, a lista crua mudaria o corpo
    enviado ao Bedrock."""
    unicos = list(dict.fromkeys(valores))
    return sorted((v for v in unicos if _indice_de_array(v)), key=int) + [v for v in unicos if not _indice_de_array(v)]


def escolha_valida(escolha: Any, ids: list[str]) -> str | None:
    """A escolha única, se for um id da lista; senão None ("nenhum"), com o aviso no log (#212)."""
    if escolha == "nenhum":
        return None
    motivo = "chave_ausente" if escolha is AUSENTE else "tipo_errado" if not isinstance(escolha, str) else None
    if motivo is None and escolha not in ids:
        motivo = "fora_da_lista"
    if motivo is not None:
        avisar_saida_invalida("classificar_entre_opcoes", motivo)
        return None
    return cast(str, escolha)


def ids_validos(valor: Any, ids: list[str]) -> list[str]:
    """Os ids da escolha múltipla que estão na lista, na ordem do modelo e sem repetir. Os de fora saem, e os
    válidos seguem; o que não é lista vira nenhum candidato. Aviso no log com as contagens (#212)."""
    if valor is AUSENTE or not isinstance(valor, list):
        avisar_saida_invalida("classificar_multiplo_entre_opcoes", "chave_ausente" if valor is AUSENTE else "tipo_errado")
        return []
    dentro = list(dict.fromkeys(v for v in valor if isinstance(v, str) and v in ids))
    fora = sum(1 for v in valor if not (isinstance(v, str) and v in ids))
    if fora:
        avisar_saida_invalida("classificar_multiplo_entre_opcoes", "fora_da_lista", ids_dentro=len(dentro), ids_fora=fora)
    return dentro


async def classificar_entre_opcoes(mensagem: str, sistema: str, ids: list[str]) -> ResultadoClassificacaoGenerica:
    try:
        if len(ids) == 0:
            return {"escolhaId": None, "viaIA": False}
        esquema = esquema_objeto(
            {
                "escolhaId": {
                    "type": "string",
                    # z.enum descarta valores repetidos, mantendo a 1ª ocorrência.
                    "enum": _sem_repetidos(["nenhum", *ids]),
                    "description": 'id do candidato que melhor atende, ou "nenhum" se não bater com confiança em nenhum',
                }
            },
            ["escolhaId"],
        )
        resultado = await invocar_estruturado(modelo, esquema, sistema, mensagem)
        saida: dict[str, Any] = {"escolhaId": escolha_valida(_js.prop(resultado["parsed"], "escolhaId"), ids)}
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
                    "items": {"type": "string", "enum": _sem_repetidos(ids)},
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
        saida: dict[str, Any] = {"ids": ids_validos(_js.prop(resultado["parsed"], "idsPlausiveis"), ids)}
        saida["viaIA"] = True
        definir_tokens(saida, resultado["raw"])
        return cast(ResultadoClassificacaoMultipla, saida)
    except Exception as erro:
        logger.error(
            "[classificar] falha ao classificar (múltiplo), tratando como não identificado", **contexto_atual(), err=erro_para_log(erro)
        )
        return {"ids": [], "viaIA": False}
