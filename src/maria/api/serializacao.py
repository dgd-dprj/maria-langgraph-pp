"""Serialização da resposta pelo schema da rota, como o `fast-json-stringify` do Fastify 5.12.1.

A regra de cada tipo foi executada no Fastify de develop @ 1157a6d, com os
schemas das rotas (tabela em `tests/fixtures/contrato/serializacao-fastify.json`):

- **ordem das chaves** é a do schema, e não a do objeto; propriedade não
  declarada some, salvo com `additionalProperties: true`, quando vem depois;
- **string:** o valor é convertido (`7` vira `"7"`, `null` vira `""`, objeto vira
  `"[object Object]"`, lista vira `join(",")`);
- **number:** `null`, `""` e `[]` viram `0`; `Infinity` vira `null`; NaN ou texto
  que não é número LANÇAM (a rota responde 500);
- **objeto com propriedades:** qualquer valor que não é objeto vira `{}`;
- **objeto só com `additionalProperties`** (os `metadados`): texto e lista viram
  objeto indexado; número, booleano e `null` viram `{}`;
- **array:** `null` vira `[]`; um valor que não é lista LANÇA;
- undefined (AUSENTE ou chave ausente) é omitido.
"""

from __future__ import annotations

import json
import math
from typing import Any

from maria.shared._js import AUSENTE, json_stringify_js, numero_js, numero_para_texto, string_js

Schema = dict[str, Any]


class ErroSerializacao(Exception):
    """O fast-json-stringify lançou: o Fastify responde 500 com esta mensagem."""


def _texto(valor: Any) -> str:
    # asString do fast-json-stringify: null vira "", o resto é String(valor).
    return json.dumps("" if valor is None else string_js(valor), ensure_ascii=False)


def _numero(valor: Any) -> str:
    n = numero_js(valor)
    if math.isnan(n):
        raise ErroSerializacao(f'The value "{string_js(valor)}" cannot be converted to a number.')
    if math.isinf(n):
        return "null"
    # O número original (inteiro grande, por exemplo) e não a conversão para float.
    return numero_para_texto(valor if isinstance(valor, int | float) and not isinstance(valor, bool) else n)


def _objeto_indexado(valor: Any) -> dict[str, Any]:
    if isinstance(valor, dict):
        return valor
    if isinstance(valor, str | list):
        return {str(i): item for i, item in enumerate(valor)}
    return {}


def _objeto(schema: Schema, valor: Any, caminho: str) -> str:
    propriedades: Schema = schema.get("properties", {})
    adicionais = schema.get("additionalProperties") is True
    if not isinstance(valor, dict):
        if not adicionais or propriedades:
            return "{}"
        valor = _objeto_indexado(valor)
    partes: list[str] = []
    for nome, sub in propriedades.items():
        if nome in valor and valor[nome] is not AUSENTE:
            partes.append(f"{json.dumps(nome, ensure_ascii=False)}:{_serializar(sub, valor[nome], f'{caminho}/properties/{nome}')}")
    if adicionais:
        for nome, item in valor.items():
            if nome not in propriedades and item is not AUSENTE:
                partes.append(f"{json.dumps(str(nome), ensure_ascii=False)}:{json_stringify_js(item)}")
    return "{" + ",".join(partes) + "}"


def _lista(schema: Schema, valor: Any, caminho: str) -> str:
    if valor is None:
        return "[]"
    if not isinstance(valor, list):
        raise ErroSerializacao(f"The value of '{caminho}' does not match schema definition.")
    itens = schema.get("items", {})
    partes = []
    for item in valor:
        if item is AUSENTE:
            raise ErroSerializacao("Cannot read properties of undefined (reading 'toString')")
        partes.append(_serializar(itens, item, f"{caminho}/items"))
    return "[" + ",".join(partes) + "]"


def _serializar(schema: Schema, valor: Any, caminho: str) -> str:
    tipo = schema.get("type")
    if tipo == "string":
        return _texto(valor)
    if tipo == "number":
        return _numero(valor)
    if tipo == "array":
        return _lista(schema, valor, caminho)
    if tipo == "object":
        return _objeto(schema, valor, caminho)
    return json_stringify_js(valor)


def serializar(schema: Schema | None, valor: Any) -> str:
    """Corpo da resposta. Sem schema para o status, é o `JSON.stringify`.

    Na raiz, um texto sai cru (o Fastify não o serializa), e um valor que não é
    objeto, num schema de objeto, sai `{}`."""
    if valor is AUSENTE:
        return ""
    if schema is None:
        return valor if isinstance(valor, str) else json_stringify_js(valor)
    if isinstance(valor, str):
        return valor
    if schema.get("type") == "object" and not isinstance(valor, dict):
        return "{}"
    return _serializar(schema, valor, "#")
