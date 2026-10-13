"""Retry dos embeddings contra um Bedrock FALSO local (servidor HTTP em 127.0.0.1,
credencial fictícia; nada sai da máquina), passando pelo langchain-aws e pelo
botocore de verdade.

O comportamento reproduzido é o de develop @ 4e695f2, medido com o mesmo tipo de
servidor falso: 49 requisições com 400, 147 com 429 e 99 com 500 antes de
desistir, depois de 12,6 a 13,4 minutos. É defeito
reproduzido de propósito (#222); quando ele for corrigido,
estes números mudam junto com a correção.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from botocore.retries import standard

from maria.shared import bedrock, embeddings_fluxos
from maria.shared.bedrock import espera_do_p_retry
from maria.shared.embeddings_fluxos import ErroEmbeddingBedrock, gerar_embedding


class _BedrockFalso:
    def __init__(self) -> None:
        self.status = 200
        self.tipo = ""
        self.requisicoes = 0
        self._trava = threading.Lock()


@pytest.fixture
def bedrock_falso(monkeypatch: pytest.MonkeyPatch) -> Iterator[_BedrockFalso]:
    estado = _BedrockFalso()

    class Tratador(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("content-length", "0")))
            with estado._trava:
                estado.requisicoes += 1
            if estado.status == 200:
                corpo = json.dumps({"embedding": [0.1, 0.2], "inputTextTokenCount": 3}).encode()
            else:
                corpo = json.dumps({"message": "falha simulada"}).encode()
            self.send_response(estado.status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(corpo)))
            if estado.tipo:
                self.send_header("x-amzn-errortype", f"{estado.tipo}:http://internal.amazon.com/coral/com.amazon.bedrock/")
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *args: object) -> None:
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
    threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", f"http://127.0.0.1:{servidor.server_address[1]}")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKEFAKEFAKEFAKE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fakefakefakefakefakefakefakefakefakefake")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    # Sem dormir: as esperas do p-retry (de 63 a 126 s por camada) e as do botocore.
    monkeypatch.setattr(bedrock, "espera_do_p_retry", lambda tentativa: 0.0)
    monkeypatch.setattr(standard.ExponentialBackoff, "delay_amount", lambda self, contexto: 0.0)
    yield estado
    servidor.shutdown()
    servidor.server_close()


async def test_sucesso_faz_uma_requisicao(bedrock_falso: _BedrockFalso) -> None:
    assert await gerar_embedding("texto") == [0.1, 0.2]
    assert bedrock_falso.requisicoes == 1


async def test_400_persistente_faz_49_requisicoes_como_develop(bedrock_falso: _BedrockFalso) -> None:
    # 7 × 7 chamadas ao SDK (duas camadas de AsyncCaller); o SDK não retenta 400.
    bedrock_falso.status, bedrock_falso.tipo = 400, "ValidationException"
    with pytest.raises(ErroEmbeddingBedrock) as erro:
        await gerar_embedding("texto")
    assert bedrock_falso.requisicoes == 49
    assert str(erro.value) == "An error occurred while embedding documents with Bedrock: falha simulada"


async def test_429_persistente_faz_147_requisicoes_como_develop(bedrock_falso: _BedrockFalso) -> None:
    # 49 chamadas ao SDK × 3 tentativas do modo standard (98 retentativas × 5
    # fichas cabem nas 500). No modo legacy do boto3 (cliente sem Config) seriam
    # 49 × 5 = 245; com "max_attempts": 3, 49 × 4 = 196.
    bedrock_falso.status, bedrock_falso.tipo = 429, "ThrottlingException"
    with pytest.raises(ErroEmbeddingBedrock):
        await gerar_embedding("texto")
    assert bedrock_falso.requisicoes == 147


async def test_500_persistente_faz_99_requisicoes_como_develop(bedrock_falso: _BedrockFalso) -> None:
    # O SDK JS cobra 10 fichas por retentativa de 5xx: a cota de 500 acaba em 50
    # retentativas, e as chamadas seguintes vão sem retry: 49 + 50 = 99. Com os
    # custos do botocore (5 fichas) seriam 147.
    bedrock_falso.status, bedrock_falso.tipo = 500, "InternalServerException"
    with pytest.raises(ErroEmbeddingBedrock):
        await gerar_embedding("texto")
    assert bedrock_falso.requisicoes == 99


def test_cliente_usa_a_config_compartilhada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    # "max_attempts": 3 no botocore são 3 RETENTATIVAS (4 requisições): o total
    # certo é "total_max_attempts". A contagem do teste do 500 é a prova.
    cliente = embeddings_fluxos._cliente_embeddings()
    assert cliente.client.meta.config.retries == {"mode": "standard", "total_max_attempts": 3}


def test_troca_da_cota_nao_vaza_do_bloco() -> None:
    original = standard.RetryQuotaChecker
    with pytest.raises(RuntimeError), bedrock.cota_como_sdk_js():
        assert standard.RetryQuotaChecker is not original
        raise RuntimeError
    assert standard.RetryQuotaChecker is original


def test_espera_do_p_retry_entre_63_e_126_segundos_por_camada() -> None:
    for _ in range(200):
        esperas = [espera_do_p_retry(n) for n in range(1, 7)]
        assert all(1000 * 2 ** (n - 1) <= e * 1000 <= 2000 * 2 ** (n - 1) for n, e in enumerate(esperas, start=1))
        assert 63 <= sum(esperas) <= 126
