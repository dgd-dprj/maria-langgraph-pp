"""`scripts/conferir_token_verde.py` (issue #298), contra um Verde falso em memória (sem rede de verdade)."""

import base64
import json
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

from conferir_token_verde import ErroDeStatus, consultar_status, ler_status, main, problema_do_token

TOKEN = "eyJhbGciOiJSUzI1NiJ9.token-ficticio-para-teste.assinatura"
CLIENTE = "cliente-ficticio"


class VerdeFalso:
    """Responde `GET /autenticacao/token/status` com o que o teste mandar e registra tudo o que recebe."""

    def __init__(self) -> None:
        self.codigo = 200
        self.corpo: Any = {"dados": {"valido": True, "expirado": False, "revogado": False, "expiraEm": "2026-11-30"}}
        self.recebidos: list[tuple[str, str, dict[str, str]]] = []
        verde = self

        class Atendente(BaseHTTPRequestHandler):
            def _responder(self) -> None:
                verde.recebidos.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}))
                if self.command != "GET":  # a conferência é só leitura: qualquer outro método é defeito
                    self.send_response(500)
                    self.end_headers()
                    return
                corpo = json.dumps(verde.corpo).encode() if verde.corpo is not None else b"nao e json"
                self.send_response(verde.codigo)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(corpo)

            do_GET = do_POST = do_PUT = do_DELETE = _responder

            def log_message(self, *args: object) -> None:
                pass

        self.servidor = HTTPServer(("127.0.0.1", 0), Atendente)
        self.url = f"http://127.0.0.1:{self.servidor.server_address[1]}/api/integra"
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def metodos(self) -> list[str]:
        return [metodo for metodo, _, _ in self.recebidos]


@pytest.fixture
def verde() -> Iterator[VerdeFalso]:
    falso = VerdeFalso()
    yield falso
    falso.servidor.shutdown()
    falso.servidor.server_close()


def _segredo(tmp_path: Path, verde: VerdeFalso) -> Path:
    arquivo = tmp_path / "segredo.json"
    arquivo.write_text(
        json.dumps(
            {
                "VERDE_API_URL": verde.url,
                "VERDE_JWT_TOKEN": TOKEN,
                "VERDE_CLIENT_ID": CLIENTE,
                "DATABASE_URL": "postgresql://nao-deve-aparecer",
            }
        ),
        encoding="utf-8",
    )
    return arquivo


def _rodar(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    codigo = main(["--ambiente", "release", "--segredo", str(_segredo(tmp_path, verde))])
    saida = capsys.readouterr()
    return codigo, saida.out + saida.err


def test_token_aceito_passa(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str]) -> None:
    codigo, saida = _rodar(tmp_path, verde, capsys)
    assert codigo == 0
    assert "aceita o token" in saida
    assert "expiraEm=2026-11-30" in saida


def test_envia_bearer_e_client_id_no_get_de_status(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str]) -> None:
    _rodar(tmp_path, verde, capsys)
    [(metodo, caminho, cabecalhos)] = verde.recebidos
    assert (metodo, caminho) == ("GET", "/api/integra/autenticacao/token/status")
    assert cabecalhos["authorization"] == f"Bearer {TOKEN}"
    assert cabecalhos["x-client-id"] == CLIENTE


def test_401_falha_e_mostra_o_codigo_do_verde(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str]) -> None:
    verde.codigo, verde.corpo = 401, {"codigo": "NAO_AUTORIZADO", "mensagem": "texto longo que não precisa ir ao log"}
    codigo, saida = _rodar(tmp_path, verde, capsys)
    assert codigo == 1
    assert "HTTP 401" in saida
    assert "NAO_AUTORIZADO" in saida
    assert "texto longo" not in saida


def test_401_com_corpo_que_nao_e_json_tambem_falha(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str]) -> None:
    verde.codigo, verde.corpo = 401, None
    codigo, saida = _rodar(tmp_path, verde, capsys)
    assert codigo == 1
    assert "HTTP 401" in saida


