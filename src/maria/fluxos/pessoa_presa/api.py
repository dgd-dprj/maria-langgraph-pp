"""Metadados e mensagens do fluxo de pessoa presa (develop: `fluxos/pessoaPresa/api.ts`).

O `metadadosSchemaPessoaPresa` não é traduzido (spec 05, decisão 3).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from maria.shared import _js


def _resumir(dados: Any, campos: tuple[str, ...]) -> Any:
    """`if (!d) return undefined; return {campo: d.campo, ...}`. Dentro do objeto,
    o campo undefined some do JSON e o null fica."""
    if not _js.verdadeiro(dados):
        return _js.AUSENTE
    resumo: dict[str, Any] = {}
    for campo in campos:
        _js.definir(resumo, campo, _js.prop(dados, campo))
    return resumo


def extrair_metadados_pessoa_presa(values: Mapping[str, Any]) -> dict[str, Any]:
    """Chaves na ordem de develop: a comparação de contrato do `api` compara bytes.

    Canal ausente nos values é omitido e `None` vira `null`, salvo em `rg`, onde
    `None` é o undefined gravado por `prepararPerguntaRgInvalido` (divergência
    aceita, MIGRACAO.md) e por isso é omitido. `dadosPessoa` vai inteiro (#237).
    """
    metadados: dict[str, Any] = {}
    _js.definir(metadados, "parentesco", values.get("parentesco", _js.AUSENTE))
    _js.definir(metadados, "temProcesso", values.get("temProcesso", _js.AUSENTE))
    _js.definir(metadados, "numeroProcesso", values.get("numeroProcesso", _js.AUSENTE))
    _js.definir(metadados, "dadosProcesso", _resumir(values.get("dadosProcesso", _js.AUSENTE), ("id", "origem")))
    rg = values.get("rg")
    if rg is not None:
        metadados["rg"] = rg
    _js.definir(
        metadados,
        "dadosApenado",
        _resumir(values.get("dadosApenado", _js.AUSENTE), ("idSeap", "idPessoa", "nome", "situacao", "tipoPreso", "regime")),
    )
    _js.definir(metadados, "dadosPessoa", values.get("dadosPessoa", _js.AUSENTE))
    if _js.verdadeiro(values.get("motivoHandoff", _js.AUSENTE)):
        metadados["motivoHandoff"] = values["motivoHandoff"]
    return metadados


MENSAGEM_CONCLUIDO = "Show! Já confirmei os dados da pessoa presa. Vou seguir com o encaminhamento a partir daqui."
MENSAGEM_HANDOFF = "Não consegui confirmar os dados da pessoa presa. Vou encaminhar seu atendimento pra equipe verificar com mais calma."
MENSAGEM_HANDOFF_SEM_NUMERO_PROCESSO = (
    "Já confirmei os dados da pessoa presa, mas como você não tem o número do processo, "
    "vou encaminhar seu atendimento pra equipe localizar isso e dar continuidade."
)
MENSAGEM_HANDOFF_ORIGEM_NAO_SUPORTADA = (
    "Já confirmei os dados da pessoa presa, mas o processo informado tem uma origem que ainda não consigo tratar por aqui. "
    "Vou encaminhar seu atendimento pra equipe dar continuidade."
)
MENSAGEM_FALHA_CADASTRO = (
    "Não consegui localizar nem cadastrar seus dados no sistema. Vou encaminhar seu atendimento pra um atendente confirmar manualmente."
)
