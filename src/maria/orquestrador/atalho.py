"""Atalho por palavra antes da IA (#553): a mensagem inteira é uma palavra só que nomeia o fluxo.

Achado da #553 (2026-11-25): a pessoa escreveu só "preso" e a conversa foi para "outros" da Tykhe. A IA do
multi-fluxo (release) leu a palavra sozinha como "prisão citada sem pedido" e devolveu nenhuma opção. Medido no
Bedrock (26/11): com o Qwen3 VL 235B, "preso." errou 5 de 5, "cadeia" 3 de 3, "detento" 2 de 3; com o Ministral
14B, todas as palavras soltas erraram. A produção (Haiku) acertou, mas o atalho vale nos dois caminhos: é 0 token e
não depende do modelo.

Segue o modelo do `parentesco_pela_resposta` (#212): lê pelas palavras o que não pede interpretação. Só a mensagem
inteira, depois de tirar caixa, acento, pontuação e espaços, conta. Frase com mais contexto ("meu marido foi preso e
quero me divorciar") continua com a IA, que separa o pedido do contexto.

A lista é decisão da Nicole (26/11): "preso", "presa", "cadeia", "detento" e "presidiário", com feminino e plural.
"""

from __future__ import annotations

import re
import unicodedata

from maria.fluxos import ID_PESSOA_PRESA

# Sem acento e em minúscula, como sai de `_palavra_unica`.
PALAVRAS_PESSOA_PRESA = frozenset(
    {
        "preso", "presa", "presos", "presas",
        "cadeia",
        "detento", "detenta", "detentos", "detentas",
        "presidiario", "presidiaria", "presidiarios", "presidiarias",
    }
)  # fmt: skip

# O motivo que vai no log (`atalho`), sem a mensagem.
MOTIVO_PESSOA_PRESA = "palavra_de_prisao"

ATALHOS: dict[frozenset[str], tuple[str, str]] = {PALAVRAS_PESSOA_PRESA: (ID_PESSOA_PRESA, MOTIVO_PESSOA_PRESA)}

_LETRAS = re.compile(r"[a-z0-9]+")


def _palavra_unica(mensagem: str) -> str | None:
    """A única palavra da mensagem, sem acento e em minúscula; None se houver mais de uma ou nenhuma.

    Pontuação, emoji e espaços em volta não contam ("Preso!", " preso. "). Hífen separa palavras."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", mensagem.lower()) if unicodedata.category(c) != "Mn")
    palavras = _LETRAS.findall(sem_acento)
    return palavras[0] if len(palavras) == 1 else None


def atalho_pela_palavra(mensagem: object) -> tuple[str, str] | None:
    """O fluxo e o motivo do atalho, ou None para a IA decidir."""
    if not isinstance(mensagem, str):
        return None
    palavra = _palavra_unica(mensagem)
    if palavra is None:
        return None
    for palavras, destino in ATALHOS.items():
        if palavra in palavras:
            return destino
    return None
