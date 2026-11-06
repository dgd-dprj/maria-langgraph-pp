"""Conferência do e-mail que a pessoa informa (#425), sem consultar a internet.

Confere o formato (`nome@dominio.algo`) e os erros comuns de digitação nos provedores mais usados
(`gmial.com`, `hotmal.com`, `.con` no fim). Não confere se o domínio existe: isso seria uma consulta à
internet a cada e-mail (decisão da Nicole em 2026-11-06). Reaproveitável pela troca de contato da #426.

O e-mail é dado pessoal: nada aqui escreve em log.
"""

from __future__ import annotations

import re

_LOCAL = re.compile(r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*")
_ROTULO = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?")
_FINAL = re.compile(r"[a-z]{2,}")

# Provedores em que um erro de uma letra é quase sempre digitação.
PROVEDORES = ("gmail", "hotmail", "outlook", "yahoo", "icloud")
# Nomes certos que ficam a uma letra de um provedor e não podem ser confundidos com erro.
NOMES_CERTOS = frozenset({*PROVEDORES, "email", "ymail", "mail", "live", "msn", "bol", "uol", "terra", "globo", "ig", "me", "mac", "aol"})
# Finais que não existem e são erro de digitação de ".com".
FINAIS_ERRADOS = frozenset({"con", "cmo", "comm", "coom", "vom", "xom", "cpm", "ocm", "cim", "clm"})
# Finais que existem na internet, mas nos provedores são ".com" digitado pela metade.
FINAIS_ERRADOS_DE_PROVEDOR = frozenset({"co", "cm", "om"})
# Domínios de provedor que não existem, embora pareçam certos.
DOMINIOS_ERRADOS = frozenset({"gmail.com.br", "icloud.com.br"})
_PONTUACAO_DO_FIM = ".,;:!?)\"'"


def _distancia(a: str, b: str) -> int:
    """Distância de edição com troca de duas letras vizinhas (`gmial` fica a 1 de `gmail`)."""
    anterior2: list[int] = []
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            custo = 0 if ca == cb else 1
            valor = min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + custo)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                valor = min(valor, anterior2[j - 2] + 1)
            atual.append(valor)
        anterior2, anterior = anterior, atual
    return anterior[-1]


def _extrair(resposta: str) -> str | None:
    """O trecho com `@` da resposta ("meu e-mail é nome@gmail.com." vale). Nenhum ou mais de um: `None`."""
    candidatos = [parte for parte in resposta.split() if "@" in parte]
    if len(candidatos) != 1:
        return None
    # Ponto no começo é erro de formato, então só aspas e parênteses saem do começo.
    return candidatos[0].rstrip(_PONTUACAO_DO_FIM).lstrip("(\"'").lower()


def _dominio_com_erro(dominio: str) -> bool:
    if dominio in DOMINIOS_ERRADOS:
        return True
    rotulos = dominio.split(".")
    if rotulos[-1] in FINAIS_ERRADOS:
        return True
    nome = rotulos[0]
    if nome in PROVEDORES and ".".join(rotulos[1:]) in FINAIS_ERRADOS_DE_PROVEDOR:
        return True
    return nome not in NOMES_CERTOS and any(_distancia(nome, provedor) == 1 for provedor in PROVEDORES)


def conferir_email(resposta: str | None) -> str | None:
    """O e-mail da resposta, em minúsculas, ou `None` quando tem erro de formato ou de digitação comum."""
    if not resposta:
        return None
    email = _extrair(resposta)
    if email is None or email.count("@") != 1:
        return None
    local, dominio = email.split("@")
    if not _LOCAL.fullmatch(local) or len(local) > 64 or len(dominio) > 253:
        return None
    rotulos = dominio.split(".")
    if len(rotulos) < 2 or not all(_ROTULO.fullmatch(r) for r in rotulos) or not _FINAL.fullmatch(rotulos[-1]):
        return None
    return None if _dominio_com_erro(dominio) else email
