"""`scripts/avisar_token_verde.py` (issue #571), contra uma função de e-mail falsa em memória (sem rede de verdade)."""

import json
import threading
from collections.abc import Iterator
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from avisar_token_verde import main, montar_aviso

HOJE = date(2026, 11, 27)
EXECUCAO = "https://github.com/dgd-dprj/maria-langgraph-pp/actions/runs/1"
CHAVE = "chave-ficticia-do-aviso"


class EmailFalso:
    def __init__(self) -> None:
        self.codigo = 200
        self.recebidos: list[tuple[str, dict[str, Any]]] = []
        falso = self

        class Manipulador(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                falso.recebidos.append((self.headers.get("Authorization", ""), corpo))
                self.send_response(falso.codigo)
                self.end_headers()

            def log_message(self, *_: object) -> None:
                return None

        self.servidor = HTTPServer(("127.0.0.1", 0), Manipulador)
        self.url = f"http://127.0.0.1:{self.servidor.server_port}/"
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()


@pytest.fixture
def email() -> Iterator[EmailFalso]:
    falso = EmailFalso()
    yield falso
    falso.servidor.shutdown()


def _env(email: EmailFalso, status: str = "success") -> dict[str, str]:
    return {
        "AMBIENTE": "prod",
        "STATUS_DO_JOB": status,
        "URL_DA_EXECUCAO": EXECUCAO,
        "EMAIL_AVISO_URL": email.url,
        "EMAIL_AVISO_API_KEY": CHAVE,
    }


def test_renovacao_gera_o_aviso_com_a_nova_expiracao() -> None:
    corpo = montar_aviso("prod", "success", "redeploy do ECS", {"expiraEm": "2026-12-27"}, EXECUCAO, HOJE)
    assert corpo is not None
    assert corpo["protocolo"] == "TOKEN-VERDE-PROD-RENOVADO-20261127"
    assert corpo["aviso"]["assunto"] == "Token do Verde renovado (Produção (SP))"
    assert corpo["dados"] == {
        "Ambiente": "Produção (SP)",
        "Resultado": "Token renovado",
        "Nova expiração": "2026-12-27",
        "Execução": EXECUCAO,
    }


def test_falha_gera_o_aviso_com_a_etapa() -> None:
    corpo = montar_aviso("release", "failure", "gravação do token novo no Secrets Manager", None, EXECUCAO, HOJE)
    assert corpo is not None
    assert corpo["protocolo"] == "TOKEN-VERDE-RELEASE-FALHA-20261127"
    assert corpo["dados"]["Etapa"] == "gravação do token novo no Secrets Manager"
    assert "Token renovado" not in corpo["dados"]


def test_falha_depois_da_renovacao_avisa_que_o_token_ja_foi_trocado() -> None:
    corpo = montar_aviso("prod", "failure", "espera do serviço estabilizar", {"expiraEm": "2026-12-27"}, EXECUCAO, HOJE)
    assert corpo is not None
    assert corpo["dados"]["Token renovado"].startswith("sim")
    assert "foi renovado, mas" in corpo["aviso"]["texto"]


def test_token_saudavel_nao_avisa() -> None:
    assert montar_aviso("prod", "success", "", None, EXECUCAO, HOJE) is None


def test_falha_sem_etapa_conhecida_diz_que_foi_na_leitura_do_segredo() -> None:
    corpo = montar_aviso("prod", "failure", "", None, EXECUCAO, HOJE)
    assert corpo is not None and corpo["dados"]["Etapa"] == "leitura do segredo"


def test_envia_com_a_chave_e_sem_o_token(tmp_path: Path, email: EmailFalso, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "renovado.json").write_text(json.dumps({"expiraEm": "2026-12-27"}), encoding="utf-8")
    assert main(_env(email), tmp_path) == 0
    assert len(email.recebidos) == 1
    autorizacao, corpo = email.recebidos[0]
    assert autorizacao == f"Bearer {CHAVE}"
    assert set(corpo) == {"protocolo", "dados", "aviso"}
    assert CHAVE not in capsys.readouterr().out
    assert CHAVE not in json.dumps(corpo)


def test_sem_renovacao_e_sem_falha_nao_chama_a_funcao(tmp_path: Path, email: EmailFalso) -> None:
    assert main(_env(email), tmp_path) == 0
    assert email.recebidos == []


def test_falha_ao_enviar_sai_com_codigo_1_sem_expor_a_chave(tmp_path: Path, email: EmailFalso, capsys: pytest.CaptureFixture[str]) -> None:
    email.codigo = 400
    (tmp_path / "etapa.txt").write_text("redeploy do ECS", encoding="utf-8")
    assert main(_env(email, "failure"), tmp_path) == 1
    saida = capsys.readouterr().out
    assert "HTTP 400" in saida and CHAVE not in saida


def test_sem_os_secrets_nao_envia_e_avisa_no_log(tmp_path: Path, email: EmailFalso, capsys: pytest.CaptureFixture[str]) -> None:
    env = {**_env(email, "failure"), "EMAIL_AVISO_URL": "", "EMAIL_AVISO_API_KEY": ""}
    assert main(env, tmp_path) == 1
    assert "ausentes" in capsys.readouterr().out
    assert email.recebidos == []
