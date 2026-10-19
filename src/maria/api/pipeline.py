"""Pipeline de requisição com a ordem e os formatos do Fastify 5.12.1 de develop.

O FastAPI valida o corpo junto com as dependências, responde 422 com `detail`
e pode autenticar depois do corpo. O contrato com a Tykhe (fixtures gravadas do
servidor real) é outro, e por isso as rotas de negócio passam por este
middleware ASGI, e não pelo roteamento do FastAPI. A ordem, executada no app de
develop @ 1157a6d:

1. procura a rota (método + caminho exato; HEAD usa a rota GET): sem rota, 404
   `{"message":"Route GET:/x not found","error":"Not Found","statusCode":404}`,
   com a query string na mensagem, e uma linha de log "Route … not found";
2. autenticação Bearer (`@fastify/bearer-auth` 10.1.3) nas rotas protegidas:
   401 `{"error":"missing authorization header"}` ou `"invalid …"`, sem linha
   de log (o plugin só registra se `error` for propriedade própria do logger, e
   no pino não é);
3. parser pelo `content-type`: `application/json` (sem caixa, com BOM aceito,
   `__proto__` recusado), `text/plain`; o resto, 415; corpo vazio ou JSON
   inválido, 400; corpo que não é UTF-8, 400 (tamanho decodificado diferente
   do Content-Length);
4. validação do corpo (`validacao.py`), que roda mesmo sem corpo;
5. o handler;
6. a serialização pelo schema da rota para o status (`serializacao.py`).

Erro com status que tem schema na rota sai `{}` (o Fastify serializa o objeto
Error pelo schema, e nenhuma propriedade declarada existe nele); sem schema, sai
o corpo padrão do Fastify. Erro 4xx é registrado em nível info com `res` e
`err`; 5xx, em nível error com `req`, `res` e `err`.
"""

from __future__ import annotations

import hmac
import json
import math
import re
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from maria.api.serializacao import Schema, serializar
from maria.api.validacao import ErroValidacao, validar_corpo
from maria.shared._js import AUSENTE, numero_js, trim_js
from maria.shared.logger import logger

CONTENT_TYPE_JSON = "application/json; charset=utf-8"
LIMITE_CORPO = 1_048_576  # bodyLimit padrão do Fastify (1 MiB)
_METODOS_COM_CORPO = frozenset(("POST", "PUT", "PATCH", "DELETE", "OPTIONS"))
_TOKEN = r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
_TIPO_MIDIA = re.compile(rf"{_TOKEN}/{_TOKEN}")
_RAZAO = {
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    413: "Payload Too Large",
    415: "Unsupported Media Type",
    500: "Internal Server Error",
}


class LogRequisicao:
    """O `req.log` do Fastify: o logger do processo com o `reqId` da requisição."""

    def __init__(self, req_id: str) -> None:
        self.req_id = req_id

    def info(self, msg: str, **campos: Any) -> None:
        logger.info(msg, reqId=self.req_id, **campos)

    def warn(self, msg: str, **campos: Any) -> None:
        logger.warning(msg, reqId=self.req_id, **campos)

    def error(self, msg: str, **campos: Any) -> None:
        logger.error(msg, reqId=self.req_id, **campos)


@dataclass
class Contexto:
    log: LogRequisicao
    corpo: Any
    cabecalhos: dict[str, str]
    # `req.params` (decodificados) e `req.query` do Fastify.
    parametros: dict[str, str] = field(default_factory=dict)
    consulta: dict[str, Any] = field(default_factory=dict)
    # `app.inject` do Fastify: chamada interna, em processo, pelo pipeline inteiro.
    injetar: Callable[[str, str, dict[str, str], Any], Awaitable[RespostaInjetada]] | None = None
    # A API_KEY com que o app subiu: o bridge a usa na chamada interna (`apiKey` de develop).
    chave_api: str = ""


@dataclass
class Resposta:
    status: int
    corpo: Any
    cabecalhos: dict[str, str] = field(default_factory=dict)
    # Corpo cru, sem serialização pelo schema: `reply.type(...).send(texto)`.
    # Com `texto` e sem `content_type`, a resposta sai sem content-type
    # (o `reply.code(403).send()` vazio do webhook).
    texto: str | None = None
    content_type: str | None = CONTENT_TYPE_JSON


