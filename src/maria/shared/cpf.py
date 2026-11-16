"""#497 (decisão da Nicole, 2026-11-16): o CPF conferido pelos dígitos verificadores, sem IA, antes de consultar o Verde.

Um número é CPF válido quando, sem ponto, traço e espaços, tem 11 dígitos, não são todos iguais e os dois últimos são
os dígitos verificadores dos nove primeiros, pela regra oficial (resto da divisão por 11).

Usado na pergunta do RG da pessoa presa (um CPF ali não vai ao Verde) e nas perguntas do CPF (um CPF com a conta
errada não vai ao Verde). A Tykhe faz a mesma conferência no fluxo dela (identificadores na #497).
"""

from __future__ import annotations

import re

from maria.shared import _js

# Os mesmos separadores do RG (#343): ponto, traço (também os do celular: ‐ ‑ – —) e espaços.
_SEPARADORES = re.compile(f"[.\\-‐‑–—]|{_js.CLASSE_ESPACO_JS}")
_ONZE_DIGITOS = re.compile(r"[0-9]{11}")


def _digito_verificador(numeros: str) -> int:
    """Pesos de `len + 1` até 2; resto da divisão por 11: menor que 2 dá 0, senão 11 menos o resto."""
    peso_inicial = len(numeros) + 1
    soma = sum(int(digito) * (peso_inicial - posicao) for posicao, digito in enumerate(numeros))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def cpf_valido(texto: object) -> bool:
    """O texto é um CPF de verdade? Só pontuação e espaços são tirados: com letra ou outro símbolo, não é."""
    if not isinstance(texto, str):
        return False
    numeros = _SEPARADORES.sub("", texto)
    if _ONZE_DIGITOS.fullmatch(numeros) is None or len(set(numeros)) == 1:
        return False
    return _digito_verificador(numeros[:9]) == int(numeros[9]) and _digito_verificador(numeros[:10]) == int(numeros[10])
