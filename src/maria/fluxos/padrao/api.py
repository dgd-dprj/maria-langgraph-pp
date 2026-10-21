"""Metadados e mensagens do grafo padrão (develop: `fluxos/padrao/api.ts`).

O `metadadosSchemaPadrao` não é traduzido (spec 05, decisão 3): não tem
consumidor em develop.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def extrair_metadados_padrao(values: Mapping[str, Any]) -> dict[str, Any]:
    # O grafo não coleta nada: existe só para cumprir o contrato de FluxoConfig.
    return {}


# Mensagem única para qualquer categoria planejada que caia neste grafo (#21).
MENSAGEM_CONCLUIDO = (
    "Esse tipo de atendimento ainda está sendo construído na Maria. "
    "Por enquanto, vou encaminhar você pra um canal de atendimento alternativo."
)

# Nunca deveria disparar (o grafo só conclui), mas FluxoConfig exige o campo.
MENSAGEM_HANDOFF = "Vou encaminhar seu atendimento para um atendente humano."
