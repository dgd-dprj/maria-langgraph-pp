"""Persistência e busca vetorial em uma tabela própria do pgvector."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .base import Documento
from .catalogo import CandidatoCatalogo, normalizar_texto


class ArmazenamentoVetorial:
    """Implementa o ciclo de armazenamento e busca sem Prisma."""

    def __init__(self, database_url: str) -> None:
        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=4,
            kwargs={"row_factory": dict_row},
            open=False,
        )

    def abrir(self) -> None:
        self._pool.open(wait=True)
        with self._pool.connection() as conexao:
            conexao.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_documentos_swagger (
                    id TEXT PRIMARY KEY,
                    conteudo TEXT NOT NULL,
                    fonte TEXT NOT NULL,
                    endpoint TEXT NOT NULL DEFAULT '',
                    metodo TEXT NOT NULL DEFAULT '',
                    assunto TEXT NOT NULL DEFAULT '',
                    hash_conteudo TEXT NOT NULL,
                    embedding VECTOR(1024) NOT NULL,
                    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conexao.execute(
                "CREATE INDEX IF NOT EXISTS rag_documentos_swagger_embedding_idx "
                "ON rag_documentos_swagger USING hnsw (embedding vector_cosine_ops)"
            )
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_catalogo_orquestrador (
                    id TEXT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    descricao TEXT NOT NULL,
                    palavras_chave JSONB NOT NULL DEFAULT '[]'::jsonb,
                    dados JSONB NOT NULL DEFAULT '{}'::jsonb,
                    texto_busca TEXT NOT NULL,
                    hash_conteudo TEXT NOT NULL,
                    ordem INTEGER NOT NULL,
                    embedding VECTOR(1024) NOT NULL,
                    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conexao.execute(
                "CREATE INDEX IF NOT EXISTS rag_catalogo_orquestrador_lexical_idx "
                "ON rag_catalogo_orquestrador USING gin (to_tsvector('portuguese', texto_busca))"
            )

    def fechar(self) -> None:
        self._pool.close()

    def hashes_existentes(self) -> dict[str, str]:
        with self._pool.connection() as conexao:
            linhas = conexao.execute("SELECT id, hash_conteudo FROM rag_documentos_swagger").fetchall()
        return {
            str(cast(dict[str, Any], linha)["id"]): str(cast(dict[str, Any], linha)["hash_conteudo"])
            for linha in linhas
        }

    def salvar_documentos(
        self,
        documentos: Sequence[Documento],
        hashes: Sequence[str],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        if not (len(documentos) == len(hashes) == len(embeddings)):
            raise ValueError("Documentos, hashes e embeddings precisam ter o mesmo tamanho.")
        with self._pool.connection() as conexao, conexao.transaction():
            for documento, hash_conteudo, embedding in zip(documentos, hashes, embeddings, strict=True):
                vetor = "[" + ",".join(str(float(valor)) for valor in embedding) + "]"
                conexao.execute(
                    """
                    INSERT INTO rag_documentos_swagger
                        (id, conteudo, fonte, endpoint, metodo, assunto, hash_conteudo, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (id) DO UPDATE SET
                        conteudo = EXCLUDED.conteudo,
                        fonte = EXCLUDED.fonte,
                        endpoint = EXCLUDED.endpoint,
                        metodo = EXCLUDED.metodo,
                        assunto = EXCLUDED.assunto,
                        hash_conteudo = EXCLUDED.hash_conteudo,
                        embedding = EXCLUDED.embedding,
                        atualizado_em = now()
                    """,
                    (documento.id, documento.conteudo, documento.fonte, documento.endpoint, documento.metodo,
                     documento.assunto, hash_conteudo, vetor),
                )

    def excluir_ids_ausentes(self, ids_validos: set[str]) -> None:
        with self._pool.connection() as conexao, conexao.transaction():
            if ids_validos:
                conexao.execute("DELETE FROM rag_documentos_swagger WHERE NOT (id = ANY(%s))", (list(ids_validos),))
            else:
                conexao.execute("DELETE FROM rag_documentos_swagger")

    def buscar(self, embedding: Sequence[float], limite: int = 3) -> list[dict[str, Any]]:
        vetor = "[" + ",".join(str(float(valor)) for valor in embedding) + "]"
        with self._pool.connection() as conexao:
            linhas = conexao.execute(
                """
                SELECT id, conteudo, fonte, endpoint, metodo, assunto,
                       1 - (embedding <=> %s::vector) AS similaridade
                FROM rag_documentos_swagger
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vetor, vetor, limite),
            ).fetchall()
        return [dict(linha) for linha in linhas]

    def hashes_catalogo_existentes(self) -> dict[str, str]:
        with self._pool.connection() as conexao:
            linhas = conexao.execute("SELECT id, hash_conteudo FROM rag_catalogo_orquestrador").fetchall()
        return {
            str(cast(dict[str, Any], linha)["id"]): str(cast(dict[str, Any], linha)["hash_conteudo"])
            for linha in linhas
        }

    def salvar_candidatos(
        self,
        candidatos: Sequence[CandidatoCatalogo],
        hashes: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        ordens: Sequence[int],
    ) -> None:
        if not (len(candidatos) == len(hashes) == len(embeddings) == len(ordens)):
            raise ValueError("Candidatos, hashes, embeddings e ordens precisam ter o mesmo tamanho.")
        with self._pool.connection() as conexao, conexao.transaction():
            for candidato, hash_conteudo, embedding, ordem in zip(candidatos, hashes, embeddings, ordens, strict=True):
                vetor = "[" + ",".join(str(float(valor)) for valor in embedding) + "]"
                conexao.execute(
                    """
                    INSERT INTO rag_catalogo_orquestrador
                        (id, nome, descricao, palavras_chave, dados, texto_busca, hash_conteudo, ordem, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (id) DO UPDATE SET
                        nome = EXCLUDED.nome,
                        descricao = EXCLUDED.descricao,
                        palavras_chave = EXCLUDED.palavras_chave,
                        dados = EXCLUDED.dados,
                        texto_busca = EXCLUDED.texto_busca,
                        hash_conteudo = EXCLUDED.hash_conteudo,
                        ordem = EXCLUDED.ordem,
                        embedding = EXCLUDED.embedding,
                        atualizado_em = now()
                    """,
                    (
                        candidato.id,
                        candidato.nome,
                        candidato.descricao,
                        Jsonb(list(candidato.palavras_chave)),
                        Jsonb(candidato.dados or {}),
                        normalizar_texto(" ".join((candidato.nome, candidato.descricao, *candidato.palavras_chave))),
                        hash_conteudo,
                        ordem,
                        vetor,
                    ),
                )

    def excluir_candidatos_ausentes(self, ids_validos: set[str]) -> None:
        with self._pool.connection() as conexao, conexao.transaction():
            if ids_validos:
                conexao.execute("DELETE FROM rag_catalogo_orquestrador WHERE NOT (id = ANY(%s))", (list(ids_validos),))
            else:
                conexao.execute("DELETE FROM rag_catalogo_orquestrador")

    def ordens_catalogo(self) -> dict[str, int]:
        with self._pool.connection() as conexao:
            linhas = conexao.execute("SELECT id, ordem FROM rag_catalogo_orquestrador").fetchall()
        return {
            str(cast(dict[str, Any], linha)["id"]): int(cast(dict[str, Any], linha)["ordem"])
            for linha in linhas
        }

    def sincronizar_metadados_catalogo(self, candidatos: Sequence[CandidatoCatalogo], ordens: dict[str, int]) -> None:
        with self._pool.connection() as conexao, conexao.transaction():
            for candidato in candidatos:
                conexao.execute(
                    """
                    UPDATE rag_catalogo_orquestrador SET
                        nome = %s,
                        descricao = %s,
                        palavras_chave = %s,
                        dados = %s,
                        texto_busca = %s,
                        ordem = %s
                    WHERE id = %s
                    """,
                    (
                        candidato.nome,
                        candidato.descricao,
                        Jsonb(list(candidato.palavras_chave)),
                        Jsonb(candidato.dados or {}),
                        normalizar_texto(" ".join((candidato.nome, candidato.descricao, *candidato.palavras_chave))),
                        ordens[candidato.id],
                        candidato.id,
                    ),
                )

    def buscar_candidatos_por_vetor(self, embedding: Sequence[float], limite: int) -> list[dict[str, Any]]:
        vetor = "[" + ",".join(str(float(valor)) for valor in embedding) + "]"
        with self._pool.connection() as conexao:
            linhas = conexao.execute(
                """
                SELECT id, nome, descricao, palavras_chave, dados,
                       1 - (embedding <=> %s::vector) AS similaridade
                FROM rag_catalogo_orquestrador
                ORDER BY embedding <=> %s::vector, ordem
                LIMIT %s
                """,
                (vetor, vetor, limite),
            ).fetchall()
        return [dict(linha) for linha in linhas]

    def buscar_candidatos_por_texto(self, consulta: str, limite: int) -> list[dict[str, Any]]:
        consulta_normalizada = normalizar_texto(consulta)
        if not consulta_normalizada:
            return []
        # OR mantém recall lexical em relatos longos: um termo exato como
        # "LOAS" ou "rescisão" ainda pode recuperar o candidato pertinente.
        consulta_ou = " | ".join(consulta_normalizada.split())
        with self._pool.connection() as conexao:
            linhas = conexao.execute(
                """
                WITH busca AS (
                    SELECT to_tsquery('portuguese', %s) AS termos
                )
                SELECT candidato.id, candidato.nome, candidato.descricao,
                       candidato.palavras_chave, candidato.dados,
                       ts_rank_cd(to_tsvector('portuguese', candidato.texto_busca), busca.termos) AS relevancia
                FROM rag_catalogo_orquestrador AS candidato
                CROSS JOIN busca
                WHERE to_tsvector('portuguese', candidato.texto_busca) @@ busca.termos
                ORDER BY relevancia DESC, candidato.ordem
                LIMIT %s
                """,
                (consulta_ou, limite),
            ).fetchall()
        return [dict(linha) for linha in linhas]

    def contar(self) -> int:
        with self._pool.connection() as conexao:
            linha = conexao.execute("SELECT count(*) AS total FROM rag_documentos_swagger").fetchone()
        if linha is None:
            return 0
        return int(cast(dict[str, Any], linha)["total"])

    def contar_candidatos(self) -> int:
        with self._pool.connection() as conexao:
            linha = conexao.execute("SELECT count(*) AS total FROM rag_catalogo_orquestrador").fetchone()
        if linha is None:
            return 0
        return int(cast(dict[str, Any], linha)["total"])
