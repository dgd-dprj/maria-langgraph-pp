"""Tipos dos documentos recuperados pelo RAG do Verde."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Documento:
    id: str
    conteudo: str
    fonte: str
    endpoint: str = ""
    metodo: str = ""
    assunto: str = ""

