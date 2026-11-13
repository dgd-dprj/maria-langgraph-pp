"""Ingestão e recuperação semântica dos contratos da API Verde."""

from __future__ import annotations

import hashlib
from typing import Any

from langchain_aws import BedrockEmbeddings

from .ingest_documentos import carregar_documentos
from .vector_store import ArmazenamentoVetorial


class RecuperadorVerde:
    def __init__(self, armazenamento: ArmazenamentoVetorial, embeddings: BedrockEmbeddings) -> None:
        self.armazenamento = armazenamento
        self.embeddings = embeddings

    def indexar(self) -> dict[str, int]:
        """Gera embeddings apenas para documentos novos ou alterados."""
        documentos = carregar_documentos()
        hashes_existentes = self.armazenamento.hashes_existentes()
        alterados = [
            (documento, hashlib.sha256(documento.conteudo.encode("utf-8")).hexdigest())
            for documento in documentos
        ]
        pendentes = [(documento, hash_atual) for documento, hash_atual in alterados if hashes_existentes.get(documento.id) != hash_atual]

        if pendentes:
            vetores = self.embeddings.embed_documents([documento.conteudo for documento, _ in pendentes])
            self.armazenamento.salvar_documentos(
                [documento for documento, _ in pendentes],
                [hash_atual for _, hash_atual in pendentes],
                vetores,
            )

        self.armazenamento.excluir_ids_ausentes({documento.id for documento in documentos})
        return {"documentos": len(documentos), "embeddings_gerados": len(pendentes), "já_indexados": len(documentos) - len(pendentes)}

    def buscar(self, consulta: str, limite: int = 3) -> list[dict[str, Any]]:
        vetor = self.embeddings.embed_query(consulta)
        return self.armazenamento.buscar(vetor, limite=limite)


def criar_documento_de_mensagem(mensagem: str, endpoint: str = "", metodo: str = "", status_http: int | None = None) -> str:
    """Acrescenta contexto observável da chamada ao texto pesquisado."""
    partes = [f"Mensagem da API Verde: {mensagem}"]
    if endpoint:
        partes.append(f"Endpoint: {metodo.upper()} {endpoint}".strip())
    if status_http is not None:
        partes.append(f"Status HTTP: {status_http}")
    return "\n".join(partes)
