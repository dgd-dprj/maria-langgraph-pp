"""Recuperação semântica ou híbrida dos candidatos do orquestrador.

Este índice é separado dos documentos Swagger. A busca híbrida fica desligada
por padrão porque a medição registrada na issue #353 não justificou ativá-la.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from typing import Any

from langchain_aws import BedrockEmbeddings

from .catalogo import CandidatoCatalogo
from .vector_store import ArmazenamentoVetorial

LIMITE_CANDIDATOS = 15
K_RRF = 60


class RecuperadorCatalogo:
    def __init__(self, armazenamento: ArmazenamentoVetorial, embeddings: BedrockEmbeddings) -> None:
        self.armazenamento = armazenamento
        self.embeddings = embeddings

    def indexar(self, candidatos: Sequence[CandidatoCatalogo], sincronizar_completo: bool = True) -> dict[str, int]:
        ids = [candidato.id for candidato in candidatos]
        if len(ids) != len(set(ids)):
            raise ValueError("O catálogo contém IDs de candidato duplicados.")
        hashes_existentes = self.armazenamento.hashes_catalogo_existentes()
        ordens_existentes = self.armazenamento.ordens_catalogo()
        if sincronizar_completo:
            ordens = {identificador: indice for indice, identificador in enumerate(ids)}
        else:
            proxima_ordem = max(ordens_existentes.values(), default=-1) + 1
            ordens = {}
            for identificador in ids:
                if identificador in ordens_existentes:
                    ordens[identificador] = ordens_existentes[identificador]
                else:
                    ordens[identificador] = proxima_ordem
                    proxima_ordem += 1
        com_hash = [
            (
                candidato,
                hashlib.sha256(candidato.texto_embedding.encode("utf-8")).hexdigest(),
            )
            for candidato in candidatos
        ]
        pendentes = [(candidato, hash_atual) for candidato, hash_atual in com_hash if hashes_existentes.get(candidato.id) != hash_atual]
        if pendentes:
            vetores = self.embeddings.embed_documents([candidato.texto_embedding for candidato, _ in pendentes])
            self.armazenamento.salvar_candidatos(
                [candidato for candidato, _ in pendentes],
                [hash_atual for _, hash_atual in pendentes],
                vetores,
                ordens=[ordens[candidato.id] for candidato, _ in pendentes],
            )
        self.armazenamento.sincronizar_metadados_catalogo(candidatos, ordens)
        if sincronizar_completo:
            self.armazenamento.excluir_candidatos_ausentes(set(ids))
        return {
            "candidatos": len(candidatos),
            "embeddings_gerados": len(pendentes),
            "já_indexados": len(candidatos) - len(pendentes),
        }

    def buscar(self, relato: str, limite: int = LIMITE_CANDIDATOS, busca_hibrida: bool | None = None) -> dict[str, Any]:
        if not 1 <= limite <= LIMITE_CANDIDATOS:
            raise ValueError(f"O limite deve estar entre 1 e {LIMITE_CANDIDATOS}.")
        usar_hibrida = os.getenv("ORQUESTRADOR_BUSCA_HIBRIDA", "false") == "true" if busca_hibrida is None else busca_hibrida
        vetor_consulta = self.embeddings.embed_query(relato)
        semanticos = self.armazenamento.buscar_candidatos_por_vetor(vetor_consulta, limite)
        if not usar_hibrida:
            return {
                "estrategia": "semantica",
                "limite": limite,
                "resultados": [
                    {**candidato, "rank_semantico": posicao, "rank_lexical": None, "score_rrf": None}
                    for posicao, candidato in enumerate(semanticos, start=1)
                ],
            }

        lexicos = self.armazenamento.buscar_candidatos_por_texto(relato, limite)
        ranks_semanticos = {candidato["id"]: posicao for posicao, candidato in enumerate(semanticos, start=1)}
        ranks_lexicos = {candidato["id"]: posicao for posicao, candidato in enumerate(lexicos, start=1)}
        por_id = {candidato["id"]: candidato for candidato in semanticos}
        for candidato in lexicos:
            por_id.setdefault(candidato["id"], candidato)
        ordens = self.armazenamento.ordens_catalogo()
        candidatos_com_score = []
        for identificador, candidato in por_id.items():
            rank_semantico = ranks_semanticos.get(identificador)
            rank_lexical = ranks_lexicos.get(identificador)
            score = sum(1 / (K_RRF + rank) for rank in (rank_semantico, rank_lexical) if rank is not None)
            candidatos_com_score.append(
                {
                    **candidato,
                    "rank_semantico": rank_semantico,
                    "rank_lexical": rank_lexical,
                    "score_rrf": score,
                    "_ordem": ordens.get(identificador, 0),
                }
            )
        candidatos_com_score.sort(key=lambda item: (-item["score_rrf"], item["_ordem"]))
        return {
            "estrategia": "hibrida_rrf",
            "limite": limite,
            "k_rrf": K_RRF,
            "resultados": [{chave: valor for chave, valor in item.items() if chave != "_ordem"} for item in candidatos_com_score[:limite]],
        }

