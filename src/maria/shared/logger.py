"""Logger único do processo, com o envelope de linha do pino.

Cada linha sai como um objeto JSON em stdout, na mesma forma que o `pino()` de
develop gravava: `level` numérico, `time` em milissegundos, `pid`, `hostname`,
os campos de negócio no primeiro nível e `msg` por último. `scripts/logs-prod.sh`
e os painéis do Grafana (CloudWatch Logs Insights) leem essas chaves pelo nome,
então elas não mudam.

Uso: `logger.info("[verde] apenado: chamada concluída", chatId=..., duracaoMs=...)`.
Os nomes dos campos continuam em camelCase. Campo com valor `None` é omitido da
linha, como o `undefined` do JS. Uma exceção passada como `err=` é serializada
como o serializador `err` do pino: `{type, message, stack}`.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
import traceback
from collections.abc import Mapping, MutableMapping
from typing import Any, ClassVar

import structlog

# Níveis do pino. `warn` e `warning` dão o mesmo número.
NIVEIS_PINO: dict[str, int] = {
    "trace": 10,
    "debug": 20,
    "info": 30,
    "warn": 40,
    "warning": 40,
    "error": 50,
    "exception": 50,
    "critical": 60,
    "fatal": 60,
}

_PID = os.getpid()
_HOSTNAME = socket.gethostname()


def serializar_erro(erro: BaseException) -> dict[str, str]:
    """Mesmo formato do serializador `err` padrão do pino."""
    return {
        "type": type(erro).__name__,
        "message": str(erro),
        "stack": "".join(traceback.format_exception(erro)).rstrip("\n"),
    }


def _valor(v: Any) -> Any:
    if isinstance(v, BaseException):
        return serializar_erro(v)
    if isinstance(v, Mapping):
        return {k: _valor(x) for k, x in v.items() if x is not None}
    return v


def _envelope_pino(_logger: Any, metodo: str, evento: MutableMapping[str, Any]) -> Mapping[str, Any]:
    msg = evento.pop("event", None)
    linha: dict[str, Any] = {
        "level": NIVEIS_PINO.get(metodo, 30),
        "time": time.time_ns() // 1_000_000,
        "pid": _PID,
        "hostname": _HOSTNAME,
    }
    for chave, valor in evento.items():
        if valor is None:
            continue
        linha[chave] = _valor(valor)
    if msg is not None:
        linha["msg"] = msg
    return linha


def _renderizar(_logger: Any, _metodo: str, linha: Mapping[str, Any]) -> str:
    # Sem espaços e com UTF-8 cru, como o JSON.stringify do pino.
    return json.dumps(linha, ensure_ascii=False, separators=(",", ":"), default=str)


class _SaidaPadrao:
    """Escreve em `sys.stdout` resolvido a cada linha (e não na importação),
    para que a captura de saída dos testes funcione."""

    def msg(self, mensagem: str) -> None:
        # Sempre UTF-8, como o pino. Sem isso, com a saída redirecionada o Python
        # usa a codificação local (cp1252 no Windows) e corrompe "—", "ã" etc.
        saida = sys.stdout
        bruto = getattr(saida, "buffer", None)
        if bruto is None:
            saida.write(mensagem + "\n")
            saida.flush()
            return
        saida.flush()
        bruto.write((mensagem + "\n").encode("utf-8"))
        bruto.flush()

    log = debug = info = warn = warning = error = critical = exception = fatal = msg


logger: structlog.typing.FilteringBoundLogger = structlog.wrap_logger(
    _SaidaPadrao(),
    processors=[_envelope_pino, _renderizar],
    # Mesmo nível mínimo padrão do pino: info.
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    cache_logger_on_first_use=True,
)


class _PonteStdlib(logging.Handler):
    """Encaminha o logging da biblioteca padrão (uvicorn e afins) para o mesmo
    envelope, para que nenhuma linha de texto puro chegue ao stdout:
    `scripts/logs-prod.sh` assume que toda linha é JSON."""

    _METODOS: ClassVar[dict[int, str]] = {
        logging.DEBUG: "debug",
        logging.INFO: "info",
        logging.WARNING: "warn",
        logging.ERROR: "error",
        logging.CRITICAL: "fatal",
    }

    def emit(self, registro: logging.LogRecord) -> None:
        metodo = self._METODOS.get(registro.levelno, "info")
        campos: dict[str, Any] = {}
        if registro.exc_info and registro.exc_info[1] is not None:
            campos["err"] = registro.exc_info[1]
        getattr(logger, metodo)(registro.getMessage(), **campos)


# Bibliotecas cujos registros abaixo de WARNING carregam conteúdo do atendimento:
# o botocore registra em DEBUG o corpo da requisição ao Bedrock (o prompt, com o
# relato da pessoa, e o texto dos embeddings); o httpx e o httpcore registram a
# URL completa, que no Verde inclui ?cpf= (verde.ts:291); urllib3 e s3transfer são
# o que o boto3 usa por baixo; o psycopg_pool registra cada conexão entregue.
# O nível fica FIXO em cada uma delas, e não herdado: baixar o nível raiz para
# DEBUG numa depuração de incidente não as afeta. Decisão registrada na #208.
BIBLIOTECAS_COM_NIVEL_FIXO: tuple[str, ...] = (
    "botocore",
    "boto3",
    "urllib3",
    "s3transfer",
    "httpx",
    "httpcore",
    "psycopg",
)


def configurar_logging_stdlib() -> None:
    # Três barreiras independentes contra registro de biblioteca com dado pessoal:
    # 1. o nível raiz fica em WARNING (bibliotecas sem nível próprio);
    # 2. as BIBLIOTECAS_COM_NIVEL_FIXO ficam em WARNING mesmo se o raiz mudar;
    # 3. o logger structlog filtra abaixo de INFO.
    # Só o uvicorn fica em INFO, para as linhas de inicialização, como o
    # "Server listening" do Fastify.
    raiz = logging.getLogger()
    raiz.handlers = [_PonteStdlib()]
    raiz.setLevel(logging.WARNING)
    for nome in BIBLIOTECAS_COM_NIVEL_FIXO:
        logging.getLogger(nome).setLevel(logging.WARNING)
    for nome in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(nome)
        lg.handlers = []
        lg.propagate = True
        lg.setLevel(logging.INFO)
