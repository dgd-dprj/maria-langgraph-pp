"""O relógio do TTL nos testes: o tempo passa de propósito, e não por sorte.

`TTL_INATIVIDADE_HORAS=0` quer dizer "qualquer intervalo maior que zero expira". O intervalo é a diferença entre
`datetime.now()` na resposta e o `atualizadoEm` da última atividade. No Windows, o relógio anda em degraus de cerca de
15 ms, e a criação e a resposta às vezes caem no mesmo degrau: o intervalo dá zero, a Maria não pergunta se a pessoa
quer continuar, e o teste falha de vez em quando (achado no PR #541, caso `ttl_c0_confirmacao` da conferência pr2). No
Linux do CI o degrau é bem menor, por isso não aparecia lá. Na produção, com a inatividade de 24 h, ninguém responde no
mesmo degrau: o defeito é do teste, não da Maria.

A correção é dizer, no teste, que o tempo passou: o relógio que o TTL lê fica 1 segundo à frente do real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo

import pytest

from maria.api import atendimentos

AVANCO = timedelta(seconds=1)


class RelogioAdiantado:
    """O `datetime` que `maria.api.atendimentos` usa no TTL, com o `now()` 1 segundo à frente do real."""

    @staticmethod
    def now(tz: tzinfo | None = None) -> datetime:
        return datetime.now(tz) + AVANCO


def adiantar_relogio_do_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Antes da resposta que deve achar o atendimento parado: o TTL passa a ver 1 segundo de inatividade a mais."""
    monkeypatch.setattr(atendimentos, "datetime", RelogioAdiantado)
