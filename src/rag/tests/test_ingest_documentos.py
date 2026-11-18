"""Testes unitários de ingestão de documentos (OpenAPI, HTML, PDF, DOCX, Excel e imagens)."""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

from rag.ingest_documentos import (
    EXTENSOES_SUPORTADAS,
    carregar_documentos,
    documentos_de_docx,
    documentos_de_excel,
    documentos_de_imagem,
    documentos_de_pdf,
)


def _criar_docx_exemplo(caminho: Path, paragrafo: str, celulas: tuple[str, str]) -> None:
    xml_documento = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>{paragrafo}</w:t></w:r></w:p>
        <w:tbl>
          <w:tr>
            <w:tc><w:p><w:r><w:t>{celulas[0]}</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>{celulas[1]}</w:t></w:r></w:p></w:tc>
          </w:tr>
        </w:tbl>
      </w:body>
    </w:document>
    """
    with zipfile.ZipFile(caminho, "w") as pacote:
        pacote.writestr("word/document.xml", xml_documento)


def _criar_xlsx_exemplo(caminho: Path) -> None:
    workbook_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <sheets>
        <sheet name="Atendimentos" sheetId="1" r:id="rId1"/>
      </sheets>
    </workbook>
    """
    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
    </Relationships>
    """
    shared_strings_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <si><t>Código</t></si>
      <si><t>Orientação</t></si>
      <si><t>Prazo de contestação de 15 dias</t></si>
    </sst>
    """
    sheet1_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData>
        <row r="1">
          <c r="A1" t="s"><v>0</v></c>
          <c r="B1" t="s"><v>1</v></c>
        </row>
        <row r="2">
          <c r="A2" t="inlineStr"><is><t>ERR-404</t></is></c>
          <c r="B2" t="s"><v>2</v></c>
        </row>
      </sheetData>
    </worksheet>
    """
    with zipfile.ZipFile(caminho, "w") as pacote:
        pacote.writestr("xl/workbook.xml", workbook_xml)
        pacote.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        pacote.writestr("xl/sharedStrings.xml", shared_strings_xml)
        pacote.writestr("xl/worksheets/sheet1.xml", sheet1_xml)


def _criar_pdf_exemplo(caminho: Path, texto: str) -> None:
    fluxo_bt = f"BT /F1 12 Tf 72 720 Td ({texto}) Tj ET".encode("latin-1")
    comprimido = zlib.compress(fluxo_bt)
    conteudo_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Length "
        + str(len(comprimido)).encode("ascii")
        + b" /Filter /FlateDecode >>\nstream\n"
        + comprimido
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    caminho.write_bytes(conteudo_pdf)


def _criar_png_com_texto(caminho: Path, texto: str) -> None:
    assinatura = b"\x89PNG\r\n\x1a\n"
    dados_text = b"Description\x00" + texto.encode("latin-1")
    chunk_text = struct.pack(">I", len(dados_text)) + b"tEXt" + dados_text + b"\x00\x00\x00\x00"
    chunk_iend = struct.pack(">I", 0) + b"IEND\xaeB`\x82"
    caminho.write_bytes(assinatura + chunk_text + chunk_iend)


class TestIngestDocumentos(unittest.TestCase):
    def test_extensoes_suportadas_incluem_pdf_docx_excel_e_imagens(self) -> None:
        for ext in (".pdf", ".docx", ".xlsx", ".xls", ".csv", ".png", ".jpg", ".jpeg", ".webp"):
            self.assertIn(ext, EXTENSOES_SUPORTADAS)

    def test_documentos_de_docx_extrai_paragrafos_tabelas_e_omite_pii(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "Manual Atendimento.docx"
            _criar_docx_exemplo(
                arquivo,
                "Orientação sobre erro de cadastro para CPF 123.456.789-01.",
                ("Campo", "Obrigatório no Verde"),
            )
            docs = documentos_de_docx(arquivo)
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0].fonte, "Manual Atendimento.docx")
            self.assertIn("[CPF omitido]", docs[0].conteudo)
            self.assertNotIn("123.456.789-01", docs[0].conteudo)
            self.assertIn("Campo | Obrigatório no Verde", docs[0].conteudo)

    def test_documentos_de_excel_extrai_xlsx_e_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            arquivo_xlsx = Path(tmp) / "tabela_erros.xlsx"
            _criar_xlsx_exemplo(arquivo_xlsx)
            docs_xlsx = documentos_de_excel(arquivo_xlsx)
            self.assertEqual(len(docs_xlsx), 1)
            self.assertIn("Planilha: Atendimentos", docs_xlsx[0].conteudo)
            self.assertIn("Código: ERR-404 | Orientação: Prazo de contestação de 15 dias", docs_xlsx[0].conteudo)

            arquivo_csv = Path(tmp) / "contatos.csv"
            arquivo_csv.write_text("Setor;Responsavel\nTriagem;pessoa@defensoria.rj.def.br\n", encoding="utf-8")
            docs_csv = documentos_de_excel(arquivo_csv)
            self.assertEqual(len(docs_csv), 1)
            self.assertIn("Setor: Triagem | Responsavel: [e-mail omitido]", docs_csv[0].conteudo)

    def test_documentos_de_pdf_extrai_fluxo_comprimido(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            arquivo_pdf = Path(tmp) / "fluxo-agendamento.pdf"
            _criar_pdf_exemplo(arquivo_pdf, "Agendamento presencial na comarca do Rio de Janeiro")
            docs_pdf = documentos_de_pdf(arquivo_pdf)
            self.assertEqual(len(docs_pdf), 1)
            self.assertEqual(docs_pdf[0].fonte, "fluxo-agendamento.pdf")
            self.assertIn("Agendamento presencial na comarca do Rio de Janeiro", docs_pdf[0].conteudo)

    def test_documentos_de_imagem_usa_ocr_local_ou_metadados(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            arquivo_png = Path(tmp) / "captura_erro.png"
            _criar_png_com_texto(arquivo_png, "Mensagem de falha no envio de anexo")
            with patch("rag.ingest_documentos._extrair_texto_ocr_local", return_value="Erro 422: CPF invalido"):
                docs_img = documentos_de_imagem(arquivo_png)
            self.assertEqual(len(docs_img), 1)
            self.assertIn("Erro 422: CPF invalido", docs_img[0].conteudo)
            self.assertIn("Mensagem de falha no envio de anexo", docs_img[0].conteudo)

    def test_carregar_documentos_combina_swagger_e_novos_formatos_na_pasta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            swagger = {
                "openapi": "3.0.0",
                "info": {"title": "API Verde Teste", "version": "1.0"},
                "paths": {
                    "/integra/cep/{cep}": {
                        "get": {
                            "summary": "Consulta CEP",
                            "responses": {"200": {"description": "OK"}},
                        }
                    }
                },
            }
            (pasta / "swagger.json").write_text(json.dumps(swagger), encoding="utf-8")
            _criar_docx_exemplo(pasta / "guia.docx", "Texto do guia em Word", ("ColA", "ColB"))
            _criar_xlsx_exemplo(pasta / "planilha.xlsx")
            _criar_pdf_exemplo(pasta / "manual.pdf", "Conteudo do manual em PDF")
            _criar_png_com_texto(pasta / "tela.png", "Texto extraido da imagem PNG")

            with patch("rag.ingest_documentos._extrair_texto_ocr_local", return_value=""):
                fragmentos = carregar_documentos(pasta)

            fontes = {doc.fonte for doc in fragmentos}
            self.assertEqual(fontes, {"swagger.json", "guia.docx", "planilha.xlsx", "manual.pdf", "tela.png"})


if __name__ == "__main__":
    unittest.main()
