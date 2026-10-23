"""Workflows do GitHub Actions alterados pela fundação (#209).

Não substituem a execução real no GitHub, mas pegam o que dá para pegar
localmente: YAML válido, gatilhos e a checagem de referência do
publish-grafana executada de verdade com bash.
"""

import base64
import json
import shutil
import subprocess
import time
import urllib.request
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


# Renovação do token do Verde (#316): o script Python embutido no workflow roda
# de verdade, com o AWS CLI e a Verde simulados. Tokens e ids inventados.
TOKEN_VELHO_ASSINATURA = "assinatura-velha-inventada"
TOKEN_NOVO = "token-novo-inventado"
DEPLOY_NOVO = "ecs-svc/novo"
DEPLOY_VELHO = "ecs-svc/velho"


def _script_da_renovacao() -> str:
    passos = _carregar("verificar-token-verde.yml")["jobs"]["verificar"]["steps"]
    run = next(p["run"] for p in passos if "python3 - <<'EOF'" in p.get("run", ""))
    return str(run.split("python3 - <<'EOF'\n", 1)[1].split("\nEOF", 1)[0])


def _token_que_vence_em(dias: float) -> str:
    carga = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + dias * 86400}).encode()).decode().rstrip("=")
    return f"cabecalho.{carga}.{TOKEN_VELHO_ASSINATURA}"


class _RespostaVerde:
    def __init__(self, corpo: dict[str, Any]) -> None:
        self.status = 200
        self._corpo = json.dumps(corpo).encode()

    def __enter__(self) -> "_RespostaVerde":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._corpo


def _renovar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    dias: float = 3,
    estabiliza: bool = True,
    deploys_depois: tuple[str, ...] = (DEPLOY_NOVO,),
    grava: bool = True,
) -> tuple[int, str, list[list[str]]]:
    """Roda o script de renovação; devolve o código de saída, a saída e os comandos `aws` chamados."""
    (tmp_path / "secret.json").write_text(
        json.dumps(
            {
                "VERDE_API_URL": "https://verde.invalido",
                "VERDE_JWT_TOKEN": _token_que_vence_em(dias),
                "VERDE_CLIENT_ID": "cliente-inventado",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for nome, valor in {"AMBIENTE": "prod", "AWS_REGION": "us-east-1", "ECS_CLUSTER": "maria-langgraph-pp", "ECS_SERVICE": "api"}.items():
        monkeypatch.setenv(nome, valor)

    def verde(req: urllib.request.Request, timeout: float = 0) -> _RespostaVerde:
        if req.full_url.endswith("/token/status"):
            return _RespostaVerde(
                {"dados": {"valido": True, "expirado": False, "revogado": False, "expiraEm": "2026-11-01T09:28:22-03:00"}}
            )
        assert req.full_url.endswith("/token/refresh")
        return _RespostaVerde({"token": TOKEN_NOVO, "expiraEm": "2026-11-30T09:28:22-03:00"})

    chamados: list[list[str]] = []

    def aws(args: list[str], check: bool = False, **_: Any) -> subprocess.CompletedProcess[str]:
        chamados.append(args)
        saida = ""
        if args[1:3] == ["secretsmanager", "put-secret-value"] and not grava:
            raise subprocess.CalledProcessError(254, args)
        if args[1:3] == ["ecs", "update-service"]:
            saida = json.dumps(
                {"service": {"deployments": [{"id": DEPLOY_NOVO, "status": "PRIMARY"}, {"id": DEPLOY_VELHO, "status": "ACTIVE"}]}}
            )
        elif args[1:3] == ["ecs", "wait"] and not estabiliza:
            raise subprocess.CalledProcessError(255, args)
        elif args[1:3] == ["ecs", "describe-services"]:
            deploys = [{"id": d, "status": "PRIMARY" if i == 0 else "ACTIVE"} for i, d in enumerate(deploys_depois)]
            saida = json.dumps({"services": [{"deployments": deploys, "runningCount": 1, "desiredCount": 1}]})
        return subprocess.CompletedProcess(args, 0, saida, "")

    monkeypatch.setattr(urllib.request, "urlopen", verde)
    monkeypatch.setattr(subprocess, "run", aws)
    codigo = 0
    try:
        exec(compile(_script_da_renovacao(), "verificar-token-verde.yml", "exec"), {"__name__": "__main__"})
    except SystemExit as fim:
        codigo = int(fim.code or 0)
    saida = capsys.readouterr().out
    assert TOKEN_NOVO not in saida and TOKEN_VELHO_ASSINATURA not in saida, "token no log"
    return codigo, saida, chamados


def _subcomandos(chamados: list[list[str]]) -> list[str]:
    return [" ".join(c[1:3]) for c in chamados]


def test_renovacao_espera_o_container_novo_subir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo, saida, chamados = _renovar(monkeypatch, tmp_path, capsys)
    assert codigo == 0, saida
    assert _subcomandos(chamados) == ["secretsmanager put-secret-value", "ecs update-service", "ecs wait", "ecs describe-services"]
    assert "container novo no ar" in saida


def test_renovacao_falha_se_o_servico_nao_estabiliza(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # O caso de 2026-10-22: o redeploy travou, e o container antigo seguiu com o token invalidado.
    codigo, saida, _ = _renovar(monkeypatch, tmp_path, capsys, estabiliza=False)
    assert codigo == 1
    assert "container novo não subiu" in saida
    assert "token INVALIDADO" in saida
    assert "não estabilizou" in saida


def test_renovacao_falha_se_sobra_o_deploy_antigo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo, saida, _ = _renovar(monkeypatch, tmp_path, capsys, deploys_depois=(DEPLOY_VELHO,))
    assert codigo == 1
    assert "container novo não subiu" in saida
    assert "deploy antigo no ar: True" in saida


def test_renovacao_aceita_deploy_mais_novo_que_o_dela(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Um push no meio cria um deploy depois da gravação do segredo: os containers dele leem o token novo.
    codigo, saida, _ = _renovar(monkeypatch, tmp_path, capsys, deploys_depois=("ecs-svc/de-um-push-no-meio",))
    assert codigo == 0, saida


def test_falha_ao_gravar_o_segredo_nao_imprime_o_segredo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Sem o try, o traceback do CalledProcessError imprimiria o comando, com o segredo dentro.
    codigo, saida, chamados = _renovar(monkeypatch, tmp_path, capsys, grava=False)
    assert codigo == 1
    assert "gravação no Secrets Manager falhou (código 254)" in saida
    assert _subcomandos(chamados) == ["secretsmanager put-secret-value"]


def test_token_saudavel_nao_pede_deploy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo, saida, chamados = _renovar(monkeypatch, tmp_path, capsys, dias=20)
    assert codigo == 0
    assert chamados == []
    assert "token saudável" in saida
