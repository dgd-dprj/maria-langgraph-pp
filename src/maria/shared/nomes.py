"""Nome mascarado para as confirmações (#393, decisão da Nicole de 2026-11-04).

Quem digita o CPF ou o RG de outra pessoa não pode ver o nome completo dela: a confirmação
mostra só o primeiro nome e as iniciais dos outros.
"""

from __future__ import annotations

# Partículas que não viram inicial: "Maria da Silva" fica "Maria S.".
_PARTICULAS = frozenset({"da", "das", "de", "do", "dos", "e", "di", "du"})


def nome_mascarado(nome: str) -> str:
    """Primeiro nome e as iniciais dos outros: "MARIA DA SILVA SANTOS" vira "Maria S. S.".
    Palavra que não começa com letra, como "(mock)", fica fora."""
    palavras = [p for p in nome.split() if p[:1].isalpha()]
    if not palavras:
        return nome
    primeiro = palavras[0][:1].upper() + palavras[0][1:].lower()
    iniciais = [f"{p[:1].upper()}." for p in palavras[1:] if p.lower() not in _PARTICULAS]
    return " ".join([primeiro, *iniciais])
