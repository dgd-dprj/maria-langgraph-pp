"""Bedrock FALSO local para os testes do módulo ia (servidor HTTP em 127.0.0.1,
credencial fictícia; nada sai da máquina), passando pelo langchain-aws e pelo
botocore de verdade.

Os módulos criam o `modelo` na importação, como em develop, e a configuração de
teste da fundação não carrega nada de IA. Por isso a fixture troca o atributo
`modelo` de cada módulo por um criado com `criar_modelo()` depois de apontar
`AWS_ENDPOINT_URL_BEDROCK_RUNTIME` para o servidor falso: o mesmo caminho de
construção (Config, cota do SDK JS), sem depender da ordem de importação.

As respostas roteirizadas são as do script de caracterização de develop
(`tests/fixtures/ia/caracterizacao-ia.mts`).
"""

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote

import pytest
from botocore.retries import standard
from langchain_core.runnables import retry as retry_runnable
from tenacity import wait_none

from maria.ia import _estruturado, classificar, desambiguar, extrair, reescrever, sumarizar

MODELO_DE_PRODUCAO = "us.anthropic.claude-haiku-4-5-20251001-v1:0"  # infra/terraform/ecs.tf:40
USO = {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18}


@dataclass
class Roteiro:
    status: int
    corpo: Any
    cabecalhos: dict[str, str] = field(default_factory=dict)


def ferramenta(entrada: Any, uso: Any = USO) -> Roteiro:
    corpo: dict[str, Any] = {
        "output": {
            "message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "tooluse_1", "name": "extract", "input": entrada}}]}
        },
        "stopReason": "tool_use",
    }
    if uso:
        corpo["usage"] = uso
    corpo["metrics"] = {"latencyMs": 5}
    return Roteiro(200, corpo)


SO_TEXTO = Roteiro(
    200,
    {
        "output": {"message": {"role": "assistant", "content": [{"text": "não sei"}]}},
        "stopReason": "end_turn",
        "usage": USO,
        "metrics": {"latencyMs": 5},
    },
)


def _erro(status: int, tipo: str, mensagem: str) -> Roteiro:
    return Roteiro(status, {"message": mensagem}, {"x-amzn-errortype": f"{tipo}:http://internal.amazon.com/coral/com.amazon.bedrock/"})


THROTTLE = _erro(429, "ThrottlingException", "Too many requests, please wait before trying again.")
ERRO_500 = _erro(500, "InternalServerException", "Internal error")
VALIDACAO_400 = _erro(400, "ValidationException", "Malformed input request")


@dataclass
class Requisicao:
    caminho: str
    corpo_bruto: bytes

    @property
    def corpo(self) -> Any:
        return json.loads(self.corpo_bruto)


@dataclass
class BedrockFalso:
    fila: list[Roteiro] = field(default_factory=list)
    requisicoes: list[Requisicao] = field(default_factory=list)
    _trava: threading.Lock = field(default_factory=threading.Lock)

    def roteirizar(self, *roteiros: Roteiro) -> None:
        """Responde na ordem; o último se repete depois que a fila acaba."""
        self.fila = list(roteiros)

    def _proximo(self) -> Roteiro:
        with self._trava:
            return self.fila.pop(0) if len(self.fila) > 1 else self.fila[0]


@pytest.fixture
def bedrock(monkeypatch: pytest.MonkeyPatch) -> Iterator[BedrockFalso]:
    falso = BedrockFalso()

    class Tratador(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            bruto = self.rfile.read(int(self.headers.get("content-length", "0")))
            with falso._trava:
                falso.requisicoes.append(Requisicao(unquote(self.path), bruto))
            r = falso._proximo()
            corpo = json.dumps(r.corpo).encode()
            self.send_response(r.status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(corpo)))
            for k, v in r.cabecalhos.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *args: object) -> None:
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
    threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", f"http://127.0.0.1:{servidor.server_address[1]}")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKEFAKEFAKEFAKE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fakefakefakefakefakefakefakefakefakefake")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", MODELO_DE_PRODUCAO)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("REESCREVER_IA", "true")
    monkeypatch.setenv("EXTRACAO_LIVRE_IA", "true")
    # Sem dormir: as esperas do with_retry (tenacity) e do botocore.
    monkeypatch.setattr(retry_runnable, "wait_exponential_jitter", lambda **_: wait_none())
    monkeypatch.setattr(standard.ExponentialBackoff, "delay_amount", lambda self, contexto: 0.0)
    # Um modelo para os cinco módulos: criar cliente boto3 é caro, e nenhum
    # teste esgota a cota de retentativas (500 fichas).
    modelo = _estruturado.criar_modelo()
    for modulo in (classificar, desambiguar, extrair, reescrever, sumarizar):
        monkeypatch.setattr(modulo, "modelo", modelo)
    yield falso
    servidor.shutdown()
    servidor.server_close()


def linhas_de_log(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(linha) for linha in capsys.readouterr().out.splitlines() if linha.strip()]
