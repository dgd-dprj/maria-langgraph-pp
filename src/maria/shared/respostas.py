"""Interpretação das respostas sim/não digitadas, como em develop (`shared/respostaSimNao.ts`, #234).

Usada pelos nós sim/não dos fluxos e subgrafos e pela confirmação de TTL do
módulo api. O contrato com a Tykhe prevê "true"/"false" crus, mas na prática ela
às vezes repassa o texto que a pessoa digitou ("Sim"/"Não", com acento e
maiúscula variáveis; achado ao vivo em 2026-08-31), e o bridge do WhatsApp
sempre repassa o texto digitado. Antes do #234, a mesma `respostaEhSim` estava
copiada em quatro arquivos de develop, com o texto idêntico.
"""

from __future__ import annotations

import re
import unicodedata

from maria.shared._js import trim_js

_MARCAS_COMBINANTES = re.compile("[̀-ͯ]")

_SIM = frozenset(("true", "sim", "s", "yes"))
_NAO = frozenset(("false", "nao", "n", "no"))


def normalizar_resposta(resposta: str) -> str:
    """`normalize("NFD")`, remoção de U+0300 a U+036F (acentos), `trim()` e `toLowerCase()`."""
    return trim_js(_MARCAS_COMBINANTES.sub("", unicodedata.normalize("NFD", resposta))).lower()


def resposta_eh_sim(resposta: str) -> bool:
    """Verdadeiro só para "true", "sim", "s" e "yes" depois de normalizar, por
    igualdade exata. "sim." e "claro" são falsos, como em develop."""
    return normalizar_resposta(resposta) in _SIM


def resposta_eh_nao(resposta: str) -> bool:
    """Verdadeiro só para "false", "nao", "n" e "no" depois de normalizar."""
    return normalizar_resposta(resposta) in _NAO
