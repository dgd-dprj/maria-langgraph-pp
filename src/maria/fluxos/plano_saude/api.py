"""Metadados e mensagens do fluxo Problemas com plano de saúde (NUDECON, issue #329).

Os textos marcados "provisório" valem até o NUDECON validar (#335) e a Tykhe
confirmar os destinos (#336).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Rascunho do time, não validado pelo NUDECON (#329, #335).
HORARIO_NUDECON = "de segunda a sexta, das 11h às 16h"


def extrair_metadados_plano_saude(values: Mapping[str, Any]) -> dict[str, Any]:
    """O que a Maria devolve à Tykhe além do CPF: com isso a Tykhe monta o e-mail do NUDECON (#345)."""
    metadados: dict[str, Any] = {}
    for chave in ("canal", "paraSi", "imagensRecebidas", "renda", "confirmou", "motivoHandoff"):
        valor = values.get(chave)
        if valor is not None:
            metadados[chave] = valor
    return metadados


# Provisório: o prazo e o que mais o NUDECON pede dependem da #335. Não promete tempo de resposta.
MENSAGEM_CONCLUIDO = "Pronto! Encaminhei seus dados para o NUDECON. A equipe vai entrar em contato com você."
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
# Provisório: sem as fotos o NUDECON não consegue analisar o caso; a equipe orienta o envio.
MENSAGEM_IMAGENS_PENDENTES = (
    "Ainda não recebi as fotos dos documentos. Vou encaminhar seu atendimento para a equipe te orientar como enviá-las."
)
MENSAGEM_RENDA_NAO_INFORMADA = "Não consegui entender sua renda mensal. Vou encaminhar seu atendimento para a equipe dar continuidade."
# Provisório: a correção de um dado por campo fica para outra issue; por ora a equipe corrige.
MENSAGEM_DADOS_NAO_CONFIRMADOS = "Tudo bem, os dados precisam de correção. Vou encaminhar seu atendimento para a equipe ajustar com você."
MENSAGEM_HANDOFF = "Vou encaminhar seu atendimento para um atendente humano."
