"""Tipos e normalização do catálogo usado na recuperação de candidatos."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CandidatoCatalogo:
    id: str
    nome: str
    descricao: str
    palavras_chave: tuple[str, ...] = ()
    dados: dict[str, object] | None = None

    @property
    def texto_embedding(self) -> str:
        palavras = ", ".join(self.palavras_chave)
        partes = [f"Nome: {self.nome}", f"Descrição: {self.descricao}"]
        if palavras:
            partes.append(f"Palavras-chave: {palavras}")
        return "\n".join(partes)

    @property
    def texto_busca(self) -> str:
        return normalizar_texto(" ".join((self.nome, self.descricao, *self.palavras_chave)))


def normalizar_texto(texto: str) -> str:
    """Normaliza caixa e acentos antes da busca lexical no Postgres."""
    sem_acentos = unicodedata.normalize("NFKD", texto.casefold()).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", sem_acentos))

