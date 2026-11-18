"""Testes unitários para a funcionalidade de acompanhamento de progresso do ingest."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from rag.base import Documento
from rag.ingest import criar_formatador_terminal
from rag.ingest_documentos import carregar_documentos
from rag.progresso import ProgressoIngest, RastreadorProgresso
from rag.retriever import RecuperadorVerde


class TestProgressoIngest(unittest.TestCase):
    def test_progresso_ingest_to_dict_e_campos(self) -> None:
        p = ProgressoIngest(
            etapa="embeddings",
            mensagem="Gerando embeddings...",
            atual=10,
            total=20,
            porcentagem=50.0,
            arquivo_atual="manual.pdf",
            em_andamento=True,
        )
        dados = p.to_dict()
        self.assertEqual(dados["etapa"], "embeddings")
        self.assertEqual(dados["porcentagem"], 50.0)
        self.assertEqual(dados["atual"], 10)
        self.assertEqual(dados["total"], 20)
        self.assertEqual(dados["arquivo_atual"], "manual.pdf")
        self.assertTrue(dados["em_andamento"])

    def test_rastreador_ciclo_de_vida_completo(self) -> None:
        rastreador = RastreadorProgresso()
        status_inicial = rastreador.obter_status()
        self.assertFalse(status_inicial["em_andamento"])
        self.assertEqual(status_inicial["etapa"], "ocioso")

        rastreador.iniciar("Iniciando teste...")
        status = rastreador.obter_status()
        self.assertTrue(status["em_andamento"])
        self.assertEqual(status["etapa"], "iniciando")
        self.assertIsNotNone(status["iniciado_em"])

        rastreador.atualizar(
            etapa="embeddings",
            mensagem="Processando lote 1",
            atual=25,
            total=50,
            detalhes={"lote": 1},
        )
        status = rastreador.obter_status()
        self.assertEqual(status["etapa"], "embeddings")
        self.assertEqual(status["atual"], 25)
        self.assertEqual(status["total"], 50)
        self.assertEqual(status["porcentagem"], 50.0)
        self.assertEqual(status["detalhes"]["lote"], 1)

        rastreador.concluir(resumo={"documentos": 50, "embeddings_gerados": 50, "já_indexados": 0})
        status_fim = rastreador.obter_status()
        self.assertFalse(status_fim["em_andamento"])
        self.assertEqual(status_fim["etapa"], "concluido")
        self.assertEqual(status_fim["porcentagem"], 100.0)
        self.assertEqual(status_fim["resumo"]["documentos"], 50)

    def test_rastreador_falha(self) -> None:
        rastreador = RastreadorProgresso()
        rastreador.iniciar()
        rastreador.falhar("Erro de conexão com o banco")
        status = rastreador.obter_status()
        self.assertFalse(status["em_andamento"])
        self.assertEqual(status["etapa"], "erro")
        self.assertIn("Erro de conexão", status["erro"])

    def test_carregar_documentos_notifica_progresso(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            doc_json = {
                "openapi": "3.0.0",
                "info": {"title": "API Teste", "version": "1.0"},
                "paths": {
                    "/teste": {"get": {"summary": "Endpoint teste", "responses": {"200": {"description": "OK"}}}}
                },
            }
            (pasta / "swagger.json").write_text(json.dumps(doc_json), encoding="utf-8")

            eventos: list[ProgressoIngest] = []
            carregar_documentos(pasta, callback_progresso=eventos.append)

            etapas = [e.etapa for e in eventos]
            self.assertIn("descoberta", etapas)
            self.assertIn("carregamento", etapas)
            self.assertIn("fragmentacao", etapas)

    def test_recuperador_verde_indexar_com_lotes_e_progresso(self) -> None:
        mock_armazenamento = MagicMock()
        mock_armazenamento.hashes_existentes.return_value = {}
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.side_effect = lambda textos: [[0.1] * 1024 for _ in textos]

        docs_falsos = [
            Documento(id=f"doc-{i}", conteudo=f"Conteúdo do documento {i}", fonte="teste.json")
            for i in range(1, 6)
        ]

        recuperador = RecuperadorVerde(mock_armazenamento, mock_embeddings)
        eventos: list[ProgressoIngest] = []

        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            (pasta / "swagger.json").write_text(
                json.dumps({
                    "openapi": "3.0.0",
                    "info": {"title": "T", "version": "1"},
                    "paths": {"/t": {"get": {"responses": {"200": {"description": "ok"}}}}},
                }),
                encoding="utf-8",
            )

            # Mock carregar_documentos para retornar docs_falsos
            with unittest.mock.patch("rag.retriever.carregar_documentos", return_value=docs_falsos):
                resumo = recuperador.indexar(
                    pasta=pasta,
                    callback_progresso=eventos.append,
                    tamanho_lote=2,
                )

        self.assertEqual(resumo["documentos"], 5)
        self.assertEqual(resumo["embeddings_gerados"], 5)
        self.assertEqual(resumo["já_indexados"], 0)

        # Deve ter chamado embed_documents 3 vezes (2 + 2 + 1) devido ao tamanho_lote=2
        self.assertEqual(mock_embeddings.embed_documents.call_count, 3)

        etapas = [e.etapa for e in eventos]
        self.assertIn("carregando", etapas)
        self.assertIn("comparacao", etapas)
        self.assertIn("embeddings", etapas)
        self.assertIn("persistindo", etapas)
        self.assertIn("concluido", etapas)

    def test_formatador_terminal(self) -> None:
        buffer = io.StringIO()
        formatter = criar_formatador_terminal(stream=buffer, silencioso=False)

        formatter(ProgressoIngest(etapa="descoberta", mensagem="3 arquivos encontrados"))
        formatter(ProgressoIngest(etapa="carregamento", mensagem="Carregando doc.pdf", atual=1, total=3, arquivo_atual="doc.pdf"))
        formatter(
            ProgressoIngest(
                etapa="comparacao",
                mensagem="Verificando",
                detalhes={"total_documentos": 10, "ja_indexados": 5, "pendentes": 5},
            )
        )
        formatter(
            ProgressoIngest(
                etapa="embeddings",
                mensagem="Lote 1",
                atual=5,
                total=5,
                detalhes={"lote": 1, "total_lotes": 1},
            )
        )
        formatter(ProgressoIngest(etapa="persistindo", mensagem="Removendo obsoletos"))

        saida = buffer.getvalue()
        self.assertIn("Descoberta", saida)
        self.assertIn("doc.pdf", saida)
        self.assertIn("pgvector", saida)
        self.assertIn("Bedrock", saida)

    def test_api_status_indexacao_e_concorrencia(self) -> None:
        from fastapi.testclient import TestClient

        from rag.api import app, rastreador_ingest

        cliente = TestClient(app)

        # 1. Consulta status inicial
        resposta = cliente.get("/api/index/status")
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertIn("etapa", dados)
        self.assertIn("em_andamento", dados)

        # 2. Testa 409 quando ingestão já está em andamento
        rastreador_ingest.iniciar("Teste em andamento")
        try:
            resposta_concorrente = cliente.post("/api/index")
            self.assertEqual(resposta_concorrente.status_code, 409)
            self.assertIn("já está em andamento", resposta_concorrente.json()["detail"]["mensagem"])
        finally:
            rastreador_ingest.concluir(resumo={})


if __name__ == "__main__":
    unittest.main()
