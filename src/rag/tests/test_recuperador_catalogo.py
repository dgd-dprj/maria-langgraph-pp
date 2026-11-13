"""Testes unitários do ranking do catálogo, sem Bedrock ou Postgres reais."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import patch

from rag.catalogo import CandidatoCatalogo
from rag.recuperador_catalogo import RecuperadorCatalogo


class EmbeddingsFalsos:
    def __init__(self) -> None:
        self.documentos: list[str] = []

    def embed_documents(self, documentos: list[str]) -> list[list[float]]:
        self.documentos.extend(documentos)
        return [[0.1, 0.2] for _ in documentos]

    def embed_query(self, _: str) -> list[float]:
        return [0.3, 0.4]


class ArmazenamentoFalso:
    def __init__(self) -> None:
        self.hashes: dict[str, str] = {}
        self.vetoriais: list[dict[str, Any]] = []
        self.lexicais: list[dict[str, Any]] = []
        self.ordens: dict[str, int] = {}
        self.excluidos: set[str] | None = None
        self.ordens_atualizadas: dict[str, int] = {}

    def hashes_catalogo_existentes(self) -> dict[str, str]:
        return self.hashes

    def salvar_candidatos(self, candidatos: list[CandidatoCatalogo], hashes: list[str], _: Any, ordens: list[int]) -> None:
        for candidato, hash_atual in zip(candidatos, hashes, strict=True):
            self.hashes[candidato.id] = hash_atual
        self.ordens_atualizadas.update({candidato.id: ordem for candidato, ordem in zip(candidatos, ordens, strict=True)})

    def sincronizar_metadados_catalogo(self, _: list[CandidatoCatalogo], ordens: dict[str, int]) -> None:
        self.ordens_atualizadas = ordens

    def excluir_candidatos_ausentes(self, ids_validos: set[str]) -> None:
        self.excluidos = ids_validos

    def buscar_candidatos_por_vetor(self, _: list[float], limite: int) -> list[dict[str, Any]]:
        return self.vetoriais[:limite]

    def buscar_candidatos_por_texto(self, _: str, limite: int) -> list[dict[str, Any]]:
        return self.lexicais[:limite]

    def ordens_catalogo(self) -> dict[str, int]:
        return self.ordens


def _candidato(identificador: str) -> CandidatoCatalogo:
    return CandidatoCatalogo(identificador, identificador.title(), f"Descrição de {identificador}", (identificador,))


class TestRecuperadorCatalogo(unittest.TestCase):
    def setUp(self) -> None:
        self.armazenamento = ArmazenamentoFalso()
        self.embeddings = EmbeddingsFalsos()
        self.recuperador = RecuperadorCatalogo(self.armazenamento, self.embeddings)  # type: ignore[arg-type]

    def test_indexa_apenas_candidatos_novos_e_sincroniza_ordem(self) -> None:
        candidatos = [_candidato("bpc"), _candidato("rescisao")]
        resumo = self.recuperador.indexar(candidatos)
        self.assertEqual(resumo, {"candidatos": 2, "embeddings_gerados": 2, "já_indexados": 0})
        self.assertEqual(self.armazenamento.ordens_atualizadas, {"bpc": 0, "rescisao": 1})

        self.embeddings.documentos.clear()
        resumo = self.recuperador.indexar(candidatos)
        self.assertEqual(resumo["embeddings_gerados"], 0)
        self.assertEqual(self.embeddings.documentos, [])
        self.assertEqual(self.armazenamento.excluidos, {"bpc", "rescisao"})

    def test_atualizacao_parcial_preserva_ordem_dos_ids_existentes(self) -> None:
        self.recuperador.indexar([_candidato("bpc"), _candidato("rescisao")])
        self.armazenamento.ordens = {"bpc": 0, "rescisao": 1}

        self.recuperador.indexar([_candidato("rescisao"), _candidato("novo")], sincronizar_completo=False)

        self.assertEqual(self.armazenamento.ordens_atualizadas, {"rescisao": 1, "novo": 2})
        self.assertEqual(self.armazenamento.excluidos, {"bpc", "rescisao"})

    def test_busca_hibrida_usa_rrf_e_desempata_na_ordem_do_catalogo(self) -> None:
        self.armazenamento.vetoriais = [{"id": "bpc"}, {"id": "rescisao"}]
        self.armazenamento.lexicais = [{"id": "rescisao"}, {"id": "bpc"}]
        self.armazenamento.ordens = {"bpc": 0, "rescisao": 1}

        resultado = self.recuperador.buscar("Quero saber do BPC", busca_hibrida=True)

        self.assertEqual(resultado["estrategia"], "hibrida_rrf")
        self.assertEqual([item["id"] for item in resultado["resultados"]], ["bpc", "rescisao"])
        self.assertEqual(resultado["resultados"][0]["rank_semantico"], 1)
        self.assertEqual(resultado["resultados"][0]["rank_lexical"], 2)
        self.assertAlmostEqual(resultado["resultados"][0]["score_rrf"], 1 / 61 + 1 / 62)

    def test_interruptor_ambiente_so_ativa_com_string_true_exata(self) -> None:
        self.armazenamento.vetoriais = [{"id": "bpc"}]
        self.armazenamento.lexicais = [{"id": "bpc"}]
        with patch.dict(os.environ, {"ORQUESTRADOR_BUSCA_HIBRIDA": "True"}):
            resultado = self.recuperador.buscar("BPC")
        self.assertEqual(resultado["estrategia"], "semantica")

    def test_limite_nao_passa_de_quinze(self) -> None:
        with self.assertRaises(ValueError):
            self.recuperador.buscar("consulta", limite=16)


if __name__ == "__main__":
    unittest.main()
