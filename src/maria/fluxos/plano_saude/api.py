"""Metadados e mensagens do fluxo Problemas com plano de saúde (NUDECON, issue #329).

Os textos marcados "provisório" valem até o NUDECON validar (#335) e a Tykhe
confirmar os destinos (#336).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Rascunho do time, não validado pelo NUDECON (#329, #335).
HORARIO_NUDECON = "de segunda a sexta, das 11h às 16h"

# `municipio.id` que o `GET /cep` do Verde devolve para o Rio de Janeiro (informado pelo Ícaro em 2026-10-28).
ID_MUNICIPIO_RIO = 3643
# Provisório (decisão do Ícaro em 2026-10-28): assunto qualquer só para o Verde indicar a unidade de quem mora fora do Rio.
# O assunto definitivo (3312 ou 8420, por tipo de pedido) e a lista de unidades dependem da reunião com os responsáveis e da #265.
ID_ASSUNTO_UNIDADE_FORA_DO_RIO = 3050
# Provisório (decisão do Ícaro em 2026-10-28): horário da unidade quando o Verde não informa.
HORARIO_UNIDADE_PADRAO = "de segunda a sexta, das 10h às 17h"


def extrair_metadados_plano_saude(values: Mapping[str, Any]) -> dict[str, Any]:
    metadados: dict[str, Any] = {}
    for chave in ("canal", "paraSi", "relato", "renda", "foraDoRio", "motivoHandoff"):
        valor = values.get(chave)
        if valor is not None:
            metadados[chave] = valor
    return metadados


# Provisório: o texto final, com documentos e prazo, é da #335; o envio ao NUDECON, da #345.
MENSAGEM_CONCLUIDO = "Recebi suas informações e vou encaminhar seu atendimento ao NUDECON, que entra em contato com você."
MENSAGEM_IMAGENS_PENDENTES = "Não recebi as imagens dos documentos. Vou encaminhar seu atendimento para a equipe dar continuidade."
MENSAGEM_SITUACAO_NAO_INFORMADA = "Não consegui entender a sua situação. Vou encaminhar seu atendimento para a equipe dar continuidade."
MENSAGEM_RENDA_NAO_ENTENDIDA = "Não consegui entender a sua renda. Vou encaminhar seu atendimento para a equipe dar continuidade."
MENSAGEM_DADOS_NAO_CONFIRMADOS = "Não consegui confirmar seus dados. Vou encaminhar seu atendimento para a equipe dar continuidade."
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
# Provisório: a orientação de qual unidade procurar fora do Rio é da #331.
MENSAGEM_FORA_DO_RIO = (
    "O NUDECON atende quem mora no município do Rio de Janeiro. "
    "Vou encaminhar seu atendimento para a equipe te orientar sobre onde procurar atendimento."
)
# Sem encaminhamento: quem mora fora do Rio recebe a unidade que deve procurar e a conversa conclui.
MENSAGEM_FORA_DO_RIO_COM_UNIDADE = "O NUDECON atende quem mora no município do Rio de Janeiro. Pelo seu endereço, procure: {unidade}."
MENSAGEM_MUNICIPIO_NAO_IDENTIFICADO = "Não consegui confirmar o seu município. Vou encaminhar seu atendimento para a equipe."
MENSAGEM_FALHA_INFRA_VERDE = "Não consegui consultar o seu endereço agora. Vou encaminhar seu atendimento para a equipe."
# Qualquer falha inesperada do fluxo: o assistido não pode ficar sem atendimento (#329).
MENSAGEM_ERRO_INTERNO = "Tive um problema para continuar o seu atendimento. Vou encaminhar para a equipe dar continuidade."
MENSAGEM_HANDOFF = "Vou encaminhar seu atendimento para um atendente humano."
