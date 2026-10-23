"""Auxiliares de semântica de JavaScript (`shared/_js.py`)."""

import pytest

from maria.shared._js import AUSENTE, texto_template


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (None, "null"),
        (AUSENTE, "undefined"),
        (True, "true"),
        (3.0, "3"),
        ("x", "x"),
        # `${{}}` e `${[]}` de JS: Object.prototype.toString e Array join(",").
        ({}, "[object Object]"),
        ({"a": 1}, "[object Object]"),
        ([], ""),
        ([1, None, "b", [2, 3], {}], "1,,b,2,3,[object Object]"),
    ],
)
def test_texto_template_como_template_literal_de_js(valor: object, esperado: str) -> None:
    assert texto_template(valor) == esperado