@dataclass
class RespostaInjetada:
    """O que o `app.inject` devolve e o bridge usa: status e corpo."""

    status: int
    corpo_bruto: str

    def json(self) -> Any:
        # `res.json()` do light-my-request: JSON.parse do corpo, que lança se não for JSON.
        return json.loads(self.corpo_bruto)


Handler = Callable[[Contexto], Awaitable[Resposta]]


@dataclass
class Rota:
    metodo: str
    # Estático, ou com um segmento de parâmetro no fim (`/atendimentos/:chatId`).
    caminho: str
    handler: Handler
    protegida: bool = True
    corpo: Schema | None = None
    respostas: dict[int, Schema] = field(default_factory=dict)
    # Metadados para o /docs (OpenAPI).
    resumo: str = ""
    tags: tuple[str, ...] = ()


@dataclass
class _Entrada:
    """O que o roteamento já decidiu sobre a requisição, antes do handler."""

    metodo: str
    cabecalhos: dict[str, str]
    parametros: dict[str, str]
    consulta: dict[str, Any]
    injetar: Callable[[str, str, dict[str, str], Any], Awaitable[RespostaInjetada]]


class ErroFastify(Exception):
    """Um FastifyError (`FST_ERR_*`): status, código e mensagem do Fastify."""

    def __init__(self, status: int, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo


# --- URL: o roteador find-my-way 9.9.0 e o fast-querystring 1.1.2 de develop ----------

MAX_PARAM = 100  # maxParamLength padrão do find-my-way
# decodeURI do JS não decodifica estes (ECMA-262, "reservedURISet" mais "#").
_RESERVADOS_DECODE_URI = frozenset(";/?:@&=+$,#")
# `DECODE_COMPONENT_TABLE` do find-my-way (lib/url-sanitizer.js): os únicos
# escapes que o parâmetro de rota ainda decodifica depois do decodeURI.
_TABELA_COMPONENTE = {
    "23": "#", "24": "$", "25": "%", "26": "&", "2B": "+", "2b": "+", "2C": ",", "2c": ",", "2F": "/", "2f": "/",
    "3A": ":", "3a": ":", "3B": ";", "3b": ";", "3D": "=", "3d": "=", "3F": "?", "3f": "?", "40": "@",
}  # fmt: skip


class UrlInvalida(Exception):
    """O URIError do decodeURI: vira o 400 FST_ERR_BAD_URL do Fastify."""


def _byte_escapado(texto: str, i: int) -> int:
    par = texto[i + 1 : i + 3]
    if len(par) != 2 or any(c not in "0123456789abcdefABCDEF" for c in par):
        raise UrlInvalida(texto)
    return int(par, 16)


def _decodificar(texto: str, reservados: frozenset[str]) -> str:
    """`decodeURI` (com os reservados) ou `decodeURIComponent` (sem) do JS: lança
    em escape malformado e em UTF-8 inválido, inclusive surrogates."""
    saida: list[str] = []
    i = 0
    while i < len(texto):
        if texto[i] != "%":
            saida.append(texto[i])
            i += 1
            continue
        primeiro = _byte_escapado(texto, i)
        if primeiro < 0x80:
            caractere = chr(primeiro)
            saida.append(texto[i : i + 3] if caractere in reservados else caractere)
            i += 3
            continue
        tamanho = 2 if primeiro & 0xE0 == 0xC0 else 3 if primeiro & 0xF0 == 0xE0 else 4 if primeiro & 0xF8 == 0xF0 else 0
        if tamanho == 0:
            raise UrlInvalida(texto)
        sequencia = [primeiro]
        j = i + 3
        for _ in range(tamanho - 1):
            if texto[j : j + 1] != "%":
                raise UrlInvalida(texto)
            sequencia.append(_byte_escapado(texto, j))
            j += 3
        try:
            saida.append(bytes(sequencia).decode("utf-8"))
        except UnicodeDecodeError:
            raise UrlInvalida(texto) from None
        i = j
    return "".join(saida)


def _sanitizar(url: str) -> tuple[str, str, bool]:
    """`safeDecodeURI` do find-my-way: caminho decodificado (sem os reservados),
    query crua e se o parâmetro ainda tem escape reservado a decodificar."""
    deve_decodificar = False
    decodificar_param = False
    consulta = ""
    caminho = url
    i = 1
    while i < len(caminho):
        c = caminho[i]
        if c == "%":
            componente = _TABELA_COMPONENTE.get(caminho[i + 1 : i + 3])
            if componente is None:
                deve_decodificar = True
            else:
                decodificar_param = True
                if componente == "%":
                    deve_decodificar = True
                    caminho = caminho[: i + 1] + "25" + caminho[i + 1 :]
                    i += 2
                i += 2
        elif c in "?#":
            consulta = caminho[i + 1 :]
            caminho = caminho[:i]
            break
        i += 1
    if deve_decodificar:
        caminho = _decodificar(caminho, _RESERVADOS_DECODE_URI)
    return caminho, consulta, decodificar_param


def _decodificar_parametro(param: str) -> str:
    """`safeDecodeURIComponent` do find-my-way: só os escapes da tabela."""
    inicio = param.find("%")
    if inicio == -1:
        return param
    saida = [param[:inicio]]
    i = inicio
    while i < len(param):
        if param[i] == "%":
            # Escape fora da tabela vira "null" em develop (String de null); não
            # acontece, porque o decodeURI já decodificou todos os outros.
            saida.append(_TABELA_COMPONENTE.get(param[i + 1 : i + 3], "null"))
            i += 3
        else:
            saida.append(param[i])
            i += 1
    return "".join(saida)


def _tamanho_js(texto: str) -> int:
    # `.length` do JS conta unidades UTF-16.
    return len(texto.encode("utf-16-le")) // 2


def _decodificar_consulta(texto: str) -> str:
    # `fastDecode(x) || x`: escape inválido mantém o texto cru.
    try:
        return _decodificar(texto, frozenset()) or texto
    except UrlInvalida:
        return texto


def _consulta(texto: str) -> dict[str, Any]:
    """`parse` do fast-querystring 1.1.2: `+` vira espaço, chave repetida vira
    lista e escape inválido fica cru."""
    resultado: dict[str, Any] = {}
    for parte in texto.split("&"):
        if "=" in parte:
            chave, valor = parte.split("=", 1)
            tem_par = True
        else:
            chave, valor, tem_par = parte, "", False
        if not tem_par and not chave:
            continue
        chave = chave.replace("+", " ")
        if "%" in chave:
            chave = _decodificar_consulta(chave)
        if tem_par:
            valor = valor.replace("+", " ")
            if "%" in valor or "=" in valor:
                valor = _decodificar_consulta(valor)
        atual = resultado.get(chave)
        if atual is None:
            resultado[chave] = valor
        elif isinstance(atual, list):
            atual.append(valor)
        else:
            resultado[chave] = [atual, valor]
    return resultado


def _erro_midia() -> ErroFastify:
    return ErroFastify(415, "FST_ERR_CTP_INVALID_MEDIA_TYPE", "Unsupported Media Type")


def _inteiro_js(texto: str) -> int | float:
    # JSON.parse lê todo número como double: acima de 2**53 perde precisão.
    numero = int(texto)
    return numero if abs(numero) < 2**53 else float(numero)


def _recusar_constante(nome: str) -> Any:
    raise ValueError(nome)


def _objeto_seguro(pares: list[tuple[str, Any]]) -> dict[str, Any]:
    # secure-json-parse (o parser JSON do Fastify) recusa __proto__ e constructor.prototype.
    for chave, valor in pares:
        if chave == "__proto__" or (chave == "constructor" and isinstance(valor, dict) and "prototype" in valor):
            raise ValueError("Object contains forbidden prototype property")
    return dict(pares)


def _parse_json(texto: str) -> Any:
    if not texto:
        raise ErroFastify(400, "FST_ERR_CTP_EMPTY_JSON_BODY", "Body cannot be empty when content-type is set to 'application/json'")
    if texto.startswith("\ufeff"):
        texto = texto[1:]
    try:
        return json.loads(texto, parse_int=_inteiro_js, parse_constant=_recusar_constante, object_pairs_hook=_objeto_seguro)
    except ValueError:
        raise ErroFastify(
            400, "FST_ERR_CTP_INVALID_JSON_BODY", "Body is not valid JSON but content-type is set to 'application/json'"
        ) from None


def _corpo_vazio(cabecalhos: dict[str, str]) -> bool:
    # isEmptyBody do Fastify: decide pelo cabeçalho, e não pelos bytes.
    tamanho = cabecalhos.get("content-length")
    return "transfer-encoding" not in cabecalhos and (tamanho is None or tamanho == "0")


def _ler_corpo(cabecalhos: dict[str, str], bruto: bytes) -> Any:
    tipo = cabecalhos.get("content-type")
    if tipo is None:
        if _corpo_vazio(cabecalhos):
            return AUSENTE
        raise _erro_midia()
    principal = tipo.split(";", 1)[0].strip()
    if not _TIPO_MIDIA.fullmatch(principal):
        raise _erro_midia()
    principal = principal.lower()
    if principal not in ("application/json", "text/plain"):
        raise _erro_midia()
    texto = _ler_texto(cabecalhos, bruto)
    return _parse_json(texto) if principal == "application/json" else texto


def _ler_texto(cabecalhos: dict[str, str], bruto: bytes) -> str:
    """`rawBody` do Fastify com `asString`: o corpo é lido como UTF-8, e byte
    inválido vira U+FFFD (3 bytes). O tamanho conferido com o limite e com o
    Content-Length é o do texto decodificado, e não o dos bytes recebidos: um
    corpo que não é UTF-8 (acento em Latin-1, por exemplo) dá 400
    FST_ERR_CTP_INVALID_CONTENT_LENGTH. Achado no teste do guia de rodar
    localmente (curl do Git Bash no Windows manda o argumento em Latin-1)."""
    declarado = numero_js(cabecalhos["content-length"]) if "content-length" in cabecalhos else math.nan
    if declarado > LIMITE_CORPO:
        raise ErroFastify(413, "FST_ERR_CTP_BODY_TOO_LARGE", "Request body is too large")
    texto = bruto.decode("utf-8", errors="replace")
    recebido = len(texto.encode("utf-8"))
    if recebido > LIMITE_CORPO:
        raise ErroFastify(413, "FST_ERR_CTP_BODY_TOO_LARGE", "Request body is too large")
    if not math.isnan(declarado) and recebido != declarado:
        raise ErroFastify(400, "FST_ERR_CTP_INVALID_CONTENT_LENGTH", "Request body size did not match Content-Length")
    return texto


def _autenticar(cabecalhos: dict[str, str], chave_api: bytes) -> str | None:
    """Mensagem do 401, ou None se autenticado (`verify-bearer-auth-factory.js`)."""
    cabecalho = cabecalhos.get("authorization")
    if not cabecalho:
        return "missing authorization header"
    if cabecalho[:7] != "Bearer ":
        return "invalid authorization header"
    if not hmac.compare_digest(trim_js(cabecalho[7:]).encode(), chave_api):
        return "invalid authorization header"
    return None


def _pilha(erro: BaseException) -> str:
    return "".join(traceback.format_exception(erro)).rstrip("\n")


def _err_log(erro: BaseException) -> dict[str, Any]:
    if isinstance(erro, ErroValidacao):
        return {
            "type": "Error",
            "message": str(erro),
            "stack": _pilha(erro),
            "statusCode": 400,
            "code": "FST_ERR_VALIDATION",
            "validation": [erro.validacao],
            "validationContext": "body",
        }
    if isinstance(erro, ErroFastify):
        return {
            "type": "FastifyError",
            "message": str(erro),
            "stack": _pilha(erro),
            "code": erro.codigo,
            "name": "FastifyError",
            "statusCode": erro.status,
        }
    # Propriedades próprias que o serializador de erro do pino acrescenta, quando a
    # exceção reproduz um erro de develop (por exemplo, o `name` do EmptyInputError).
    extras: dict[str, Any] = getattr(erro, "campos_log_js", {})
    return {"type": type(erro).__name__, "message": str(erro), "stack": _pilha(erro), **extras}


class PipelineFastify:
    """Middleware ASGI. Caminhos em `delegados` (o /docs) vão ao app de baixo."""

    def __init__(self, app: ASGIApp, rotas: Iterable[Rota], chave_api: str, delegados: tuple[str, ...] = ("/docs",)) -> None:
        self.app = app
        lista = list(rotas)
        self.rotas = {(r.metodo, r.caminho): r for r in lista if ":" not in r.caminho}
        # Rotas com parâmetro no último segmento, por método: (prefixo, nome, rota).
        self.parametricas: dict[str, list[tuple[str, str, Rota]]] = {}
        for r in lista:
            if ":" in r.caminho:
                prefixo, nome = r.caminho.rsplit(":", 1)
                self.parametricas.setdefault(r.metodo, []).append((prefixo, nome, r))
        # Métodos com alguma rota: para os outros, o find-my-way nem olha a URL.
        self.metodos = {r.metodo for r in lista}
        self.chave_api = chave_api.encode()
        self.delegados = delegados

    def _casar(self, metodo: str, caminho: str, decodificar_param: bool) -> tuple[Rota | None, dict[str, str], bool]:
        """Rota e parâmetros, como o `find` do find-my-way: estática primeiro, e o
        parâmetro vai até a próxima barra. O último valor diz se o parâmetro passou
        do maxParamLength (414)."""
        estatica = self.rotas.get((metodo, caminho))
        if estatica is not None:
            return estatica, {}, False
        for prefixo, nome, rota in self.parametricas.get(metodo, ()):
            if not caminho.startswith(prefixo):
                continue
            resto = caminho[len(prefixo) :]
            if "/" in resto:
                continue
            param = _decodificar_parametro(resto) if decodificar_param else resto
            if _tamanho_js(param) > MAX_PARAM:
                return None, {}, True
            return rota, {nome: param}, False
        return None, {}, False

    async def _injetar(self, raiz: ASGIApp, metodo: str, url: str, cabecalhos: dict[str, str], corpo: Any) -> RespostaInjetada:
        """`app.inject` do light-my-request: a requisição passa pelo app inteiro, em
        processo, com o log de requisição; o corpo objeto vira JSON."""
        conteudo = json.dumps(corpo, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        transporte = httpx.ASGITransport(app=raiz, client=("127.0.0.1", 0))
        async with httpx.AsyncClient(transport=transporte, base_url="http://localhost:80") as cliente:
            r = await cliente.request(metodo, url, headers={**cabecalhos, "content-type": "application/json"}, content=conteudo)
        return RespostaInjetada(status=r.status_code, corpo_bruto=r.text)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inicio = time.perf_counter()
        metodo: str = scope["method"]
        caminho: str = scope.get("raw_path", scope["path"].encode()).decode("latin-1")
        consulta: bytes = scope.get("query_string", b"")
        url = caminho + ("?" + consulta.decode("latin-1") if consulta else "")
        cabecalhos = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        cliente = scope.get("client") or ("", 0)
        req_log = {"method": metodo, "url": url, "host": cabecalhos.get("host"), "remoteAddress": cliente[0], "remotePort": cliente[1]}
        cabeca = metodo == "HEAD"
        metodo_arvore = "GET" if cabeca else metodo

        # O roteador decodifica a URL antes de qualquer log: URL malformada (400) e
        # parâmetro longo demais (414) saem escritos direto, sem linha nenhuma
        # (onBadUrl e onMaxParamLength de fastify.js sem frameworkErrors).
        rota: Rota | None = None
        parametros: dict[str, str] = {}
        texto_consulta = ""
        delegado = any(scope["path"] == d or scope["path"].startswith(d + "/") for d in self.delegados)
        if not delegado and metodo_arvore in self.metodos:
            try:
                caminho_decodificado, texto_consulta, decodificar_param = _sanitizar(url)
            except UrlInvalida:
                await self._enviar_cru(send, 400, "FST_ERR_BAD_URL", f"'{url}' is not a valid url component", cabeca)
                return
            rota, parametros, longo = self._casar(metodo_arvore, caminho_decodificado, decodificar_param)
            if longo:
                await self._enviar_cru(
                    send, 414, "FST_ERR_MAX_PARAM_LENGTH", f"'{caminho_decodificado}' is exceeding the max param length", cabeca
                )
                return

        req_id = str(uuid.uuid4())
        log = LogRequisicao(req_id)
        log.info("incoming request", req=req_log)

        if delegado:
            status_delegado = 500

            async def enviar(mensagem: Message) -> None:
                nonlocal status_delegado
                if mensagem["type"] == "http.response.start":
                    status_delegado = mensagem["status"]
                await send(mensagem)

            await self.app(scope, receive, enviar)
            log.info("request completed", res={"statusCode": status_delegado}, responseTime=(time.perf_counter() - inicio) * 1000)
            return

        if rota is None:
            mensagem = f"Route {metodo}:{url} not found"
            log.info(mensagem)
            corpo = json.dumps({"message": mensagem, "error": "Not Found", "statusCode": 404}, ensure_ascii=False, separators=(",", ":"))
            await self._enviar(send, 404, corpo, {}, cabeca)
            status = 404
        else:
            raiz: ASGIApp = scope.get("app", self.app)

            async def injetar(metodo_interno: str, url_interna: str, cab: dict[str, str], corpo_interno: Any) -> RespostaInjetada:
                return await self._injetar(raiz, metodo_interno, url_interna, cab, corpo_interno)

            entrada = _Entrada(metodo, cabecalhos, parametros, _consulta(texto_consulta), injetar)
            status, corpo, extras, tipo = await self._tratar(rota, entrada, receive, log, req_log)
            await self._enviar(send, status, corpo, extras, cabeca, tipo)
        log.info("request completed", res={"statusCode": status}, responseTime=(time.perf_counter() - inicio) * 1000)

    async def _tratar(
        self, rota: Rota, entrada: _Entrada, receive: Receive, log: LogRequisicao, req_log: dict[str, Any]
    ) -> tuple[int, str, dict[str, str], str | None]:
        if rota.protegida:
            falha = _autenticar(entrada.cabecalhos, self.chave_api)
            if falha is not None:
                return 401, json.dumps({"error": falha}, separators=(",", ":")), {}, CONTENT_TYPE_JSON
        try:
            bruto = await _ler_bytes(receive)
            corpo = _ler_corpo(entrada.cabecalhos, bruto) if entrada.metodo in _METODOS_COM_CORPO else AUSENTE
            if rota.corpo is not None:
                corpo = validar_corpo(rota.corpo, corpo)
            ctx = Contexto(
                log=log,
                corpo=corpo,
                cabecalhos=entrada.cabecalhos,
                parametros=entrada.parametros,
                consulta=entrada.consulta,
                injetar=entrada.injetar,
                chave_api=self.chave_api.decode(),
            )
            resposta = await rota.handler(ctx)
            if resposta.texto is not None:
                return resposta.status, resposta.texto, resposta.cabecalhos, resposta.content_type
            return resposta.status, serializar(rota.respostas.get(resposta.status), resposta.corpo), resposta.cabecalhos, CONTENT_TYPE_JSON
        except (ErroValidacao, ErroFastify) as erro:
            status = 400 if isinstance(erro, ErroValidacao) else erro.status
            if status >= 500:
                log.error(str(erro), req=req_log, res={"statusCode": status}, err=_err_log(erro))
            else:
                log.info(str(erro), res={"statusCode": status}, err=_err_log(erro))
            return status, self._corpo_erro(rota, status, erro), {}, CONTENT_TYPE_JSON
        except Exception as erro:
            # O tratador de erro padrão do Fastify pega qualquer exceção: 500.
            log.error(str(erro), req=req_log, res={"statusCode": 500}, err=_err_log(erro))
            return 500, self._corpo_erro(rota, 500, erro), {}, CONTENT_TYPE_JSON

    @staticmethod
    def _corpo_erro(rota: Rota, status: int, erro: BaseException) -> str:
        if status in rota.respostas:
            return "{}"
        corpo: dict[str, Any] = {"statusCode": status}
        if isinstance(erro, ErroFastify):
            corpo["code"] = erro.codigo
        corpo["error"] = _RAZAO.get(status, "Internal Server Error")
        corpo["message"] = str(erro)
        return json.dumps(corpo, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    async def _enviar_cru(cls, send: Send, status: int, codigo: str, mensagem: str, cabeca: bool) -> None:
        """`res.writeHead` + `res.end` do onBadUrl/onMaxParamLength: JSON sem charset,
        chaves nesta ordem e "Bad Request" também no 414 (como em fastify.js)."""
        corpo = json.dumps(
            {"error": "Bad Request", "code": codigo, "message": mensagem, "statusCode": status}, ensure_ascii=False, separators=(",", ":")
        )
        await cls._enviar(send, status, corpo, {}, cabeca, "application/json")

    @staticmethod
    async def _enviar(
        send: Send, status: int, corpo: str, extras: dict[str, str], cabeca: bool, content_type: str | None = CONTENT_TYPE_JSON
    ) -> None:
        dados = corpo.encode("utf-8")
        cabecalhos = {**({"content-type": content_type} if content_type is not None else {}), **{k.lower(): v for k, v in extras.items()}}
        cabecalhos["content-length"] = str(len(dados))
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in cabecalhos.items()],
            }
        )
        await send({"type": "http.response.body", "body": b"" if cabeca else dados})


async def _ler_bytes(receive: Receive) -> bytes:
    partes: list[bytes] = []
    while True:
        mensagem = await receive()
        if mensagem["type"] != "http.request":
            break
        partes.append(mensagem.get("body", b""))
        if not mensagem.get("more_body", False):
            break
    return b"".join(partes)
