"""Converte especificações OpenAPI/Swagger, HTML, PDF, DOCX, Excel e imagens em documentos RAG.

Prefere o JSON da especificação para contratos da API, com fallback para a captura
HTML, além de indexar arquivos complementares (.pdf, .docx, .xlsx, .xls, .csv e
imagens) presentes na pasta de documentos.
"""

from __future__ import annotations

import csv
import importlib
import json
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .base import Documento
from .progresso import CallbackProgresso, ProgressoIngest

_METODOS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})
_PASTA_DOCUMENTOS = Path(__file__).resolve().parents[2] / "documentos"
_TAMANHO_FRAGMENTO = 1_200
_SOBREPOSICAO_FRAGMENTO = 160
_CPF = re.compile(r"(?<!\d)(?:\d{3}[. ]?){3}-?\d{2}(?!\d)")
_PROCESSO_CNJ = re.compile(r"(?<!\d)\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?!\d)")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_TELEFONE_BR = re.compile(r"(?<!\d)(?:\+?55[ -]?)?\(?\d{2}\)?[ -]?9?\d{4}[ -]?\d{4}(?!\d)")

EXTENSOES_IMAGEM = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"})
EXTENSOES_EXCEL = frozenset({".xlsx", ".xls", ".csv"})
EXTENSOES_PDF = frozenset({".pdf"})
EXTENSOES_DOCX = frozenset({".docx"})
EXTENSOES_SWAGGER = frozenset({".json", ".html", ".htm"})
EXTENSOES_SUPORTADAS = EXTENSOES_SWAGGER | EXTENSOES_PDF | EXTENSOES_DOCX | EXTENSOES_EXCEL | EXTENSOES_IMAGEM


def _sanitizar_texto(conteudo: str) -> str:
    conteudo = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", conteudo)
    conteudo = _EMAIL.sub("[e-mail omitido]", conteudo)
    conteudo = _CPF.sub("[CPF omitido]", conteudo)
    conteudo = _PROCESSO_CNJ.sub("[número de processo omitido]", conteudo)
    return _TELEFONE_BR.sub("[telefone omitido]", conteudo)


def _slug(valor: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", valor).strip("-").lower() or "documento"


def _tag_local(elemento: ET.Element) -> str:
    return elemento.tag.rsplit("}", 1)[-1]


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, str | int | float | bool):
        return str(valor)
    if isinstance(valor, list):
        return "; ".join(parte for item in valor if (parte := _texto(item)))
    if isinstance(valor, dict):
        return json.dumps(valor, ensure_ascii=False, sort_keys=True)
    return ""


def _resolver_referencia(esquema: Any, definicoes: dict[str, Any], vistos: frozenset[str] = frozenset(), nivel: int = 0) -> Any:
    if nivel >= 4 or not isinstance(esquema, dict):
        return esquema
    referencia = esquema.get("$ref")
    if isinstance(referencia, str) and referencia.startswith("#/components/schemas/"):
        chave = referencia.removeprefix("#/components/schemas/")
        if chave not in vistos and chave in definicoes:
            return _resolver_referencia(definicoes[chave], definicoes, vistos | {chave}, nivel + 1)
    if isinstance(referencia, str) and referencia.startswith("#/definitions/"):
        chave = referencia.removeprefix("#/definitions/")
        if chave not in vistos and chave in definicoes:
            return _resolver_referencia(definicoes[chave], definicoes, vistos | {chave}, nivel + 1)

    resultado = dict(esquema)
    propriedades = resultado.get("properties")
    if isinstance(propriedades, dict):
        resultado["properties"] = {
            nome: _resolver_referencia(definicao, definicoes, vistos, nivel + 1) for nome, definicao in propriedades.items()
        }
    itens = resultado.get("items")
    if isinstance(itens, dict):
        resultado["items"] = _resolver_referencia(itens, definicoes, vistos, nivel + 1)
    return resultado


def _resumo_esquema(esquema: Any) -> str:
    if not isinstance(esquema, dict):
        return _texto(esquema)
    tipo = _texto(esquema.get("type")) or ("objeto" if "properties" in esquema else "")
    descricao = _texto(esquema.get("description"))
    linhas = [f"tipo: {tipo}" if tipo else ""]
    if descricao:
        linhas.append(f"descrição: {descricao}")
    formato = _texto(esquema.get("format"))
    if formato:
        linhas.append(f"formato: {formato}")
    valores = esquema.get("enum")
    if isinstance(valores, list) and valores:
        linhas.append("valores permitidos: " + ", ".join(_texto(valor) for valor in valores))
    obrigatorios = esquema.get("required", [])
    if isinstance(obrigatorios, list) and obrigatorios:
        linhas.append("campos obrigatórios: " + ", ".join(_texto(campo) for campo in obrigatorios))
    propriedades = esquema.get("properties")
    if isinstance(propriedades, dict):
        for nome, propriedade in propriedades.items():
            if not isinstance(propriedade, dict):
                linhas.append(f"- {nome}: {_texto(propriedade)}")
                continue
            tipo_campo = _texto(propriedade.get("type"))
            if not tipo_campo and "properties" in propriedade:
                tipo_campo = "objeto"
            detalhe = _texto(propriedade.get("description"))
            valor = f"- {nome} ({tipo_campo})" if tipo_campo else f"- {nome}"
            formato_campo = _texto(propriedade.get("format"))
            enum_campo = propriedade.get("enum")
            if formato_campo:
                valor = f"{valor}, formato {formato_campo}"
            if isinstance(enum_campo, list) and enum_campo:
                valores_enum = ", ".join(_texto(item) for item in enum_campo)
                valor = f"{valor}, valores permitidos: {valores_enum}"
            linhas.append(f"{valor}: {detalhe}" if detalhe else valor)
    return "\n".join(linha for linha in linhas if linha)


