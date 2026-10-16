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
   inválido, 400;
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
import re
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from maria.api.serializacao import Schema, serializar
from maria.api.validacao import ErroValidacao, validar_corpo
from maria.shared._js import AUSENTE, trim_js
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


@dataclass
class Resposta:
    status: int
    corpo: Any
    cabecalhos: dict[str, str] = field(default_factory=dict)


Handler = Callable[[Contexto], Awaitable[Resposta]]


@dataclass
class Rota:
    metodo: str
    caminho: str
    handler: Handler
    protegida: bool = True
    corpo: Schema | None = None
    respostas: dict[int, Schema] = field(default_factory=dict)
    # Metadados para o /docs (OpenAPI).
    resumo: str = ""
    tags: tuple[str, ...] = ()


class ErroFastify(Exception):
    """Um FastifyError (`FST_ERR_*`): status, código e mensagem do Fastify."""

    def __init__(self, status: int, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo


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


def _parse_json(bruto: bytes) -> Any:
    if not bruto:
        raise ErroFastify(400, "FST_ERR_CTP_EMPTY_JSON_BODY", "Body cannot be empty when content-type is set to 'application/json'")
    texto = bruto.decode("utf-8", errors="replace")
    if texto.startswith("﻿"):
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
    if len(bruto) > LIMITE_CORPO:
        raise ErroFastify(413, "FST_ERR_CTP_BODY_TOO_LARGE", "Request body is too large")
    principal = principal.lower()
    if principal == "application/json":
        return _parse_json(bruto)
    if principal == "text/plain":
        return bruto.decode("utf-8", errors="replace")
    raise _erro_midia()


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
    return {"type": type(erro).__name__, "message": str(erro), "stack": _pilha(erro)}


class PipelineFastify:
    """Middleware ASGI. Caminhos em `delegados` (o /docs) vão ao app de baixo."""

    def __init__(self, app: ASGIApp, rotas: Iterable[Rota], chave_api: str, delegados: tuple[str, ...] = ("/docs",)) -> None:
        self.app = app
        self.rotas = {(r.metodo, r.caminho): r for r in rotas}
        self.chave_api = chave_api.encode()
        self.delegados = delegados

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inicio = time.perf_counter()
        req_id = str(uuid.uuid4())
        log = LogRequisicao(req_id)
        metodo: str = scope["method"]
        caminho: str = scope.get("raw_path", scope["path"].encode()).decode("latin-1")
        consulta: bytes = scope.get("query_string", b"")
        url = caminho + ("?" + consulta.decode("latin-1") if consulta else "")
        cabecalhos = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        cliente = scope.get("client") or ("", 0)
        req_log = {"method": metodo, "url": url, "host": cabecalhos.get("host"), "remoteAddress": cliente[0], "remotePort": cliente[1]}
        log.info("incoming request", req=req_log)

        if any(scope["path"] == d or scope["path"].startswith(d + "/") for d in self.delegados):
            status_delegado = 500

            async def enviar(mensagem: Message) -> None:
                nonlocal status_delegado
                if mensagem["type"] == "http.response.start":
                    status_delegado = mensagem["status"]
                await send(mensagem)

            await self.app(scope, receive, enviar)
            log.info("request completed", res={"statusCode": status_delegado}, responseTime=(time.perf_counter() - inicio) * 1000)
            return

        cabeca = metodo == "HEAD"
        rota = self.rotas.get(("GET" if cabeca else metodo, scope["path"]))
        if rota is None:
            mensagem = f"Route {metodo}:{url} not found"
            log.info(mensagem)
            corpo = json.dumps({"message": mensagem, "error": "Not Found", "statusCode": 404}, ensure_ascii=False, separators=(",", ":"))
            await self._enviar(send, 404, corpo, {}, cabeca)
        else:
            status, corpo, extras = await self._tratar(rota, metodo, cabecalhos, receive, log, req_log)
            await self._enviar(send, status, corpo, extras, cabeca)
        log.info("request completed", res={"statusCode": status if rota else 404}, responseTime=(time.perf_counter() - inicio) * 1000)

    async def _tratar(
        self, rota: Rota, metodo: str, cabecalhos: dict[str, str], receive: Receive, log: LogRequisicao, req_log: dict[str, Any]
    ) -> tuple[int, str, dict[str, str]]:
        if rota.protegida:
            falha = _autenticar(cabecalhos, self.chave_api)
            if falha is not None:
                return 401, json.dumps({"error": falha}, separators=(",", ":")), {}
        try:
            bruto = await _ler_bytes(receive)
            corpo = _ler_corpo(cabecalhos, bruto) if metodo in _METODOS_COM_CORPO else AUSENTE
            if rota.corpo is not None:
                corpo = validar_corpo(rota.corpo, corpo)
            resposta = await rota.handler(Contexto(log=log, corpo=corpo, cabecalhos=cabecalhos))
            return resposta.status, serializar(rota.respostas.get(resposta.status), resposta.corpo), resposta.cabecalhos
        except (ErroValidacao, ErroFastify) as erro:
            status = 400 if isinstance(erro, ErroValidacao) else erro.status
            log.info(str(erro), res={"statusCode": status}, err=_err_log(erro))
            return status, self._corpo_erro(rota, status, erro), {}
        except Exception as erro:
            # O tratador de erro padrão do Fastify pega qualquer exceção: 500.
            log.error(str(erro), req=req_log, res={"statusCode": 500}, err=_err_log(erro))
            return 500, self._corpo_erro(rota, 500, erro), {}

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

    @staticmethod
    async def _enviar(send: Send, status: int, corpo: str, extras: dict[str, str], cabeca: bool) -> None:
        dados = corpo.encode("utf-8")
        cabecalhos = {"content-type": CONTENT_TYPE_JSON, **{k.lower(): v for k, v in extras.items()}}
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
