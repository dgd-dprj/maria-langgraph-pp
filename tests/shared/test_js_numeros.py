"""`String(n)`, `Number(v)` e `JSON.stringify(n)` do JS, contra a referência
executada no Node 24 (`tests/fixtures/js/numeros-js.json`, gerada pelo script
`numeros-js.mts` no worktree de develop @ 1157a6d)."""

import json
import math
from pathlib import Path

import pytest

from maria.shared._js import AUSENTE, json_stringify_js, numero_js, numero_para_texto, string_js

REF = json.loads(Path("tests/fixtures/js/numeros-js.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("entrada", "esperado"), sorted(REF["string"].items()))
def test_string_de_numero_como_o_js(entrada: str, esperado: str) -> None:
    assert numero_para_texto(float(entrada)) == esperado


@pytest.mark.parametrize(("entrada", "esperado"), sorted(REF["stringify"].items()))
def test_json_stringify_de_numero_como_o_js(entrada: str, esperado: str) -> None:
    assert json_stringify_js(float(entrada)) == esperado


@pytest.mark.parametrize(("entrada", "esperado"), sorted(REF["number"].items()))
def test_number_de_texto_como_o_js(entrada: str, esperado: str) -> None:
    assert numero_para_texto(numero_js(json.loads(entrada))) == esperado


def test_number_de_lista_como_o_js() -> None:
    lista = REF["lista"]
    assert numero_para_texto(numero_js([])) == lista["vazia"]
    assert numero_para_texto(numero_js([" 5"])) == lista["um"]
    assert numero_para_texto(numero_js([1, 2])) == lista["dois"]
    assert numero_para_texto(numero_js([[3]])) == lista["aninhada"]


def test_casos_que_o_objeto_da_referencia_nao_guarda() -> None:
    # -0 e 0 viram a mesma chave no objeto de referência; inteiro grande do JSON é double no JS.
    assert numero_para_texto(-0.0) == "0"
    assert numero_para_texto(12345678901234567890) == "12345678901234567000"
    assert numero_para_texto(math.nan) == "NaN"
    assert numero_para_texto(-math.inf) == "-Infinity"
    assert json_stringify_js(math.nan) == "null"
    assert numero_js(AUSENTE) != numero_js(AUSENTE)  # NaN
    assert numero_js(None) == 0.0
    assert numero_js({"a": 1}) != numero_js({"a": 1})  # NaN


def test_string_js() -> None:
    assert string_js(None) == "null"
    assert string_js(AUSENTE) == "undefined"
    assert string_js(["a", None, 2, AUSENTE, [1, [2]]]) == "a,,2,,1,2"
    assert string_js({"a": 1}) == "[object Object]"
    assert string_js(True) == "true"


def test_json_stringify_js_omite_undefined_no_objeto_e_poe_null_na_lista() -> None:
    assert json_stringify_js({"a": AUSENTE, "b": [AUSENTE, math.inf, 1e-7], "c": "ã"}) == '{"b":[null,null,1e-7],"c":"ã"}'