@pytest.mark.parametrize(
    ("campos", "trecho"),
    [
        ({"valido": False, "expirado": False, "revogado": True}, "revogado"),
        ({"valido": False, "expirado": True, "revogado": False}, "expirou"),
        ({"expirado": True}, "expirou"),
        ({"valido": False}, "não é válido"),
    ],
)
def test_200_com_token_recusado_falha(
    tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str], campos: dict[str, Any], trecho: str
) -> None:
    verde.corpo = {"dados": campos}
    codigo, saida = _rodar(tmp_path, verde, capsys)
    assert codigo == 1
    assert trecho in saida


def test_aceita_a_resposta_plana_do_swagger(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str]) -> None:
    verde.corpo = {"valido": True, "expirado": False, "revogado": False}
    codigo, _ = _rodar(tmp_path, verde, capsys)
    assert codigo == 0


@pytest.mark.parametrize("corpo", [{}, {"dados": {}}, {"dados": {"outro": 1}}, {"dados": "texto"}, [], "texto", 7])
def test_200_sem_os_campos_esperados_falha(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str], corpo: Any) -> None:
    verde.corpo = corpo
    codigo, saida = _rodar(tmp_path, verde, capsys)
    assert codigo == 1
    assert "sem nenhum campo esperado" in saida


def test_200_que_nao_e_json_falha(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str]) -> None:
    verde.corpo = None
    codigo, saida = _rodar(tmp_path, verde, capsys)
    assert codigo == 1
    assert "sem nenhum campo esperado" in saida


def test_nunca_chama_o_refresh_nem_outro_metodo(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str]) -> None:
    # Perto de vencer e já expirado: os casos em que o workflow agendado renovaria.
    for corpo in (
        {"dados": {"valido": True, "expirado": False, "revogado": False, "expiraEm": "2026-10-23"}},
        {"dados": {"valido": False, "expirado": True, "revogado": False}},
    ):
        verde.corpo = corpo
        _rodar(tmp_path, verde, capsys)
    assert verde.metodos() == ["GET", "GET"]
    assert all(caminho.endswith("/autenticacao/token/status") for _, caminho, _ in verde.recebidos)


@pytest.mark.parametrize(
    ("codigo", "corpo"),
    [
        (200, {"dados": {"valido": True, "expirado": False, "revogado": False}}),
        (200, {"dados": {"valido": False, "expirado": False, "revogado": True}}),
        (200, {"dados": {"valido": False, "expirado": True, "revogado": False}}),
        (200, {"sem": "campos"}),
        (401, {"codigo": "NAO_AUTORIZADO"}),
        (500, None),
    ],
)
def test_a_saida_nunca_traz_o_token_nem_o_resto_do_segredo(
    tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str], codigo: int, corpo: Any
) -> None:
    verde.codigo, verde.corpo = codigo, corpo
    _, saida = _rodar(tmp_path, verde, capsys)
    assert saida
    assert TOKEN not in saida
    assert "token-ficticio" not in saida
    assert "nao-deve-aparecer" not in saida


def test_verde_fora_do_ar_falha_sem_vazar_o_endereco(tmp_path: Path, verde: VerdeFalso, capsys: pytest.CaptureFixture[str]) -> None:
    arquivo = _segredo(tmp_path, verde)
    verde.servidor.shutdown()
    verde.servidor.server_close()
    codigo = main(["--ambiente", "release", "--segredo", str(arquivo)])
    saida = capsys.readouterr().out
    assert codigo == 1
    assert "sem resposta do Verde" in saida
    assert verde.url not in saida
    assert TOKEN not in saida


@pytest.mark.parametrize("conteudo", ["isto não é json", "{}", '{"VERDE_API_URL": "http://x"}', "[]"])
def test_segredo_ilegivel_ou_incompleto_falha_sem_repetir_o_conteudo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], conteudo: str
) -> None:
    arquivo = tmp_path / "segredo.json"
    arquivo.write_text(conteudo, encoding="utf-8")
    codigo = main(["--ambiente", "release", "--segredo", str(arquivo)])
    saida = capsys.readouterr().out
    assert codigo == 1
    assert "segredo ilegível ou sem" in saida
    assert conteudo not in saida


