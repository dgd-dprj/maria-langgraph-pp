"""#412: o editor acusa os mesmos erros de tipo que o CI (decisão da Nicole, 2026-11-18).

O CI roda o mypy; o Pylance usa o pyright, que discorda em vários pontos. A configuração do VS Code no repositório
desliga a checagem de tipos do Pylance e recomenda a extensão do mypy. Este teste segura essa configuração, para ela
não se perder num ajuste de editor.
"""

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _jsonc(caminho: Path) -> dict[str, object]:
    """JSON com comentários de linha (o formato do VS Code)."""
    texto = re.sub(r"^\s*//.*$", "", caminho.read_text(encoding="utf-8"), flags=re.MULTILINE)
    dados: dict[str, object] = json.loads(texto)
    return dados


def test_pylance_sem_checagem_de_tipos_e_mypy_do_ambiente() -> None:
    config = _jsonc(RAIZ / ".vscode" / "settings.json")
    assert config["python.analysis.typeCheckingMode"] == "off"
    # O mypy do ambiente do projeto: a mesma versão e a mesma configuração que o CI usa.
    assert config["mypy-type-checker.importStrategy"] == "fromEnvironment"


def test_extensao_do_mypy_recomendada() -> None:
    recomendadas = _jsonc(RAIZ / ".vscode" / "extensions.json")["recommendations"]
    assert isinstance(recomendadas, list)
    assert "ms-python.mypy-type-checker" in recomendadas


def test_ci_continua_com_o_mypy() -> None:
    # O caminho escolhido não muda o CI: o mypy segue no workflow, e o pyright não entra.
    ci = (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "mypy" in ci
    assert "pyright" not in ci
