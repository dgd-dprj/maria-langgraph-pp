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

import decimal
import json
import math
import re
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


# O `\s` das regex de JS é o mesmo conjunto do trim(). O `\s` do Python, não.
CLASSE_ESPACO_JS: Final = f"[{_ESPACOS_JS}]"


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


def numero_para_texto(numero: float | int) -> str:
    """`String(n)` de JS (Number.prototype.toString, ECMA-262 6.1.6.1.20).

    O `repr` do Python e o JS escolhem os mesmos dígitos (o menor que faz a ida e
    volta), mas formatam diferente: `1e-07` contra `1e-7`, `nan` contra `NaN`,
    `-0.0` contra `0`. Inteiros acima de 2**53 viram double, como no JS."""
    if isinstance(numero, bool):
        return "true" if numero else "false"
    if isinstance(numero, int) and abs(numero) < 2**53:
        return str(numero)
    f = float(numero)
    if math.isnan(f):
        return "NaN"
    if math.isinf(f):
        return "Infinity" if f > 0 else "-Infinity"
    if f == 0:
        return "0"
    sinal = "-" if f < 0 else ""
    tupla = decimal.Decimal(repr(abs(f))).normalize().as_tuple()
    digitos = "".join(str(d) for d in tupla.digits)
    k = len(digitos)
    n = k + int(tupla.exponent)
    if k <= n <= 21:
        texto = digitos + "0" * (n - k)
    elif 0 < n <= 21:
        texto = digitos[:n] + "." + digitos[n:]
    elif -6 < n <= 0:
        texto = "0." + "0" * (-n) + digitos
    else:
        e = n - 1
        texto = digitos[0] + ("." + digitos[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sinal + texto


def string_js(valor: Any) -> str:
    """`String(valor)` de JS. Lista é `join(",")`, com null e undefined como ""."""
    if valor is AUSENTE:
        return "undefined"
    if valor is None:
        return "null"
    if isinstance(valor, str):
        return valor
    if isinstance(valor, bool | int | float):
        return numero_para_texto(valor)
    if isinstance(valor, list):
        return ",".join("" if item is None or item is AUSENTE else string_js(item) for item in valor)
    return "[object Object]"


_LITERAL_DECIMAL = re.compile(r"[+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)")
_LITERAL_PREFIXADO = re.compile(r"0([xXoObB])([0-9a-fA-F]+)")
_BASES = {"x": 16, "o": 8, "b": 2}


def numero_js(valor: Any) -> float:
    """`Number(valor)` de JS. Texto com espaço nas pontas, `""`, `"0x10"` e
    `"Infinity"` seguem o JS; o que não é número dá NaN, e não exceção."""
    if valor is AUSENTE:
        return math.nan
    if valor is None:
        return 0.0
    if isinstance(valor, bool):
        return 1.0 if valor else 0.0
    if isinstance(valor, int | float):
        return float(valor)
    if isinstance(valor, list):
        return numero_js(string_js(valor))
    if not isinstance(valor, str):
        return math.nan
    texto = trim_js(valor)
    if texto == "":
        return 0.0
    if texto in ("Infinity", "+Infinity"):
        return math.inf
    if texto == "-Infinity":
        return -math.inf
    prefixado = _LITERAL_PREFIXADO.fullmatch(texto)
    if prefixado:
        try:
            return float(int(prefixado.group(2), _BASES[prefixado.group(1).lower()]))
        except ValueError:
            return math.nan
    if _LITERAL_DECIMAL.fullmatch(texto):
        return float(texto)
    return math.nan


def json_stringify_js(valor: Any) -> str:
    """`JSON.stringify` com a formatação de número do JS (`1e-7`, `1e+21`) e
    NaN/Infinity como null. undefined some num objeto e vira null numa lista."""
    if valor is None or valor is AUSENTE:
        return "null"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, int | float):
        f = float(valor)
        return "null" if math.isnan(f) or math.isinf(f) else numero_para_texto(valor)
    if isinstance(valor, str):
        return json.dumps(valor, ensure_ascii=False)
    if isinstance(valor, list):
        return "[" + ",".join(json_stringify_js(item) for item in valor) + "]"
    if isinstance(valor, dict):
        partes = [f"{json.dumps(str(k), ensure_ascii=False)}:{json_stringify_js(v)}" for k, v in valor.items() if v is not AUSENTE]
        return "{" + ",".join(partes) + "}"
    return "null"
