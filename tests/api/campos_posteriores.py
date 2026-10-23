"""Campos que a API passou a devolver depois da gravação das fixtures de contrato (#294).

As fixtures (`tests/fixtures/contrato/`) são respostas gravadas da versão TypeScript e nunca são
editadas (decisão C7, `MIGRACAO.md`, "As respostas gravadas são evidência, não teste de regressão").
Quando a API ganha um campo novo e opcional no primeiro nível do corpo, as duas conferências contra
as fixtures (`test_contrato.py` e `test_conferencia_pr2.py`) tiram só esse campo da resposta obtida,
e o resto continua conferido byte a byte.

Para registrar um campo novo: uma entrada em `CAMPOS_POSTERIORES`, com a issue que o introduziu e o
teste escrito que cobre a presença e a ausência dele. Campo que não está aqui quebra a conferência.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class CampoPosterior:
    issue: int
    teste: str  # caminho a partir da raiz do repositório


CAMPOS_POSTERIORES: dict[str, CampoPosterior] = {
    "destino": CampoPosterior(issue=288, teste="tests/api/test_destino.py"),
}

_ESPACOS = " \t\n\r"
_DECODIFICADOR = json.JSONDecoder()


def _pular_espacos(texto: str, i: int) -> int:
    while i < len(texto) and texto[i] in _ESPACOS:
        i += 1
    return i


def _membros(corpo: str) -> list[tuple[str, int, int]] | None:
    """Chave, início e fim de cada membro do objeto do primeiro nível, como posições no texto.

    None quando o corpo não é um objeto JSON: nesse caso não há o que tirar."""
    i = _pular_espacos(corpo, 0)
    if not corpo.startswith("{", i):
        return None
    membros: list[tuple[str, int, int]] = []
    i = _pular_espacos(corpo, i + 1)
    try:
        if corpo[i] == "}":
            return membros if _pular_espacos(corpo, i + 1) == len(corpo) else None
        while True:
            if corpo[i] != '"':
                return None
            inicio = i
            chave, i = _DECODIFICADOR.raw_decode(corpo, i)
            i = _pular_espacos(corpo, i)
            if corpo[i] != ":":
                return None
            _, i = _DECODIFICADOR.raw_decode(corpo, _pular_espacos(corpo, i + 1))
            membros.append((chave, inicio, i))
            i = _pular_espacos(corpo, i)
            if corpo[i] == ",":
                i = _pular_espacos(corpo, i + 1)
                continue
            return membros if corpo[i] == "}" and _pular_espacos(corpo, i + 1) == len(corpo) else None
    except (ValueError, IndexError):
        return None


def sem_campos_posteriores(corpo: str) -> str:
    """O corpo sem os campos de `CAMPOS_POSTERIORES` do primeiro nível do objeto.

    O campo é cortado do texto original, com a vírgula que o separa do vizinho; nada é
    reserializado, então o resto fica como foi gravado (ordem das chaves, espaços, números
    como `1e-7`, escapes). Corpo que não é objeto JSON, ou sem nenhum desses campos, volta
    o mesmo. Mesmo nome dentro de objeto aninhado ou de um texto não é tocado."""
    while True:
        membros = _membros(corpo)
        if membros is None:
            return corpo
        k = next((k for k, (chave, _, _) in enumerate(membros) if chave in CAMPOS_POSTERIORES), None)
        if k is None:
            return corpo
        _, inicio, fim = membros[k]
        if k + 1 < len(membros):
            fim = membros[k + 1][1]
        elif k > 0:
            inicio = membros[k - 1][2]
        corpo = corpo[:inicio] + corpo[fim:]
