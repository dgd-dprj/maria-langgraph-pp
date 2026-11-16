"""Terraform de São Paulo, produção (#509): service, segredos e roles da produção, ao lado do release.

Lê os `.tf` como texto (o CI não tem o state), como `tests/api/test_fluxo_em_teste.py` faz com o stack da Virgínia.
"""

from __future__ import annotations

import re
from pathlib import Path

SP = Path("infra/terraform-sp")
VIRGINIA = Path("infra/terraform")


def _texto(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8")


def _chaves_de_segredos(ecs: str) -> list[list[str]]:
    """As listas `for k in [...]` do bloco `secrets` de uma task definition."""
    return [re.findall(r'"([A-Z0-9_]+)"', lista) for lista in re.findall(r"for k in (\[[^\]]*\])", ecs)]


def test_a_producao_em_sp_roda_com_maria_ambiente_producao_fixo() -> None:
    """Só "release" exato liga os fluxos em teste (maria/fluxos/__init__.py): a produção nunca pode herdá-lo."""
    prod = _texto(SP / "prod.tf")
    valores = re.findall(r'\{\s*name\s*=\s*"MARIA_AMBIENTE"\s*,\s*value\s*=\s*([^}]+?)\s*\}', prod)
    assert valores == ['"producao"']


def test_o_service_de_producao_nasce_sem_tasks_e_sem_trocar_o_trafego() -> None:
    prod = _texto(SP / "prod.tf")
    padrao = re.search(r'variable "prod_desired_count"\s*\{[^}]*default\s*=\s*(\d+)', prod)
    assert padrao is not None
    assert padrao.group(1) == "0"
    assert 'name            = "api-prod-sp"' in prod


def test_a_producao_nao_usa_segredos_nem_roles_do_release() -> None:
    prod = _texto(SP / "prod.tf")
    release = [
        "aws_secretsmanager_secret.app.",
        "aws_secretsmanager_secret.email_nudecon.",
        "aws_iam_role.execution.",
        "aws_iam_role.task.",
        "aws_cloudwatch_log_group.api.",
        "aws_ecs_task_definition.api.",
    ]
    assert [r for r in release if r in prod] == []


def test_as_chaves_de_segredo_da_producao_sao_as_da_producao_da_virginia() -> None:
    """Uma chave faltando no segredo derruba a task ao subir; ficar igual à Virgínia evita surpresa no corte."""
    sp = _chaves_de_segredos(_texto(SP / "prod.tf"))
    virginia = _chaves_de_segredos(_texto(VIRGINIA / "ecs.tf"))
    assert sp == virginia
    assert len(sp) == 2


def test_a_esteira_pode_redeployar_e_ler_o_segredo_da_producao_em_sp() -> None:
    oidc = _texto(SP / "github-oidc.tf")
    assert "aws_ecs_service.api_prod.id" in oidc
    assert oidc.count("aws_secretsmanager_secret.app_prod.arn") == 2
