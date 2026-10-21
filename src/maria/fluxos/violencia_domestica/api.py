"""Metadados e mensagens do fluxo de violência doméstica (develop: `fluxos/violenciaDomestica/api.ts`).

O `metadadosSchemaViolenciaDomestica` não é traduzido (spec 05, decisão 3).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from maria.shared import _js

_SEMPRE = (
    "ehVitima",
    "temProcesso",
    "numeroProcesso",
    "dadosProcesso",
    "temRegistroOcorrencia",
    "dadosPessoa",
    "orgaosViolenciaDomestica",
)


def extrair_metadados_violencia_domestica(values: Mapping[str, Any]) -> dict[str, Any]:
    """Chaves na ordem de develop: a comparação de contrato do `api` compara bytes.

    Em develop, um canal sem valor vira `undefined` e some do JSON; `null`
    fica. Aqui, canal ausente nos values é omitido e `None` vira `null`.
    `dadosPessoa` vai inteiro, com o endereço (#237).
    """
    metadados: dict[str, Any] = {}
    for chave in _SEMPRE:
        _js.definir(metadados, chave, values.get(chave, _js.AUSENTE))
    if _js.verdadeiro(values.get("tipoEncaminhamento", _js.AUSENTE)):
        metadados["tipoEncaminhamento"] = values["tipoEncaminhamento"]
    if _js.verdadeiro(values.get("motivoHandoff", _js.AUSENTE)):
        metadados["motivoHandoff"] = values["motivoHandoff"]
    # `encaminhamentoId !== undefined`: no canal, None é o undefined de develop
    # (divergência aceita do `id: null`, MIGRACAO.md).
    if values.get("encaminhamentoId") is not None:
        metadados["encaminhamentoId"] = values["encaminhamentoId"]
    return metadados


MENSAGEM_NAO_VITIMA = "Esse atendimento é destinado apenas para quem é vítima da violência. Vou encaminhar você para um atendente humano."
MENSAGEM_SEM_ORGAO_DISPONIVEL = (
    "Não encontrei um órgão disponível pra encaminhar seu caso agora. Por favor, ligue 129 pra Central de Relacionamento com o Cidadão."
)
MENSAGEM_FALHA_ENCAMINHAMENTO = (
    "Identifiquei o órgão certo pro seu caso, mas tive um problema técnico ao registrar o encaminhamento. "
    "Vou passar seu atendimento pra equipe confirmar manualmente."
)
MENSAGEM_FALHA_CADASTRO = (
    "Não consegui localizar nem cadastrar seus dados no sistema. Vou encaminhar seu atendimento pra um atendente confirmar manualmente."
)
MENSAGEM_CPF_NAO_ENCONTRADO = (
    "Não consegui localizar seus dados com o CPF informado. Vou encaminhar seu atendimento pra um atendente confirmar manualmente."
)
MENSAGEM_CONCLUIDO = "Vou seguir com o encaminhamento do seu atendimento."
MENSAGEM_HANDOFF = "Vou encaminhar seu atendimento para um atendente humano."
