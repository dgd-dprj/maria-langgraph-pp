"""Canal `tokensGastos` dos estados dos grafos, com reducer de soma (issues #35, #69, #92).

Cada nó devolve só o DELTA da sua chamada de IA (`{0, 0, 0}` quando não gastou
nada de verdade), e o reducer soma campo a campo entre nós e entre invokes
separados (persistido no checkpointer). Sem reducer, cada retorno
sobrescreveria o total.

Uso no estado de cada grafo:

    class PessoaPresaState(TypedDict, total=False):
        tokensGastos: CanalTokensGastos

Ponto de atenção 2 da #208, verificado contra o LangGraph instalado: um canal
com reducer começa no valor `Tipo()`. Com um `TypedDict` isso dá `{}`, e um
grafo em que nenhum nó gastou tokens terminaria com `tokensGastos == {}`. Em
develop, o default é `{input: 0, output: 0, total: 0}`. `TokensGastosZerados`
existe só para que `Tipo()` devolva esse valor. O serializador do checkpointer
grava e lê esse objeto como um `dict` comum.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Annotated, TypedDict


class TokensGastos(TypedDict):
    input: int
    output: int
    total: int


class TokensGastosZerados(dict[str, int]):
    """Valor inicial do canal: `{"input": 0, "output": 0, "total": 0}`."""

    def __init__(self) -> None:
        super().__init__(input=0, output=0, total=0)


def somar_tokens(atual: TokensGastos | Mapping[str, int] | None, incremento: TokensGastos) -> TokensGastos:
    """Mesma soma de develop: `(atual?.x ?? 0) + incremento.x` em cada campo."""
    base: TokensGastos | Mapping[str, int] = atual or {}
    return {
        "input": base.get("input", 0) + incremento["input"],
        "output": base.get("output", 0) + incremento["output"],
        "total": base.get("total", 0) + incremento["total"],
    }


if TYPE_CHECKING:
    # Para o mypy, o canal guarda um TokensGastos comum.
    CanalTokensGastos = Annotated[TokensGastos, somar_tokens]
else:
    # Em execução, o LangGraph chama TokensGastosZerados() para o valor inicial.
    CanalTokensGastos = Annotated[TokensGastosZerados, somar_tokens]
