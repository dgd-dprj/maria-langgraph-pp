"""Casos que saíram da conferência contra as fixtures de contrato (#321).

As fixtures (`tests/fixtures/contrato/`) são respostas gravadas da versão TypeScript e nunca são
editadas (decisão C7, `MIGRACAO.md`, "As respostas gravadas são evidência, não teste de regressão").
Quando uma mudança legítima muda o valor de uma resposta gravada (o primeiro caso à vista é um
fluxo novo mudando `GET /fluxos`), o caso sai da conferência, e o comportamento novo ganha um teste
escrito. Campo novo e opcional não é caso aposentado: é `campos_posteriores.py` (#294).

O caso aposentado continua sendo enviado, na mesma ordem, porque os seguintes podem depender do
estado que ele deixa; só a comparação dele sai. Se ele voltar a bater com a gravação, a conferência
falha, para a entrada não ficar esquecida aqui.

Para aposentar um caso: uma entrada em `CASOS_APOSENTADOS[<conferência>]`, com o nome exato do caso,
a issue, o motivo e o teste escrito que cobre o comportamento novo (`test_casos_aposentados.py`
confere o registro).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

RAIZ_FIXTURES = Path("tests/fixtures/contrato")


@dataclass(frozen=True)
class CasoAposentado:
    issue: int
    motivo: str
    teste: str  # caminho a partir da raiz do repositório


# Conferência -> (arquivo de teste dela, nomes dos casos que ela percorre).
def _nomes_contrato() -> list[str]:
    return [i["nome"] for i in json.loads((RAIZ_FIXTURES / "indice.json").read_text(encoding="utf-8"))]


def _nomes_cenarios(pasta: str) -> list[str]:
    return [c["nome"] for c in json.loads((RAIZ_FIXTURES / pasta / "cenarios.json").read_text(encoding="utf-8"))]


CONFERENCIAS: dict[str, str] = {
    "contrato": "tests/api/test_contrato.py",
    "pr1": "tests/api/test_conferencia_pr1.py",
    "pr2": "tests/api/test_conferencia_pr2.py",
}


def nomes_dos_casos(conferencia: str) -> list[str]:
    if conferencia == "contrato":
        return _nomes_contrato()
    return _nomes_cenarios({"pr1": "conferencia-api-pr1", "pr2": "conferencia-api-pr2"}[conferencia])


# As três conferências rodam com o ambiente da produção (#324): as gravações são o contrato com a
# Tykhe, e é na produção que ele vale. Um teste (`test_fluxo_em_teste.py`) exige que este valor seja
# o mesmo que `infra/terraform/ecs.tf` declara. O que só muda no release, onde os fluxos em teste
# ligam, é coberto por testes escritos, e não pelas gravações.
AMBIENTE_DAS_CONFERENCIAS = "producao"

# #393 (decisão da Nicole, 2026-11-04): "Confirma que a pessoa presa é …?" mostra o nome mascarado.
_NOME_MASCARADO = CasoAposentado(
    issue=393, motivo="o nome do apenado sai mascarado na confirmação do RG", teste="tests/fluxos/test_pessoa_presa.py"
)

# Histórico dos casos de `GET /fluxos`: a #329 aposentou 6 (contrato `fluxos-200`; pr1 `fluxos`,
# `fluxos_query`, `auth_bearer_espacos_fluxos`, `auth_bearer_duplo_espaco_fluxos`; pr2
# `rota_get_fluxos_codificado`) quando o fluxo do plano de saúde entrou na lista. Com ele em teste,
# desligado na produção (#324), os 6 voltaram a bater com as gravações e saíram daqui (registro no
# `MIGRACAO.md`). As gravações não foram editadas.
# #475 (decisão da Nicole, 2026-11-12): a pergunta do RG mostra os formatos aceitos.
_PERGUNTA_DO_RG = CasoAposentado(issue=475, motivo="a pergunta do RG mostra os formatos aceitos", teste="tests/fluxos/test_pessoa_presa.py")
_IRMAO_E_IRMA = CasoAposentado(issue=212, motivo="o parentesco Irmão(a) virou Irmão e Irmã", teste="tests/shared/test_parentesco.py")

CASOS_APOSENTADOS: dict[str, dict[str, CasoAposentado]] = {
    "contrato": {
        "pessoa-presa-resposta-rg-200": _NOME_MASCARADO,
        "pessoa-presa-get-metadados-parciais-200": _NOME_MASCARADO,
        "pessoa-presa-resposta-texto-sem-opcoes-200": _PERGUNTA_DO_RG,
    },
    "pr1": {},
    "pr2": {
        "pp_rg": _NOME_MASCARADO,
        "pp_get_confirma_nome": _NOME_MASCARADO,
        # #394 (decisão da Nicole, 2026-11-12): a recusa do RG pelo formato diz a tentativa e dá um exemplo.
        "pp_rg_invalido": CasoAposentado(
            issue=394, motivo="a mensagem de recusa do RG pelo formato mudou", teste="tests/fluxos/test_pessoa_presa.py"
        ),
        "pp_sem_processo": _PERGUNTA_DO_RG,
        "orq_identifica_responde": _PERGUNTA_DO_RG,
        # #212 (decisão da Nicole, 2026-11-13): "Irmão(a)" virou "Irmão" e "Irmã"; a resposta "irmão" grava "Irmão".
        "pp_parentesco": _IRMAO_E_IRMA,
        "pp_get_concluido": _IRMAO_E_IRMA,
    },
}


def falhas_que_valem(nome: str, falhas_do_caso: list[str], aposentados: Mapping[str, CasoAposentado]) -> list[str]:
    """As falhas de um caso que contam na conferência.

    Caso fora da lista: as próprias falhas. Caso aposentado: nenhuma, a não ser que ele tenha
    voltado a bater com a gravação, o que vira falha de entrada esquecida."""
    caso = aposentados.get(nome)
    if caso is None:
        return falhas_do_caso
    if not falhas_do_caso:
        return [f"{nome}: aposentado (#{caso.issue}), mas voltou a bater com a gravação; tire a entrada de casos_aposentados.py"]
    return []


def falhas_da_conferencia(por_caso: Mapping[str, list[str]], aposentados: Mapping[str, CasoAposentado]) -> list[str]:
    """Junta as falhas de cada caso da conferência, aplicando a lista de aposentados."""
    return [f for nome, falhas in por_caso.items() for f in falhas_que_valem(nome, falhas, aposentados)]


def problemas_do_registro(registro: Mapping[str, Mapping[str, CasoAposentado]]) -> list[str]:
    """O que está errado no registro: conferência ou caso inexistente, teste que não existe ou não
    cita o caso nem a issue, motivo ou issue vazios."""
    problemas: list[str] = []
    for conferencia, casos in registro.items():
        if conferencia not in CONFERENCIAS:
            problemas.append(f"conferência inexistente: {conferencia}")
            continue
        existentes = set(nomes_dos_casos(conferencia))
        for nome, caso in casos.items():
            onde = f"{conferencia}/{nome}"
            if nome not in existentes:
                problemas.append(f"{onde}: o caso não existe nessa conferência")
            if caso.issue <= 0 or not caso.motivo.strip():
                problemas.append(f"{onde}: issue e motivo são obrigatórios")
            arquivo = Path(caso.teste)
            if not arquivo.name.startswith("test_") or not arquivo.is_file():
                problemas.append(f"{onde}: o teste {caso.teste} não existe")
            elif nome not in (texto := arquivo.read_text(encoding="utf-8")) and f"#{caso.issue}" not in texto:
                problemas.append(f"{onde}: o teste {caso.teste} não cita o caso nem a #{caso.issue}")
    return problemas
