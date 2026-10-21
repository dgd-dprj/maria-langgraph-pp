"""`scripts/logs-prod.sh`: as checagens antes do laço (spec 08, D-3 e seção 9.1).

Cada teste roda o script com um PATH controlado: uma pasta só com os executáveis falsos do
caso. A ordem das checagens é node, npx, aws e o download do pino-pretty. O laço em si não é
testado (ele não termina e depende da AWS).

Precisa de um `sh` de verdade: no CI (Linux) roda; no Windows, é pulado.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "logs-prod.sh"
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(sys.platform == "win32" or SH is None, reason="precisa de um sh POSIX (roda no CI)")


def _rodar(tmp_path: Path, executaveis: dict[str, int]) -> subprocess.CompletedProcess[str]:
    """Roda o script com PATH só com `executaveis` (nome → código de saída do falso)."""
    pasta = tmp_path / "bin"
    pasta.mkdir()
    for nome, codigo in executaveis.items():
        falso = pasta / nome
        falso.write_text(f"#!{SH}\nexit {codigo}\n", encoding="utf-8")
        falso.chmod(0o755)
    assert SH is not None
    return subprocess.run([SH, str(SCRIPT)], env={"PATH": str(pasta)}, capture_output=True, text=True, timeout=30, check=False)


def test_sem_node(tmp_path: Path) -> None:
    r = _rodar(tmp_path, {})
    assert r.returncode == 1
    assert r.stderr.startswith("logs-prod.sh: precisa do Node.js")


def test_sem_npx(tmp_path: Path) -> None:
    r = _rodar(tmp_path, {"node": 0})
    assert r.returncode == 1
    assert r.stderr.startswith("logs-prod.sh: precisa do npx")


def test_sem_aws(tmp_path: Path) -> None:
    r = _rodar(tmp_path, {"node": 0, "npx": 0})
    assert r.returncode == 1
    assert r.stderr.startswith("logs-prod.sh: precisa do AWS CLI v2")


def test_sem_rede_para_baixar_o_pino_pretty(tmp_path: Path) -> None:
    r = _rodar(tmp_path, {"node": 0, "npx": 1, "aws": 0})
    assert r.returncode == 1
    assert r.stderr.startswith("logs-prod.sh: não consegui obter o pino-pretty@13.1.3 pelo npx")
    assert "conexão com a internet" in r.stderr


def test_nenhuma_mensagem_de_comando_nao_encontrado(tmp_path: Path) -> None:
    r = _rodar(tmp_path, {})
    assert "not found" not in r.stderr
    assert "não encontrado" not in r.stderr
