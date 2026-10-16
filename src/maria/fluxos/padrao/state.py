"""Estado do grafo padrão (develop: `fluxos/padrao/state.ts`).

Mínimo: o grafo nunca pausa e conclui no primeiro invoke. `tokensGastos`
existe para repassar a semente do orquestrador (issue #35); sem o canal, o
LangGraph ignoraria a chave e o total ficaria em zero.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from maria.shared.tokens_acumulados import CanalTokensGastos


class PadraoState(TypedDict, total=False):
    statusFinal: Literal["concluido"] | None
    mensagemFinal: str | None
    tokensGastos: CanalTokensGastos
