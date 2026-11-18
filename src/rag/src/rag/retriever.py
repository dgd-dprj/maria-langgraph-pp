"""Ingestão e recuperação semântica dos contratos da API Verde."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from langchain_aws import BedrockEmbeddings

from .ingest_documentos import carregar_documentos
from .progresso import CallbackProgresso, ProgressoIngest
from .vector_store import ArmazenamentoVetorial


class RecuperadorVerde:
    def __init__(self, armazenamento: ArmazenamentoVetorial, embeddings: BedrockEmbeddings) -> None:
        self.armazenamento = armazenamento
        self.embeddings = embeddings

    def indexar(
        self,
        pasta: str | Path | None = None,
        callback_progresso: CallbackProgresso | None = None,
        tamanho_lote: int = 25,
    ) -> dict[str, int]:
        """Gera embeddings apenas para documentos novos ou alterados, com acompanhamento de progresso."""
        if callback_progresso:
            callback_progresso(
                ProgressoIngest(
                    etapa="carregando",
                    mensagem="Iniciando leitura e fragmentação dos documentos...",
                )
            )

        documentos = carregar_documentos(pasta=pasta, callback_progresso=callback_progresso)

        if callback_progresso:
            callback_progresso(
                ProgressoIngest(
                    etapa="comparacao",
                    mensagem="Consultando hashes existentes no pgvector...",
                    atual=0,
                    total=len(documentos),
                )
            )

        hashes_existentes = self.armazenamento.hashes_existentes()
        alterados = [(documento, hashlib.sha256(documento.conteudo.encode("utf-8")).hexdigest()) for documento in documentos]
        pendentes = [(documento, hash_atual) for documento, hash_atual in alterados if hashes_existentes.get(documento.id) != hash_atual]
        ja_indexados = len(documentos) - len(pendentes)

        if callback_progresso:
            callback_progresso(
                ProgressoIngest(
                    etapa="comparacao",
                    mensagem=f"Verificação concluída: {len(documentos)} total, {ja_indexados} já indexados, {len(pendentes)} pendentes.",
                    atual=ja_indexados,
                    total=len(documentos),
                    detalhes={"total_documentos": len(documentos), "ja_indexados": ja_indexados, "pendentes": len(pendentes)},
                )
            )

        if pendentes:
            total_pendentes = len(pendentes)
            tamanho_lote_efetivo = max(1, tamanho_lote)
            total_lotes = (total_pendentes + tamanho_lote_efetivo - 1) // tamanho_lote_efetivo
            processados = 0

            for i in range(0, total_pendentes, tamanho_lote_efetivo):
                lote = pendentes[i : i + tamanho_lote_efetivo]
                lote_idx = (i // tamanho_lote_efetivo) + 1

                if callback_progresso:
                    msg_lote = f"Gerando embeddings: lote {lote_idx}/{total_lotes} ({processados}/{total_pendentes} concluídos)..."
                    callback_progresso(
                        ProgressoIngest(
                            etapa="embeddings",
                            mensagem=msg_lote,
                            atual=processados,
                            total=total_pendentes,
                            detalhes={"lote": lote_idx, "total_lotes": total_lotes, "lote_tamanho": len(lote)},
                        )
                    )

                docs_lote = [documento for documento, _ in lote]
                hashes_lote = [hash_atual for _, hash_atual in lote]
                textos_lote = [doc.conteudo for doc in docs_lote]

                vetores = self.embeddings.embed_documents(textos_lote)
                self.armazenamento.salvar_documentos(docs_lote, hashes_lote, vetores)

                processados += len(lote)
                if callback_progresso:
                    callback_progresso(
                        ProgressoIngest(
                            etapa="embeddings",
                            mensagem=f"Lote {lote_idx}/{total_lotes} concluído ({processados}/{total_pendentes} salvos no pgvector).",
                            atual=processados,
                            total=total_pendentes,
                            detalhes={"lote": lote_idx, "total_lotes": total_lotes, "processados": processados},
                        )
                    )

        if callback_progresso:
            callback_progresso(
                ProgressoIngest(
                    etapa="persistindo",
                    mensagem="Sincronizando pgvector e removendo documentos obsoletos...",
                    atual=len(documentos),
                    total=len(documentos),
                )
            )

        self.armazenamento.excluir_ids_ausentes({documento.id for documento in documentos})
        resumo = {"documentos": len(documentos), "embeddings_gerados": len(pendentes), "já_indexados": ja_indexados}

        if callback_progresso:
            msg_fim = f"Indexação concluída: {resumo['embeddings_gerados']} gerados, {resumo['já_indexados']} reaproveitados."
            callback_progresso(
                ProgressoIngest(
                    etapa="concluido",
                    mensagem=msg_fim,
                    atual=len(documentos),
                    total=len(documentos),
                    resumo=resumo,
                    detalhes={"resumo": resumo},
                )
            )

        return resumo

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
