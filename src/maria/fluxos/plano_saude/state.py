"""Estado do fluxo de problemas com plano de saúde (NUDECON, issue #329).

Esqueleto: o fluxo ainda não coleta nada. As perguntas (canal, para quem,
renda, confirmação) entram nas próximas etapas da #329.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from maria.shared.tokens_acumulados import CanalTokensGastos


class PlanoSaudeState(TypedDict, total=False):
    statusFinal: Literal["concluido"] | None
    mensagemFinal: str | None
    tokensGastos: CanalTokensGastos
