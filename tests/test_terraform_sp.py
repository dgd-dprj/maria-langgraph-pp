"""Terraform de São Paulo (#482): o ambiente da Maria e os modelos que a task pode chamar.

Lê os `.tf` como texto, como `tests/api/test_fluxo_em_teste.py` faz com o stack da Virgínia: o CI não
tem o state, e o que importa aqui é o que está declarado.
"""

from __future__ import annotations

import re
from pathlib import Path

SP = Path("infra/terraform-sp")
MINISTRAL_14B = "arn:aws:bedrock:sa-east-1::foundation-model/mistral.ministral-3-14b-instruct"


def _texto(arquivo: str) -> str:
    return (SP / arquivo).read_text(encoding="utf-8")


def test_o_ambiente_da_maria_vem_do_environment_e_nunca_de_um_valor_fixo() -> None:
    """Um stack de produção em São Paulo não pode herdar o "release" (plano de saúde e multi-fluxo ligados)."""
    ecs = _texto("ecs.tf")
    valores = re.findall(r'\{\s*name\s*=\s*"MARIA_AMBIENTE"\s*,\s*value\s*=\s*([^}]+?)\s*\}', ecs)
    assert valores == ["local.maria_ambiente"]


def test_so_o_environment_release_liga_os_fluxos_em_teste() -> None:
    """A mesma regra do código (`maria/fluxos/__init__.py`): só "release" exato; o resto é produção."""
    ecs = _texto("ecs.tf")
    expressao = re.search(r"maria_ambiente\s*=\s*(.+)", ecs)
    assert expressao is not None
    assert expressao.group(1).strip() == 'var.environment == "release" ? "release" : "producao"'


def test_a_task_pode_chamar_o_qwen_e_a_volta_atras_para_o_ministral_14b() -> None:
    variaveis = _texto("variables.tf")
    bloco = re.search(r'variable "bedrock_model_arns"\s*\{(.*?)\n\}', variaveis, re.S)
    assert bloco is not None
    arns = re.findall(r'"(arn:aws:bedrock:[^"]+)"', bloco.group(1))
    assert "arn:aws:bedrock:sa-east-1::foundation-model/qwen.*" in arns
    assert MINISTRAL_14B in arns
    # O 3B saiu na #472 ("mãe" virava "Outro"): não entra por engano junto com o 14B.
    assert not any("ministral-3-3b" in a or "ministral-3-8b" in a for a in arns)