def test_segredo_inexistente_falha(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--ambiente", "release", "--segredo", str(tmp_path / "nao-existe.json")]) == 1
    assert "segredo ilegível" in capsys.readouterr().out


def test_funcoes_de_status_usadas_pelo_workflow_agendado(verde: VerdeFalso) -> None:
    codigo, corpo = consultar_status(verde.url, TOKEN, CLIENTE)
    status = ler_status(codigo, corpo)
    assert problema_do_token(status) is None
    with pytest.raises(ErroDeStatus, match="HTTP 403"):
        ler_status(403, {"dados": {"revogado": False}})


# --- O workflow agendado, com a consulta de status vinda do script (renovação intacta) ---

RAIZ = Path(__file__).resolve().parents[2]


def _codigo_do_workflow_agendado() -> str:
    """O Python inline do passo "Checar e renovar", como o GitHub o entrega ao `python3 -`."""
    passos = yaml.safe_load((RAIZ / ".github" / "workflows" / "verificar-token-verde.yml").read_text(encoding="utf-8"))["jobs"][
        "verificar"
    ]["steps"]
    shell: str = next(p["run"] for p in passos if "Checar e renovar" in p.get("name", ""))
    return shell.split("python3 - <<'EOF'\n", 1)[1].rsplit("\nEOF", 1)[0]


def _jwt_que_vence_em(dias: float) -> str:
    corpo = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + dias * 86400}).encode()).decode().rstrip("=")
    return f"cabecalho.{corpo}.assinatura"


def _rodar_workflow_agendado(tmp_path: Path, verde: VerdeFalso, token: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "scripts").symlink_to(RAIZ / "scripts")
    (tmp_path / "secret.json").write_text(
        json.dumps({"VERDE_API_URL": verde.url, "VERDE_JWT_TOKEN": token, "VERDE_CLIENT_ID": CLIENTE}), encoding="utf-8"
    )
    ambiente = {"AMBIENTE": "release", "AWS_REGION": "us-east-1", "ECS_CLUSTER": "c", "ECS_SERVICE": "s", "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [sys.executable, "-I", "-c", _codigo_do_workflow_agendado()], cwd=tmp_path, env=ambiente, capture_output=True, text=True, timeout=60
    )


@pytest.mark.skipif(sys.platform == "win32", reason="o teste usa link simbólico")
def test_workflow_agendado_token_saudavel_nao_renova(tmp_path: Path, verde: VerdeFalso) -> None:
    # `-I` isola o interpretador, então o `sys.path.insert(0, "scripts")` do próprio workflow é o que importa o script.
    resultado = _rodar_workflow_agendado(tmp_path, verde, _jwt_que_vence_em(60))
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert "saudável" in resultado.stdout
    assert verde.metodos() == ["GET"]


@pytest.mark.skipif(sys.platform == "win32", reason="o teste usa link simbólico")
def test_workflow_agendado_token_revogado_falha_sem_renovar(tmp_path: Path, verde: VerdeFalso) -> None:
    verde.corpo = {"dados": {"valido": False, "expirado": False, "revogado": True}}
    resultado = _rodar_workflow_agendado(tmp_path, verde, _jwt_que_vence_em(60))
    assert resultado.returncode == 1
    assert "revogado" in resultado.stdout
    assert verde.metodos() == ["GET"]


@pytest.mark.skipif(sys.platform == "win32", reason="o teste usa link simbólico")
def test_workflow_agendado_401_falha_sem_mostrar_o_corpo(tmp_path: Path, verde: VerdeFalso) -> None:
    verde.codigo, verde.corpo = 401, {"codigo": "NAO_AUTORIZADO", "mensagem": "texto que não vai ao log"}
    resultado = _rodar_workflow_agendado(tmp_path, verde, _jwt_que_vence_em(60))
    assert resultado.returncode == 1
    assert "HTTP 401" in resultado.stdout
    assert "texto que não vai ao log" not in resultado.stdout
