"""Linha de comando (#542): manifesto e verificação do PR."""

import json
from pathlib import Path

import pytest

from maria.versionamento.__main__ import main
from tests.versionamento.conftest import GRAFO, escrever


def _manifesto(raiz: Path, destino: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["manifesto", "--raiz", str(raiz)]) == 0
    destino.write_text(capsys.readouterr().out, encoding="utf-8")


def test_verificar_pr_falha_sem_secoes_e_passa_com_elas(raiz: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, head, corpo, resumo = tmp_path / "base.json", tmp_path / "head.json", tmp_path / "corpo.md", tmp_path / "resumo.md"
    _manifesto(raiz, base, capsys)
    escrever(raiz, "fluxos/exemplo/graph.py", GRAFO.replace("Qual o seu nome?", "Qual o nome completo?"))
    _manifesto(raiz, head, capsys)
    assert json.loads(base.read_text())["fluxos"] and base.read_text() != head.read_text()

    corpo.write_text("## Solicitado por\n<!-- nome -->\n", encoding="utf-8")
    argumentos = ["verificar-pr", "--base", str(base), "--head", str(head), "--corpo", str(corpo), "--resumo", str(resumo)]
    assert main(argumentos) == 1
    saida = capsys.readouterr().out
    assert "::error::" in saida and "Solicitado por" in saida and "Resumo da mudança" in saida
    assert "exemplo" in resumo.read_text()

    corpo.write_text("## Solicitado por\nNicole\n\n## Resumo da mudança\nNome completo.\n", encoding="utf-8")
    assert main(argumentos) == 0
    assert "::error::" not in capsys.readouterr().out
