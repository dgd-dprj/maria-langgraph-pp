"""Metadados e mensagens do fluxo de problemas com plano de saúde (NUDECON, issue #329)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def extrair_metadados_plano_saude(values: Mapping[str, Any]) -> dict[str, Any]:
    # Esqueleto: o fluxo ainda não coleta nada.
    return {}


# Provisória até as perguntas da #329 entrarem.
MENSAGEM_CONCLUIDO = (
    "Esse atendimento sobre plano de saúde ainda está sendo construído na Maria. "
    "Por enquanto, vou encaminhar você pra um canal de atendimento alternativo."
)

# Nunca deveria disparar (o esqueleto só conclui), mas FluxoConfig exige o campo.
MENSAGEM_HANDOFF = "Vou encaminhar seu atendimento para um atendente humano."
