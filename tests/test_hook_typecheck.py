"""Hook `.claude/hooks/typecheck-after-edit.mjs` (#209).

Dispara com `.py` e ignora as demais extensões. Para não depender do mypy
nem do projeto, o hook roda com `cwd` numa pasta vazia: se ele tentar rodar o
typecheck, `uv run mypy` falha ali e o hook sai com 2; se ele ignorar o
arquivo, sai com 0 sem executar nada.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / ".claude" / "hooks" / "typecheck-after-edit.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="o hook é um script Node")


def _rodar_hook(arquivo: str, cwd: Path) -> int:
    entrada = json.dumps({"tool_input": {"file_path": arquivo}, "cwd": str(cwd)})
    return subprocess.run(["node", str(HOOK)], input=entrada, capture_output=True, text=True, timeout=120).returncode


@pytest.mark.parametrize("arquivo", ["src/maria/app.ts", "README.md", "pyproject.toml", "infra/grafana/x.json", "script.pyc"])
def test_ignora_o_que_nao_e_py(arquivo: str, tmp_path: Path) -> None:
    assert _rodar_hook(arquivo, tmp_path) == 0


def test_dispara_o_typecheck_para_py(tmp_path: Path) -> None:
    assert _rodar_hook("src/maria/app.py", tmp_path) == 2


def test_entrada_invalida_nao_bloqueia(tmp_path: Path) -> None:
    resultado = subprocess.run(["node", str(HOOK)], input="não é json", capture_output=True, text=True, timeout=60)
    assert resultado.returncode == 0
