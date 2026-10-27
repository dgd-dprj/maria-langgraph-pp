"""Metadados e mensagens do fluxo Problemas com plano de saúde (NUDECON, issue #329).

Os textos marcados "provisório" valem até o NUDECON validar (#335) e a Tykhe
confirmar os destinos (#336).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from maria.fluxos.padrao.api import MENSAGEM_CONCLUIDO as MENSAGEM_PADRAO_EM_CONSTRUCAO

# Rascunho do time, não validado pelo NUDECON (#329, #335).
HORARIO_NUDECON = "de segunda a sexta, das 11h às 16h"


def extrair_metadados_plano_saude(values: Mapping[str, Any]) -> dict[str, Any]:
    metadados: dict[str, Any] = {}
    for chave in ("canal", "paraSi", "motivoHandoff"):
        valor = values.get(chave)
        if valor is not None:
            metadados[chave] = valor
    return metadados


# Provisório: a conversa seguinte (imagens, renda, confirmação) ainda não existe.
MENSAGEM_CONCLUIDO = MENSAGEM_PADRAO_EM_CONSTRUCAO
# Provisório (mock decidido pelo Ícaro em 2026-10-26): a coleta dos dados da outra pessoa é da #347.
MENSAGEM_OUTRA_PESSOA = (
    "Entendi que o atendimento é para outra pessoa. Por enquanto não consigo seguir com esse caso por aqui. "
    "Vou encaminhar seu atendimento para a equipe dar continuidade."
)
# Provisório: o endereço do atendimento presencial depende da #335.
MENSAGEM_PRESENCIAL = (
    f"Entendi que você prefere o atendimento presencial. O NUDECON atende {HORARIO_NUDECON}. "
    "Em breve te passo o endereço; por enquanto, vou encaminhar seu atendimento para a equipe dar continuidade."
)
MENSAGEM_CANAL_NAO_ENTENDIDO = (
    "Não consegui entender como você prefere seguir. Vou encaminhar seu atendimento para a equipe dar continuidade."
)
MENSAGEM_HANDOFF = "Vou encaminhar seu atendimento para um atendente humano."
