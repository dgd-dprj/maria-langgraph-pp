"""Converte OpenAPI/Swagger ou uma captura do Swagger UI em documentos RAG.

Prefere o JSON da especificação, que contém contratos e modelos completos. A
captura HTML é uma alternativa para consulta local, mas pode conter somente os
endpoints que estavam visíveis quando foi salva.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .base import Documento

_METODOS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})
_PASTA_DOCUMENTOS = Path(__file__).resolve().parents[2] / "documentos"
_TAMANHO_FRAGMENTO = 1_200
_SOBREPOSICAO_FRAGMENTO = 160
_CPF = re.compile(r"(?<!\d)(?:\d{3}[. ]?){3}-?\d{2}(?!\d)")
_PROCESSO_CNJ = re.compile(r"(?<!\d)\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?!\d)")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_TELEFONE_BR = re.compile(r"(?<!\d)(?:\+?55[ -]?)?\(?\d{2}\)?[ -]?9?\d{4}[ -]?\d{4}(?!\d)")


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

    conteudo = "\n".join(linha for linha in linhas if linha)
    conteudo = _EMAIL.sub("[e-mail omitido]", conteudo)
    conteudo = _CPF.sub("[CPF omitido]", conteudo)
    conteudo = _PROCESSO_CNJ.sub("[número de processo omitido]", conteudo)
    conteudo = _TELEFONE_BR.sub("[telefone omitido]", conteudo)
    identificador = re.sub(r"[^a-zA-Z0-9]+", "-", f"{metodo}-{caminho}").strip("-").lower()
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
                    conteudo="\n".join(linhas_info),
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
                        id=f"swagger-grupo-{re.sub(r'[^a-zA-Z0-9]+', '-', nome).strip('-').lower()}",
                        conteudo=f"Grupo da API: {nome}\nDescrição: {descricao}",
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
        conteudo = f"Endpoint: {metodo} {atual['endpoint']}\nResumo: {resumo}".strip()
        identificador = re.sub(r"[^a-zA-Z0-9]+", "-", f"{metodo}-{atual['endpoint']}").strip("-").lower()
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


def carregar_documentos(pasta: str | Path | None = None) -> list[Documento]:
    """Carrega o OpenAPI JSON completo ou a captura HTML local como fallback."""
    diretorio = Path(pasta) if pasta is not None else _PASTA_DOCUMENTOS
    for nome_arquivo in ("swagger.json", "openapi.json"):
        json_local = diretorio / nome_arquivo
        if json_local.exists():
            especificacao = json.loads(json_local.read_text(encoding="utf-8"))
            if not isinstance(especificacao, dict):
                raise ValueError("O arquivo OpenAPI precisa conter um objeto JSON.")
            documentos = documentos_de_openapi(especificacao, fonte=json_local.name)
            return fragmentar_documentos(documentos)
    return fragmentar_documentos(documentos_de_html(diretorio / "Swagger UI.html"))