def _esquema_de_corpo(corpo: Any, definicoes: dict[str, Any]) -> list[str]:
    if not isinstance(corpo, dict):
        return []
    linhas: list[str] = []
    # Swagger 2.0 mantém body em parâmetro; OpenAPI 3 usa requestBody.content.
    esquema = corpo.get("schema")
    if esquema is not None:
        linhas.append(_resumo_esquema(_resolver_referencia(esquema, definicoes)))
    conteudo = corpo.get("content")
    if isinstance(conteudo, dict):
        for tipo_midia, definicao in conteudo.items():
            if not isinstance(definicao, dict):
                continue
            esquema_midia = definicao.get("schema")
            if esquema_midia is not None:
                linhas.append(f"{tipo_midia}:\n{_resumo_esquema(_resolver_referencia(esquema_midia, definicoes))}")
            # Exemplos de payload podem conter dados pessoais; indexamos schema,
            # descrições e status, mas não valores de exemplo.
    return linhas


def _documento_operacao(caminho: str, metodo: str, operacao: dict[str, Any], definicoes: dict[str, Any]) -> Documento:
    tags = operacao.get("tags", [])
    assunto = ", ".join(_texto(tag) for tag in tags) if isinstance(tags, list) else _texto(tags)
    operacao_id = _texto(operacao.get("operationId"))
    resumo = _texto(operacao.get("summary"))
    descricao = _texto(operacao.get("description"))
    linhas = [f"Endpoint: {metodo.upper()} {caminho}"]
    if assunto:
        linhas.append(f"Grupo: {assunto}")
    if operacao_id:
        linhas.append(f"Operação: {operacao_id}")
    if resumo:
        linhas.append(f"Resumo: {resumo}")
    if descricao:
        linhas.append(f"Descrição: {descricao}")

    parametros = operacao.get("parameters", [])
    if isinstance(parametros, list):
        for parametro in parametros:
            if not isinstance(parametro, dict):
                continue
            nome = _texto(parametro.get("name"))
            local = _texto(parametro.get("in"))
            descricao_parametro = _texto(parametro.get("description"))
            if local == "body":
                linhas.extend(f"Corpo da requisição:\n{linha}" for linha in _esquema_de_corpo(parametro, definicoes))
                continue
            esquema_parametro = _resolver_referencia(parametro.get("schema", parametro), definicoes)
            detalhe = _resumo_esquema(esquema_parametro)
            linhas.append(f"Parâmetro {nome} ({local}): {descricao_parametro or detalhe or 'sem descrição no Swagger'}")

    corpo = operacao.get("requestBody")
    linhas.extend(f"Corpo da requisição:\n{linha}" for linha in _esquema_de_corpo(corpo, definicoes))

    respostas = operacao.get("responses", {})
    if isinstance(respostas, dict):
        for status, resposta in respostas.items():
            if not isinstance(resposta, dict):
                continue
            linhas.append(f"Resposta HTTP {status}: {_texto(resposta.get('description'))}")
            linhas.extend(f"Contrato da resposta:\n{linha}" for linha in _esquema_de_corpo(resposta, definicoes))

    conteudo = _sanitizar_texto("\n".join(linha for linha in linhas if linha))
    identificador = _slug(f"{metodo}-{caminho}")
    return Documento(
        id=identificador,
        conteudo=conteudo,
        fonte="Swagger Verde",
        endpoint=caminho,
        metodo=metodo.upper(),
        assunto=assunto or resumo or operacao_id,
    )


def documentos_de_openapi(especificacao: dict[str, Any], fonte: str = "Swagger Verde") -> list[Documento]:
    """Transforma cada operação da especificação em um documento recuperável."""
    caminhos = especificacao.get("paths")
    if not isinstance(caminhos, dict):
        raise ValueError("A especificação Swagger/OpenAPI não contém 'paths'.")
    componentes = especificacao.get("components", {})
    definicoes = componentes.get("schemas", {}) if isinstance(componentes, dict) else {}
    if not isinstance(definicoes, dict):
        definicoes = {}
    if not definicoes and isinstance(especificacao.get("definitions"), dict):
        definicoes = especificacao["definitions"]

    documentos: list[Documento] = []
    informacoes = especificacao.get("info")
    if isinstance(informacoes, dict):
        titulo = _texto(informacoes.get("title"))
        versao = _texto(informacoes.get("version"))
        descricao = _texto(informacoes.get("description"))
        linhas_info = [parte for parte in (f"API: {titulo}" if titulo else "", f"Versão: {versao}" if versao else "", descricao) if parte]
        if linhas_info:
            documentos.append(
                Documento(
                    id="swagger-informacoes-gerais",
                    conteudo=_sanitizar_texto("\n".join(linhas_info)),
                    fonte=fonte,
                    assunto=titulo or "Informações gerais da API",
                )
            )

    tags = especificacao.get("tags", [])
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            nome = _texto(tag.get("name"))
            descricao = _texto(tag.get("description"))
            if nome and descricao:
                documentos.append(
                    Documento(
                        id=f"swagger-grupo-{_slug(nome)}",
                        conteudo=_sanitizar_texto(f"Grupo da API: {nome}\nDescrição: {descricao}"),
                        fonte=fonte,
                        assunto=nome,
                    )
                )

    for caminho, item in caminhos.items():
        if not isinstance(item, dict):
            continue
        for metodo, operacao in item.items():
            if metodo.lower() not in _METODOS or not isinstance(operacao, dict):
                continue
            combinado = dict(operacao)
            herdados = item.get("parameters", [])
            proprios = operacao.get("parameters", [])
            if isinstance(herdados, list) and isinstance(proprios, list):
                combinado["parameters"] = [*herdados, *proprios]
            documento = _documento_operacao(_texto(caminho), metodo, combinado, definicoes)
            documentos.append(
                Documento(
                    id=documento.id,
                    conteudo=documento.conteudo,
                    fonte=fonte,
                    endpoint=documento.endpoint,
                    metodo=documento.metodo,
                    assunto=documento.assunto,
                )
            )
    return documentos


