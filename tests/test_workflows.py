"""Workflows do GitHub Actions alterados pela fundação (#209).

Não substituem a execução real no GitHub, mas pegam o que dá para pegar
localmente: YAML válido, gatilhos e a checagem de referência do
publish-grafana executada de verdade com bash.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"


def _carregar(nome: str) -> dict[Any, Any]:
    dados = yaml.safe_load((WORKFLOWS / nome).read_text(encoding="utf-8"))
    assert isinstance(dados, dict)
    return dados


def _gatilhos(workflow: dict[Any, Any]) -> dict[str, Any]:
    # O PyYAML lê a chave `on:` como o booleano True (YAML 1.1).
    gatilhos = workflow.get("on", workflow.get(True))
    assert isinstance(gatilhos, dict)
    return gatilhos


@pytest.mark.parametrize("nome", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_yaml_valido(nome: str) -> None:
    _carregar(nome)


def test_ci_dispara_em_pr_para_develop_e_main() -> None:
    # Os gatilhos de antes da migração voltaram no corte (#268); `migration` saiu
    # depois do merge da migration em develop (PR #267).
    assert _gatilhos(_carregar("ci.yml")) == {"pull_request": {"branches": ["develop", "main"]}}


def test_ci_mantem_os_jobs_que_os_rulesets_exigem() -> None:
    # `test` e `imagem` são checks obrigatórios nos rulesets de develop e main (#214).
    # Um job renomeado deixa o check obrigatório pendente para sempre, e nenhum PR entra.
    assert {"test", "imagem"} <= set(_carregar("ci.yml")["jobs"])


def test_ci_roda_as_duas_suites_e_postgres_16_provisorio() -> None:
    job = _carregar("ci.yml")["jobs"]["test"]
    assert job["services"]["postgres"]["image"] == "pgvector/pgvector:pg16"
    comandos = [passo.get("run", "") for passo in job["steps"]]
    assert 'uv run pytest -m "not postgres and not integracao"' in comandos
    assert "uv run pytest -m postgres" in comandos


def test_ci_constroi_a_imagem_e_confere_o_health() -> None:
    passos = _carregar("ci.yml")["jobs"]["imagem"]["steps"]
    comandos = "\n".join(passo.get("run", "") for passo in passos)
    assert "docker build" in comandos
    assert "/health" in comandos


def test_nenhum_workflow_usa_node_para_a_aplicacao() -> None:
    for nome in ("ci.yml", "deploy-prod.yml", "deploy-release.yml"):
        texto = (WORKFLOWS / nome).read_text(encoding="utf-8")
        assert "pnpm" not in texto
        assert "setup-node" not in texto


def _passo_de_referencia() -> dict[str, Any]:
    passos = _carregar("publish-grafana.yml")["jobs"]["publicar"]["steps"]
    primeiro = passos[0]
    assert isinstance(primeiro, dict)
    return primeiro


def test_checagem_de_referencia_e_o_primeiro_passo_do_publish_grafana() -> None:
    assert _passo_de_referencia()["name"] == "Recusar referência fora de develop/main"


@pytest.mark.skipif(shutil.which("bash") is None, reason="precisa de bash")
@pytest.mark.parametrize(
    ("ref", "permitido"),
    [
        ("refs/heads/develop", True),
        ("refs/heads/main", True),
        ("refs/heads/migration", False),
        ("refs/heads/migration-fundacao", False),
        ("refs/heads/developer", False),
        ("refs/tags/v1.0.0", False),
    ],
)
def test_checagem_de_referencia_do_publish_grafana(ref: str, permitido: bool) -> None:
    script = _passo_de_referencia()["run"]
    resultado = subprocess.run(["bash", "-c", script], env={"GITHUB_REF": ref, "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert (resultado.returncode == 0) is permitido, resultado.stdout + resultado.stderr


# --- Conferência do token do Verde depois do deploy (#298) ---


def _passos(nome: str, job: str) -> list[dict[str, Any]]:
    passos = _carregar(nome)["jobs"][job]["steps"]
    assert isinstance(passos, list)
    return passos


@pytest.mark.parametrize(("nome", "ambiente"), [("deploy-release.yml", "release"), ("deploy-prod.yml", "prod")])
def test_deploy_confere_o_token_do_verde_depois_do_services_stable(nome: str, ambiente: str) -> None:
    passos = _passos(nome, "deploy")
    espera = next(i for i, p in enumerate(passos) if "services-stable" in p.get("run", ""))
    conferencia = passos[espera + 1]
    assert conferencia["env"] == {"AMBIENTE": ambiente}
    assert "scripts/conferir_token_verde.py" in conferencia["run"]
    assert "maria-langgraph-pp-${AMBIENTE}/app" in conferencia["run"]


@pytest.mark.parametrize("nome", ["deploy-release.yml", "deploy-prod.yml"])
def test_conferencia_do_deploy_e_so_leitura(nome: str) -> None:
    # A renovação invalida o token antigo na hora e tem um dono só (verificar-token-verde.yml).
    texto = "\n".join(p.get("run", "") for p in _passos(nome, "deploy")).lower()
    assert "refresh" not in texto
    assert "put-secret-value" not in texto


def test_verificar_token_verde_usa_o_mesmo_script_da_conferencia() -> None:
    passos = _passos("verificar-token-verde.yml", "verificar")
    assert passos[0]["uses"].startswith("actions/checkout@")  # o script mora no repositório
    renovacao = next(p for p in passos if "Checar e renovar" in p.get("name", ""))["run"]
    assert "from conferir_token_verde import" in renovacao
    assert '"/autenticacao/token/status"' not in renovacao  # a consulta de status saiu do corpo inline
