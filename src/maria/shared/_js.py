"""Semântica de JavaScript usada pelas integrações e pela IA, para a tradução ser fiel.

O código de develop lê respostas do Verde e do WhatsApp, e os argumentos da
ferramenta devolvidos pelo modelo, com `o.k`, `o?.k`, `??` e testes de verdade
(`if (x)`). Em Python, `dict.get`, `or` e `not` não fazem a
mesma coisa:

- `o.k` com `o` igual a null LANÇA TypeError em JS; `o?.k` devolve undefined.
- JS distingue chave ausente (undefined) de chave com null; `dict.get` não.
- `{}` e `[]` são verdadeiros em JS; em Python, `not {}` é True.

`AUSENTE` representa o undefined do JS. Nos objetos devolvidos ao resto do
sistema, AUSENTE nunca aparece: a chave simplesmente não é escrita, como o
JSON.stringify faz com undefined.
"""

from __future__ import annotations

import json
import math
from typing import Any, Final


class _Ausente:
    __slots__ = ()

    def __repr__(self) -> str:
        return "AUSENTE"

    def __bool__(self) -> bool:
        return False


AUSENTE: Final = _Ausente()


def prop(o: Any, chave: str) -> Any:
    """`o.chave` de JS. Lança TypeError se `o` for null ou undefined."""
    if o is None or o is AUSENTE:
        raise TypeError(f"Cannot read properties of {'null' if o is None else 'undefined'} (reading '{chave}')")
    if isinstance(o, dict):
        return o.get(chave, AUSENTE)
    return AUSENTE


def opt(o: Any, chave: str) -> Any:
    """`o?.chave` de JS. Devolve AUSENTE se `o` for null ou undefined."""
    if o is None or o is AUSENTE:
        return AUSENTE
    return prop(o, chave)


def indice(o: Any, i: int) -> Any:
    """`o[i]` de JS para listas; AUSENTE fora do intervalo ou em outro tipo."""
    if o is None or o is AUSENTE:
        raise TypeError(f"Cannot read properties of {'null' if o is None else 'undefined'} (reading '{i}')")
    if isinstance(o, list) and 0 <= i < len(o):
        return o[i]
    if isinstance(o, str) and 0 <= i < len(o):
        return o[i]
    return AUSENTE


def coalesce(valor: Any, padrao: Any) -> Any:
    """`valor ?? padrao` de JS."""
    return padrao if valor is None or valor is AUSENTE else valor


def verdadeiro(valor: Any) -> bool:
    """Verdade de JS: só undefined, null, false, 0, NaN e "" são falsos. `{}` e `[]` são verdadeiros."""
    if valor is None or valor is AUSENTE or valor is False:
        return False
    if isinstance(valor, bool):
        return True
    if isinstance(valor, int | float):
        return valor != 0 and not (isinstance(valor, float) and math.isnan(valor))
    if isinstance(valor, str):
        return valor != ""
    return True


def definir(destino: dict[str, Any], chave: str, valor: Any) -> None:
    """Escreve a chave só se o valor não for undefined (null é escrito)."""
    if valor is not AUSENTE:
        destino[chave] = valor


def texto_template(valor: Any) -> str:
    """`${valor}` de um template literal de JS."""
    if valor is AUSENTE:
        return "undefined"
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, float) and valor.is_integer() and abs(valor) < 1e21:
        return str(int(valor))
    # Array.prototype.toString é join(","), com null e undefined como "".
    if isinstance(valor, list):
        return ",".join("" if item is None or item is AUSENTE else texto_template(item) for item in valor)
    if isinstance(valor, dict):
        return "[object Object]"
    return str(valor)


# WhiteSpace e LineTerminator do ECMAScript (ECMA-262, seções 12.2 e 12.3): o que
# String.prototype.trim() remove. Inclui U+FEFF (o BOM) e NÃO inclui os
# separadores \x1c a \x1f, ao contrário do str.strip() do Python.
_ESPACOS_JS = "\u0009\u000a\u000b\u000c\u000d                  　﻿"


def trim_js(texto: str) -> str:
    """`texto.trim()` de JS."""
    return texto.strip(_ESPACOS_JS)



def _recusar_constante(nome: str) -> Any:
    # JSON.parse não aceita NaN nem Infinity; o json do Python aceita por padrão.
    raise ValueError(f"Unexpected token in JSON: {nome}")


def json_parse(bruto: bytes) -> Any:
    """`res.json()` do fetch: corpo decodificado como UTF-8 (sem BOM, com
    substituição de bytes inválidos) e JSON.parse estrito."""
    return json.loads(bruto.decode("utf-8-sig", errors="replace"), parse_constant=_recusar_constante)


def json_stringify(valor: Any) -> str:
    """`JSON.stringify` para os corpos enviados: sem espaços e com UTF-8 cru.
    None vira null (como o null de JS); undefined é chave ausente no dict."""
    return json.dumps(valor, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