class _LeitorSwaggerHTML(HTMLParser):
    def __init__(self, fonte: str) -> None:
        super().__init__(convert_charrefs=True)
        self.fonte = fonte
        self.documentos: list[Documento] = []
        self.atual: dict[str, str] | None = None
        self.profundidade_div = 0
        self.captura: str | None = None
        self.buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        atributos = {nome: valor or "" for nome, valor in attrs}
        classes = atributos.get("class", "").split()
        if tag == "div" and "opblock" in classes and any(classe.startswith("opblock-") for classe in classes):
            self.atual = {"metodo": next(classe.removeprefix("opblock-") for classe in classes if classe.startswith("opblock-")).upper()}
            self.profundidade_div = 1
            return
        if self.atual is None:
            return
        if tag == "div":
            self.profundidade_div += 1
        if tag == "span" and "data-path" in atributos:
            self.atual["endpoint"] = atributos["data-path"]
        if tag == "span" and "opblock-summary-method" in classes:
            self.captura = "metodo"
            self.buffer = []
        elif tag == "div" and "opblock-summary-description" in classes:
            self.captura = "resumo"
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.captura is not None:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.atual is None:
            return
        if self.captura is not None and ((self.captura == "metodo" and tag == "span") or (self.captura == "resumo" and tag == "div")):
            valor = " ".join(" ".join(self.buffer).split())
            self.atual[self.captura] = valor
            self.captura = None
            self.buffer = []
        if tag == "div":
            self.profundidade_div -= 1
            if self.profundidade_div == 0:
                self._finalizar()

    def _finalizar(self) -> None:
        atual = self.atual
        self.atual = None
        if atual is None or not atual.get("endpoint"):
            return
        metodo = atual.get("metodo", "GET")
        resumo = atual.get("resumo", "")
        conteudo = _sanitizar_texto(f"Endpoint: {metodo} {atual['endpoint']}\nResumo: {resumo}".strip())
        identificador = _slug(f"{metodo}-{atual['endpoint']}")
        self.documentos.append(
            Documento(
                id=identificador,
                conteudo=conteudo,
                fonte=self.fonte,
                endpoint=atual["endpoint"],
                metodo=metodo,
                assunto=resumo,
            )
        )


def documentos_de_html(caminho: str | Path) -> list[Documento]:
    arquivo = Path(caminho)
    leitor = _LeitorSwaggerHTML(arquivo.name)
    leitor.feed(arquivo.read_text(encoding="utf-8"))
    if not leitor.documentos:
        raise ValueError(f"Não encontrei operações Swagger na captura HTML: {arquivo}")
    return leitor.documentos


def _texto_paragrafo_docx(elemento_p: ET.Element) -> str:
    partes: list[str] = []
    for sub in elemento_p.iter():
        tag = _tag_local(sub)
        if tag == "t" and sub.text:
            partes.append(sub.text)
        elif tag in ("br", "cr"):
            partes.append("\n")
        elif tag == "tab":
            partes.append("\t")
    return "".join(partes).strip()


def _extrair_xml_docx(raiz: ET.Element) -> list[str]:
    linhas: list[str] = []
    corpo = next((filho for filho in raiz.iter() if _tag_local(filho) == "body"), raiz)
    for item in corpo:
        tag = _tag_local(item)
        if tag == "p":
            texto = _texto_paragrafo_docx(item)
            if texto:
                linhas.append(texto)
        elif tag == "tbl":
            for linha_tbl in item:
                if _tag_local(linha_tbl) != "tr":
                    continue
                celulas: list[str] = []
                for celula in linha_tbl:
                    if _tag_local(celula) != "tc":
                        continue
                    textos_celula = [texto_p for p in celula.iter() if _tag_local(p) == "p" and (texto_p := _texto_paragrafo_docx(p))]
                    celulas.append(" ".join(textos_celula))
                if any(celulas):
                    linhas.append(" | ".join(celulas))
    return linhas


def documentos_de_docx(caminho: str | Path) -> list[Documento]:
    """Extrai parágrafos e tabelas de arquivos Word (.docx)."""
    arquivo = Path(caminho)
    linhas: list[str] = []

    if zipfile.is_zipfile(arquivo):
        with zipfile.ZipFile(arquivo) as pacote:
            nomes = pacote.namelist()
            alvos = [
                *[nome for nome in sorted(nomes) if re.match(r"word/header\d*\.xml$", nome)],
                *(["word/document.xml"] if "word/document.xml" in nomes else []),
                *[nome for nome in sorted(nomes) if re.match(r"word/footer\d*\.xml$", nome)],
            ]
            for alvo in alvos:
                raiz = ET.fromstring(pacote.read(alvo))
                linhas.extend(_extrair_xml_docx(raiz))
    else:
        try:
            modulo_docx = importlib.import_module("docx")
            doc = modulo_docx.Document(str(arquivo))
            linhas.extend(p.text.strip() for p in doc.paragraphs if p.text and p.text.strip())
            for tabela in doc.tables:
                for linha in tabela.rows:
                    valores = [celula.text.strip() for celula in linha.cells]
                    if any(valores):
                        linhas.append(" | ".join(valores))
        except Exception as erro:
            raise ValueError(f"Arquivo DOCX inválido ou corrompido: {arquivo}") from erro

    conteudo = _sanitizar_texto("\n".join(linha for linha in linhas if linha).strip())
    if not conteudo:
        raise ValueError(f"Não encontrei texto no arquivo DOCX: {arquivo}")

    return [
        Documento(
            id=_slug(arquivo.name),
            conteudo=conteudo,
            fonte=arquivo.name,
            assunto=arquivo.stem,
        )
    ]


def _indice_coluna_excel(referencia_celula: str) -> int:
    letras = "".join(caractere for caractere in referencia_celula if caractere.isalpha()).upper()
    indice = 0
    for letra in letras:
        indice = indice * 26 + (ord(letra) - ord("A") + 1)
    return max(indice - 1, 0)


def _formatar_linhas_planilha(nome_aba: str, linhas: list[list[str]]) -> str:
    linhas_limpas = [[celula.strip() for celula in linha] for linha in linhas if any(celula.strip() for celula in linha)]
    if not linhas_limpas:
        return ""
    saida = [f"Planilha: {nome_aba}"]
    if len(linhas_limpas) == 1:
        saida.append(" | ".join(valor for valor in linhas_limpas[0] if valor))
        return "\n".join(saida)

    cabecalho = linhas_limpas[0]
    usar_cabecalho = any(cabecalho) and all(len(col) <= 80 for col in cabecalho if col)
    if usar_cabecalho:
        saida.append("Colunas: " + " | ".join(col for col in cabecalho if col))
        for linha in linhas_limpas[1:]:
            pares: list[str] = []
            for idx, valor in enumerate(linha):
                if not valor:
                    continue
                nome_col = cabecalho[idx] if idx < len(cabecalho) and cabecalho[idx] else f"Coluna {idx + 1}"
                pares.append(f"{nome_col}: {valor}")
            if pares:
                saida.append(" | ".join(pares))
    else:
        for linha in linhas_limpas:
            saida.append(" | ".join(valor for valor in linha if valor))
    return "\n".join(saida)


