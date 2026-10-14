"""Interpretação das respostas sim/não digitadas, como em develop.

Em develop, a mesma função `respostaEhSim` está copiada em quatro arquivos
(`subgrafos/identificarAssistido/graph.ts:23-30`, `subgrafos/cadastroPessoa/graph.ts:40-47`,
`fluxos/pessoaPresa/graph.ts:77-84` e `fluxos/violenciaDomestica/graph.ts:23-30`),
com o texto idêntico. Aqui é uma só, usada pelos subgrafos e pelos fluxos.
"""

from __future__ import annotations

import re
import unicodedata

from maria.shared._js import trim_js

_MARCAS_COMBINANTES = re.compile("[̀-ͯ]")


def resposta_eh_sim(resposta: str) -> bool:
    """`normalize("NFD")`, remoção de U+0300 a U+036F, `trim()` e `toLowerCase()`.

    Verdadeiro só para "true", "sim", "s" e "yes" depois disso, por igualdade
    exata. "sim." e "claro" são falsos, como em develop.
    """
    normalizado = trim_js(_MARCAS_COMBINANTES.sub("", unicodedata.normalize("NFD", resposta))).lower()
    return normalizado in ("true", "sim", "s", "yes")