def _ler_xlsx_xml(arquivo: Path) -> list[tuple[str, list[list[str]]]]:
    with zipfile.ZipFile(arquivo) as pacote:
        nomes = set(pacote.namelist())
        strings_compartilhadas: list[str] = []
        if "xl/sharedStrings.xml" in nomes:
            raiz_sst = ET.fromstring(pacote.read("xl/sharedStrings.xml"))
            for item_si in raiz_sst:
                if _tag_local(item_si) == "si":
                    textos = [no.text or "" for no in item_si.iter() if _tag_local(no) == "t"]
                    strings_compartilhadas.append("".join(textos))

        relacoes: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in nomes:
            raiz_rels = ET.fromstring(pacote.read("xl/_rels/workbook.xml.rels"))
            for rel in raiz_rels:
                if _tag_local(rel) == "Relationship":
                    rel_id = rel.attrib.get("Id", "")
                    alvo = rel.attrib.get("Target", "").lstrip("/")
                    if alvo and not alvo.startswith("xl/"):
                        alvo = f"xl/{alvo}"
                    if rel_id and alvo:
                        relacoes[rel_id] = alvo

        abas: list[tuple[str, str]] = []
        if "xl/workbook.xml" in nomes:
            raiz_wb = ET.fromstring(pacote.read("xl/workbook.xml"))
            for idx, elemento in enumerate(raiz_wb.iter(), start=1):
                if _tag_local(elemento) == "sheet":
                    nome_aba = elemento.attrib.get("name", f"Aba {idx}")
                    rel_id = next((val for chave, val in elemento.attrib.items() if chave.endswith("id") and chave != "sheetId"), "")
                    caminho_xml = relacoes.get(rel_id, f"xl/worksheets/sheet{len(abas) + 1}.xml")
                    if caminho_xml in nomes:
                        abas.append((nome_aba, caminho_xml))

        if not abas:
            for idx, caminho_xml in enumerate(sorted(n for n in nomes if re.match(r"xl/worksheets/sheet\d+\.xml$", n)), start=1):
                abas.append((f"Aba {idx}", caminho_xml))

        resultado: list[tuple[str, list[list[str]]]] = []
        for nome_aba, caminho_xml in abas:
            raiz_ws = ET.fromstring(pacote.read(caminho_xml))
            linhas_aba: list[list[str]] = []
            for elemento_linha in raiz_ws.iter():
                if _tag_local(elemento_linha) != "row":
                    continue
                celulas_dict: dict[int, str] = {}
                proximo_indice = 0
                for celula in elemento_linha:
                    if _tag_local(celula) != "c":
                        continue
                    ref = celula.attrib.get("r", "")
                    indice_col = _indice_coluna_excel(ref) if ref else proximo_indice
                    proximo_indice = indice_col + 1
                    tipo_celula = celula.attrib.get("t", "")
                    valor_texto = ""
                    if tipo_celula == "inlineStr":
                        valor_texto = "".join(no.text or "" for no in celula.iter() if _tag_local(no) == "t")
                    else:
                        no_valor = next((filho for filho in celula if _tag_local(filho) == "v"), None)
                        bruto = (no_valor.text or "") if no_valor is not None else ""
                        if tipo_celula == "s" and bruto.isdigit():
                            idx_str = int(bruto)
                            if 0 <= idx_str < len(strings_compartilhadas):
                                valor_texto = strings_compartilhadas[idx_str]
                        elif tipo_celula == "b":
                            valor_texto = "Sim" if bruto == "1" else "Não"
                        else:
                            valor_texto = bruto
                    celulas_dict[indice_col] = valor_texto
                if celulas_dict:
                    max_col = max(celulas_dict)
                    linhas_aba.append([celulas_dict.get(i, "") for i in range(max_col + 1)])
            resultado.append((nome_aba, linhas_aba))
        return resultado


def documentos_de_excel(caminho: str | Path) -> list[Documento]:
    """Extrai dados tabulares de arquivos Excel (.xlsx, .xls) e CSV (.csv)."""
    arquivo = Path(caminho)
    extensao = arquivo.suffix.lower()
    abas: list[tuple[str, list[list[str]]]] = []

    if extensao == ".csv":
        texto_csv = arquivo.read_text(encoding="utf-8-sig", errors="replace")
        try:
            dialeto = csv.Sniffer().sniff(texto_csv[:2048], delimiters=",;\t")
            leitor = csv.reader(texto_csv.splitlines(), dialect=dialeto)
        except csv.Error:
            leitor = csv.reader(texto_csv.splitlines())
        abas.append((arquivo.stem, [list(linha) for linha in leitor]))
    elif extensao == ".xlsx":
        if zipfile.is_zipfile(arquivo):
            abas = _ler_xlsx_xml(arquivo)
        else:
            try:
                openpyxl = importlib.import_module("openpyxl")
                planilha = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
                for nome_aba in planilha.sheetnames:
                    ws = planilha[nome_aba]
                    linhas_ws = [[_texto(valor) for valor in linha] for linha in ws.iter_rows(values_only=True)]
                    abas.append((str(nome_aba), linhas_ws))
            except Exception as erro:
                raise ValueError(f"Arquivo XLSX inválido ou corrompido: {arquivo}") from erro
    elif extensao == ".xls":
        try:
            xlrd = importlib.import_module("xlrd")
            livro = xlrd.open_workbook(str(arquivo))
            for aba in livro.sheets():
                linhas_xls = [[_texto(aba.cell_value(r, c)) for c in range(aba.ncols)] for r in range(aba.nrows)]
                abas.append((str(aba.name), linhas_xls))
        except ModuleNotFoundError as erro:
            raise ValueError(f"Para ler arquivos .xls legados ({arquivo.name}), converta para .xlsx ou instale 'xlrd'.") from erro
    else:
        raise ValueError(f"Extensão de planilha não suportada: {arquivo}")

    documentos: list[Documento] = []
    for nome_aba, linhas in abas:
        formatado = _sanitizar_texto(_formatar_linhas_planilha(nome_aba, linhas).strip())
        if not formatado:
            continue
        id_doc = _slug(f"{arquivo.name}-{nome_aba}") if len(abas) > 1 else _slug(arquivo.name)
        documentos.append(
            Documento(
                id=id_doc,
                conteudo=formatado,
                fonte=arquivo.name,
                assunto=f"{arquivo.stem} - {nome_aba}" if len(abas) > 1 else arquivo.stem,
            )
        )

    if not documentos:
        raise ValueError(f"Não encontrei dados preenchidos na planilha: {arquivo}")
    return documentos


def _decodificar_literal_pdf(texto_bytes: bytes, cmap: dict[int, str] | None = None) -> str:
    saida = bytearray()
    i = 0
    tamanho = len(texto_bytes)
    while i < tamanho:
        atual = texto_bytes[i]
        if atual == 0x5C and i + 1 < tamanho:  # '\'
            proximo = texto_bytes[i + 1]
            if proximo == ord("n"):
                saida.append(ord("\n"))
                i += 2
            elif proximo == ord("r"):
                saida.append(ord("\r"))
                i += 2
            elif proximo == ord("t"):
                saida.append(ord("\t"))
                i += 2
            elif proximo in (ord("b"), ord("f")):
                i += 2
            elif proximo in (ord("("), ord(")"), ord("\\")):
                saida.append(proximo)
                i += 2
            elif proximo in (ord("\r"), ord("\n")):
                i += 2
                if proximo == ord("\r") and i < tamanho and texto_bytes[i] == ord("\n"):
                    i += 1
            elif ord("0") <= proximo <= ord("7"):
                octal = bytes([proximo])
                i += 2
                for _ in range(2):
                    if i < tamanho and ord("0") <= texto_bytes[i] <= ord("7"):
                        octal += bytes([texto_bytes[i]])
                        i += 1
                    else:
                        break
                saida.append(int(octal, 8) & 0xFF)
            else:
                saida.append(proximo)
                i += 2
        else:
            saida.append(atual)
            i += 1

    bruto = bytes(saida)
    if bruto.startswith(b"\xfe\xff"):
        return bruto[2:].decode("utf-16-be", errors="ignore")
    if bruto.startswith(b"\xff\xfe"):
        return bruto[2:].decode("utf-16-le", errors="ignore")
    if cmap and len(bruto) >= 2 and len(bruto) % 2 == 0:
        codigos_2b = [int.from_bytes(bruto[idx : idx + 2], "big") for idx in range(0, len(bruto), 2)]
        acertos = sum(1 for codigo in codigos_2b if codigo in cmap)
        if acertos >= max(1, len(codigos_2b) // 2):
            return "".join(cmap.get(codigo, "") for codigo in codigos_2b)
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return bruto.decode("latin-1", errors="ignore")


def _decodificar_hex_pdf(hex_str: str, cmap: dict[int, str]) -> str:
    limpo = re.sub(r"\s+", "", hex_str)
    if len(limpo) % 2 == 1:
        limpo += "0"
    try:
        dados = bytes.fromhex(limpo)
    except ValueError:
        return ""
    if dados.startswith(b"\xfe\xff"):
        return dados[2:].decode("utf-16-be", errors="ignore")
    if cmap:
        passo = 2 if len(dados) % 2 == 0 and any(chave > 0xFF for chave in cmap) else 1
        caracteres: list[str] = []
        for idx in range(0, len(dados), passo):
            codigo = int.from_bytes(dados[idx : idx + passo], "big")
            caracteres.append(cmap.get(codigo, chr(codigo) if 32 <= codigo <= 0x10FFFF else ""))
        return "".join(caracteres)
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("latin-1", errors="ignore")


def _extrair_cmap_pdf(streams: list[bytes]) -> dict[int, str]:
    cmap: dict[int, str] = {}
    padrao_char = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
    padrao_range = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
    for dados in streams:
        if b"beginbfchar" not in dados and b"beginbfrange" not in dados:
            continue
        for bloco in re.findall(rb"beginbfchar(.*?)endbfchar", dados, flags=re.DOTALL):
            for origem, destino in padrao_char.findall(bloco):
                try:
                    bytes_dest = bytes.fromhex(destino.decode("ascii"))
                    cmap[int(origem, 16)] = bytes_dest.decode("utf-16-be", errors="ignore")
                except ValueError:
                    continue
        for bloco in re.findall(rb"beginbfrange(.*?)endbfrange", dados, flags=re.DOTALL):
            for inicio_hex, fim_hex, dest_hex in padrao_range.findall(bloco):
                try:
                    inicio = int(inicio_hex, 16)
                    fim = int(fim_hex, 16)
                    base = int(dest_hex, 16)
                    for offset in range(min(fim - inicio + 1, 1024)):
                        cmap[inicio + offset] = chr(base + offset)
                except ValueError:
                    continue
    return cmap


def _extrair_texto_pdf_nativo(dados_pdf: bytes) -> str:
    streams: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", dados_pdf, flags=re.DOTALL):
        cabecalho = dados_pdf[max(0, match.start() - 350) : match.start()]
        if any(marcador in cabecalho for marcador in (b"/Subtype /Image", b"/Subtype/Image", b"/DCTDecode", b"/FontFile")):
            continue
        corpo = match.group(1)
        if corpo.startswith((b"\xff\xd8", b"\x89PNG")):
            continue
        descomprimido = corpo
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                descomprimido = zlib.decompress(corpo, wbits)
                break
            except zlib.error:
                continue
        if descomprimido.startswith((b"\xff\xd8", b"\x89PNG")):
            continue
        streams.append(descomprimido)

    if not streams:
        streams = [dados_pdf]

    cmap = _extrair_cmap_pdf(streams)
    linhas_totais: list[str] = []
    token_re = re.compile(
        rb"(\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>|\[(?:\\.|[^\[\]])*\]\s*TJ|-?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?\s+T[dD]|T\*|'|\"|Tj)",
        flags=re.DOTALL,
    )
    interno_tj_re = re.compile(rb"(\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>|-?\d+(?:\.\d+)?)", flags=re.DOTALL)

    for stream in streams:
        if b"BT" not in stream and b"Tj" not in stream and b"TJ" not in stream:
            continue
        blocos = re.findall(rb"BT(.*?)ET", stream, flags=re.DOTALL) or [stream]
        for bloco in blocos:
            buffer_linha: list[str] = []
            ultimo_literal = ""
            for token_match in token_re.finditer(bloco):
                token = token_match.group(0)
                if token.startswith(b"(") and token.endswith(b")"):
                    ultimo_literal = _decodificar_literal_pdf(token[1:-1], cmap)
                elif token.startswith(b"<") and token.endswith(b">"):
                    ultimo_literal = _decodificar_hex_pdf(token[1:-1].decode("ascii", errors="ignore"), cmap)
                elif token == b"Tj":
                    if ultimo_literal:
                        buffer_linha.append(ultimo_literal)
                        ultimo_literal = ""
                elif token in (b"'", b'"'):
                    if buffer_linha:
                        linhas_totais.append("".join(buffer_linha).strip())
                        buffer_linha = []
                    if ultimo_literal:
                        buffer_linha.append(ultimo_literal)
                        ultimo_literal = ""
                elif token.endswith(b"TJ"):
                    partes_tj: list[str] = []
                    for sub_match in interno_tj_re.finditer(token):
                        sub = sub_match.group(0)
                        if sub.startswith(b"(") and sub.endswith(b")"):
                            partes_tj.append(_decodificar_literal_pdf(sub[1:-1], cmap))
                        elif sub.startswith(b"<") and sub.endswith(b">"):
                            partes_tj.append(_decodificar_hex_pdf(sub[1:-1].decode("ascii", errors="ignore"), cmap))
                        else:
                            try:
                                deslocamento = float(sub)
                                if deslocamento < -150 and partes_tj and not partes_tj[-1].endswith(" "):
                                    partes_tj.append(" ")
                            except ValueError:
                                continue
                    texto_tj = "".join(partes_tj)
                    if texto_tj:
                        buffer_linha.append(texto_tj)
                elif token == b"T*" and buffer_linha:
                    linhas_totais.append("".join(buffer_linha).strip())
                    buffer_linha = []
                elif token.endswith((b"Td", b"TD")):
                    partes_td = token.split()
                    try:
                        ty = float(partes_td[1]) if len(partes_td) >= 3 else 0.0
                    except ValueError:
                        ty = 0.0
                    if abs(ty) > 0.5 and buffer_linha:
                        linhas_totais.append("".join(buffer_linha).strip())
                        buffer_linha = []
            if buffer_linha:
                linhas_totais.append("".join(buffer_linha).strip())

    return "\n".join(linha for linha in linhas_totais if linha)


def documentos_de_pdf(caminho: str | Path) -> list[Documento]:
    """Extrai o texto de arquivos PDF (.pdf) usando pypdf ou parser nativo de streams."""
    arquivo = Path(caminho)
    textos_paginas: list[str] = []

    erro_pypdf: Exception | None = None
    try:
        pypdf = importlib.import_module("pypdf")
        leitor = pypdf.PdfReader(str(arquivo))
        for idx, pagina in enumerate(leitor.pages, start=1):
            texto_pagina = (pagina.extract_text() or "").strip()
            if texto_pagina:
                textos_paginas.append(f"Página {idx}:\n{texto_pagina}" if len(leitor.pages) > 1 else texto_pagina)
    except ModuleNotFoundError:
        pass
    except Exception as erro:
        erro_pypdf = erro

    if not textos_paginas:
        dados_pdf = arquivo.read_bytes()
        if not dados_pdf.startswith(b"%PDF"):
            if erro_pypdf is not None:
                raise ValueError(f"Arquivo PDF inválido ou corrompido: {arquivo}") from erro_pypdf
            raise ValueError(f"O arquivo não possui cabeçalho PDF válido: {arquivo}")
        texto_extraido = _extrair_texto_pdf_nativo(dados_pdf).strip()
        if texto_extraido:
            textos_paginas.append(texto_extraido)
        elif erro_pypdf is not None:
            raise ValueError(f"Arquivo PDF inválido ou corrompido: {arquivo}") from erro_pypdf

    conteudo = _sanitizar_texto("\n\n".join(textos_paginas).strip())
    if not conteudo:
        raise ValueError(f"Não encontrei texto extraível no PDF: {arquivo}")

    return [
        Documento(
            id=_slug(arquivo.name),
            conteudo=conteudo,
            fonte=arquivo.name,
            assunto=arquivo.stem,
        )
    ]


def _extrair_texto_metadados_imagem(dados: bytes) -> str:
    textos: list[str] = []
    # Chunks de texto PNG: tEXt, zTXt, iTXt
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        pos = 8
        tamanho_total = len(dados)
        while pos + 8 <= tamanho_total:
            comp = struct.unpack(">I", dados[pos : pos + 4])[0]
            tipo = dados[pos + 4 : pos + 8]
            inicio_dados = pos + 8
            fim_dados = inicio_dados + comp
            if fim_dados > tamanho_total:
                break
            bloco = dados[inicio_dados:fim_dados]
            if tipo == b"tEXt":
                partes = bloco.split(b"\x00", 1)
                texto_chunk = partes[-1].decode("latin-1", errors="ignore").strip()
                if texto_chunk:
                    textos.append(texto_chunk)
            elif tipo == b"zTXt" and b"\x00" in bloco:
                _, resto = bloco.split(b"\x00", 1)
                if len(resto) > 1:
                    try:
                        descomp = zlib.decompress(resto[1:]).decode("utf-8", errors="replace").strip()
                        if descomp:
                            textos.append(descomp)
                    except zlib.error:
                        pass
            elif tipo == b"iTXt":
                segmentos = bloco.split(b"\x00", 5)
                if len(segmentos) >= 2:
                    texto_itxt = segmentos[-1].decode("utf-8", errors="ignore").strip()
                    if texto_itxt:
                        textos.append(texto_itxt)
            pos = fim_dados + 4

    # Comentários JPEG (marcador COM 0xFFFE)
    elif dados.startswith(b"\xff\xd8"):
        pos = 2
        tamanho_total = len(dados)
        while pos + 4 <= tamanho_total and dados[pos] == 0xFF:
            marcador = dados[pos + 1]
            if marcador in (0xD9, 0xDA):  # EOI ou SOS
                break
            comp = struct.unpack(">H", dados[pos + 2 : pos + 4])[0]
            if comp < 2 or pos + 2 + comp > tamanho_total:
                break
            if marcador == 0xFE:  # COM
                comentario = dados[pos + 4 : pos + 2 + comp].decode("utf-8", errors="replace").strip()
                if comentario:
                    textos.append(comentario)
            pos += 2 + comp

    return "\n".join(t for t in textos if t)


def _ocr_windows_nativo(arquivo: Path) -> str:
    if sys.platform != "win32":
        return ""
    caminho_escapado = str(arquivo.resolve()).replace("'", "''")
    script_ps = (
        "Add-Type -AssemblyName System.Runtime.WindowsRuntime; "
        "$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]; "
        "$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]; "
        "$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]; "
        "$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | "
        "Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and "
        "$_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]; "
        "Function Await($WinRtTask, $ResultType) { "
        "$asTask = $asTaskGeneric.MakeGenericMethod($ResultType); "
        "$netTask = $asTask.Invoke($null, @($WinRtTask)); "
        "$netTask.Wait(-1) | Out-Null; $netTask.Result }; "
        f"$fs = [System.IO.File]::OpenRead('{caminho_escapado}'); "
        "$stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fs); "
        "$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) "
        "([Windows.Graphics.Imaging.BitmapDecoder]); "
        "$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap]); "
        "$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages(); "
        "$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult]); "
        "$fs.Dispose(); "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$result.Lines | ForEach-Object { Write-Output $_.Text }"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script_ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=20,
            check=False,
        )
        if proc.returncode == 0:
            linhas = [linha.strip() for linha in proc.stdout.splitlines() if linha.strip() and "InitializeDefaultDrives" not in linha]
            return "\n".join(linhas)
    except Exception:
        return ""
    return ""


def _extrair_texto_ocr_local(arquivo: Path) -> str:
    # 1. RapidOCR (100% local e gratuito via ONNX Runtime)
    try:
        modulo_rapidocr = importlib.import_module("rapidocr_onnxruntime")
        motor_ocr = modulo_rapidocr.RapidOCR()
        resultado, _ = motor_ocr(str(arquivo))
        if resultado:
            linhas = [str(item[1]).strip() for item in resultado if len(item) >= 2 and str(item[1]).strip()]
            if linhas:
                return "\n".join(linhas)
    except ModuleNotFoundError:
        pass
    except Exception:
        pass

    # 2. Tesseract OCR local (se instalado)
    try:
        pytesseract = importlib.import_module("pytesseract")
        pil_image = importlib.import_module("PIL.Image")
        with pil_image.open(arquivo) as img:
            try:
                texto_tess = str(pytesseract.image_to_string(img, lang="por+eng")).strip()
            except Exception:
                texto_tess = str(pytesseract.image_to_string(img)).strip()
            if texto_tess:
                return texto_tess
    except ModuleNotFoundError:
        pass
    except Exception:
        pass

    # 3. OCR nativo do Windows (gratuito e sem dependências externas no Windows)
    texto_win = _ocr_windows_nativo(arquivo)
    if texto_win:
        return texto_win

    return ""


def documentos_de_imagem(caminho: str | Path) -> list[Documento]:
    """Extrai texto de imagens (.png, .jpg, .jpeg, .webp, .bmp, .gif, .tif, .tiff) via OCR local gratuito ou metadados."""
    arquivo = Path(caminho)
    if not arquivo.exists():
        raise ValueError(f"Arquivo de imagem não encontrado: {arquivo}")

    partes: list[str] = []
    texto_ocr = _extrair_texto_ocr_local(arquivo).strip()
    if texto_ocr:
        partes.append(texto_ocr)

    texto_meta = _extrair_texto_metadados_imagem(arquivo.read_bytes()).strip()
    if texto_meta and texto_meta not in texto_ocr:
        partes.append(texto_meta)

    conteudo = _sanitizar_texto("\n".join(partes).strip())
    if not conteudo:
        raise ValueError(f"Não foi possível extrair texto da imagem: {arquivo}")

    return [
        Documento(
            id=_slug(arquivo.name),
            conteudo=conteudo,
            fonte=arquivo.name,
            assunto=arquivo.stem,
        )
    ]


def carregar_documento_arquivo(caminho: str | Path) -> list[Documento]:
    """Carrega um único arquivo suportado de acordo com sua extensão."""
    arquivo = Path(caminho)
    extensao = arquivo.suffix.lower()

    if extensao == ".json":
        especificacao = json.loads(arquivo.read_text(encoding="utf-8"))
        if isinstance(especificacao, dict) and "paths" in especificacao:
            return documentos_de_openapi(especificacao, fonte=arquivo.name)
        conteudo_json = _sanitizar_texto(_texto(especificacao).strip())
        if not conteudo_json:
            raise ValueError(f"Arquivo JSON vazio: {arquivo}")
        return [Documento(id=_slug(arquivo.name), conteudo=conteudo_json, fonte=arquivo.name, assunto=arquivo.stem)]

    if extensao in (".html", ".htm"):
        return documentos_de_html(arquivo)
    if extensao in EXTENSOES_PDF:
        return documentos_de_pdf(arquivo)
    if extensao in EXTENSOES_DOCX:
        return documentos_de_docx(arquivo)
    if extensao in EXTENSOES_EXCEL:
        return documentos_de_excel(arquivo)
    if extensao in EXTENSOES_IMAGEM:
        return documentos_de_imagem(arquivo)

    raise ValueError(f"Extensão de arquivo não suportada para ingestão RAG: {arquivo.suffix}")


def fragmentar_documentos(documentos: list[Documento]) -> list[Documento]:
    """Divide operações longas em trechos com sobreposição para busca semântica."""
    fragmentos: list[Documento] = []
    for documento in documentos:
        texto = documento.conteudo
        inicio = 0
        numero = 1
        while inicio < len(texto):
            fim = min(inicio + _TAMANHO_FRAGMENTO, len(texto))
            if fim < len(texto):
                quebra = texto.rfind("\n", inicio + _TAMANHO_FRAGMENTO // 2, fim)
                if quebra > inicio:
                    fim = quebra
            conteudo = texto[inicio:fim].strip()
            if conteudo:
                fragmentos.append(
                    Documento(
                        id=f"{documento.id}-trecho-{numero}",
                        conteudo=conteudo,
                        fonte=documento.fonte,
                        endpoint=documento.endpoint,
                        metodo=documento.metodo,
                        assunto=documento.assunto,
                    )
                )
                numero += 1
            if fim >= len(texto):
                break
            inicio = max(fim - _SOBREPOSICAO_FRAGMENTO, inicio + 1)
    return fragmentos


def carregar_documentos(
    pasta: str | Path | None = None,
    callback_progresso: CallbackProgresso | None = None,
) -> list[Documento]:
    """Carrega especificações OpenAPI/HTML e demais documentos suportados (PDF, DOCX, Excel, imagens)."""
    alvo = Path(pasta) if pasta is not None else _PASTA_DOCUMENTOS
    if alvo.is_file():
        if callback_progresso:
            callback_progresso(
                ProgressoIngest(
                    etapa="carregamento",
                    mensagem=f"Carregando arquivo único: {alvo.name}",
                    atual=0,
                    total=1,
                    arquivo_atual=alvo.name,
                )
            )
        fragmentos = fragmentar_documentos(carregar_documento_arquivo(alvo))
        if callback_progresso:
            callback_progresso(
                ProgressoIngest(
                    etapa="fragmentacao",
                    mensagem=f"Arquivo {alvo.name} fragmentado em {len(fragmentos)} trechos.",
                    atual=1,
                    total=1,
                    arquivo_atual=alvo.name,
                )
            )
        return fragmentos

    diretorio = alvo
    documentos: list[Documento] = []
    processados: set[Path] = set()
    arquivos_alvo: list[Path] = []

    # 1. Prioriza o OpenAPI JSON principal (ou captura Swagger UI.html apenas como fallback do Swagger)
    swagger_json_encontrado: Path | None = None
    for nome_arquivo in ("swagger.json", "openapi.json"):
        json_local = diretorio / nome_arquivo
        if json_local.exists():
            swagger_json_encontrado = json_local
            break

    if swagger_json_encontrado is not None:
        arquivos_alvo.append(swagger_json_encontrado)
        processados.add(swagger_json_encontrado.resolve())
    else:
        html_fallback = diretorio / "Swagger UI.html"
        if html_fallback.exists():
            arquivos_alvo.append(html_fallback)
            processados.add(html_fallback.resolve())

    # 2. Varre todos os demais arquivos suportados na pasta (PDF, DOCX, Excel, imagens, etc.)
    if diretorio.exists():
        arquivos_extras = sorted(
            (arq for arq in diretorio.rglob("*") if arq.is_file() and not arq.name.startswith(".")),
            key=lambda p: str(p.relative_to(diretorio)).lower(),
        )
        for arquivo in arquivos_extras:
            if arquivo.resolve() in processados:
                continue
            if arquivo.suffix.lower() not in EXTENSOES_SUPORTADAS:
                continue
            arquivos_alvo.append(arquivo)

    if not arquivos_alvo:
        raise ValueError(f"Nenhum documento suportado encontrado em: {diretorio}")

    total_arquivos = len(arquivos_alvo)
    if callback_progresso:
        callback_progresso(
            ProgressoIngest(
                etapa="descoberta",
                mensagem=f"Descobertos {total_arquivos} arquivos para ingestão em '{diretorio.name}'.",
                atual=0,
                total=total_arquivos,
            )
        )

    for idx, arquivo in enumerate(arquivos_alvo, 1):
        if callback_progresso:
            eh_imagem = arquivo.suffix.lower() in EXTENSOES_IMAGEM
            acao = "Processando OCR em" if eh_imagem else "Carregando"
            callback_progresso(
                ProgressoIngest(
                    etapa="carregamento",
                    mensagem=f"[{idx}/{total_arquivos}] {acao} {arquivo.name}...",
                    atual=idx - 1,
                    total=total_arquivos,
                    arquivo_atual=arquivo.name,
                )
            )

        if arquivo.name in ("swagger.json", "openapi.json"):
            especificacao = json.loads(arquivo.read_text(encoding="utf-8"))
            if not isinstance(especificacao, dict):
                raise ValueError("O arquivo OpenAPI precisa conter um objeto JSON.")
            docs = documentos_de_openapi(especificacao, fonte=arquivo.name)
        else:
            docs = carregar_documento_arquivo(arquivo)

        documentos.extend(docs)
        if callback_progresso:
            callback_progresso(
                ProgressoIngest(
                    etapa="carregamento",
                    mensagem=f"[{idx}/{total_arquivos}] {arquivo.name} processado ({len(docs)} documento(s) bruto(s)).",
                    atual=idx,
                    total=total_arquivos,
                    arquivo_atual=arquivo.name,
                    detalhes={"documentos_brutos_extraidos": len(docs)},
                )
            )

    if not documentos:
        raise ValueError(f"Nenhum documento extraído dos arquivos em: {diretorio}")

    if callback_progresso:
        callback_progresso(
            ProgressoIngest(
                etapa="fragmentacao",
                mensagem=f"Fragmentando {len(documentos)} documentos extraídos...",
                atual=len(documentos),
                total=len(documentos),
            )
        )

    fragmentos = fragmentar_documentos(documentos)

    if callback_progresso:
        callback_progresso(
            ProgressoIngest(
                etapa="fragmentacao",
                mensagem=f"Fragmentação concluída: {len(fragmentos)} fragmentos gerados a partir de {total_arquivos} arquivo(s).",
                atual=len(fragmentos),
                total=len(fragmentos),
                detalhes={"total_fragmentos": len(fragmentos), "total_arquivos": total_arquivos},
            )
        )

    return fragmentos
