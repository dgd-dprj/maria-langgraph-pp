"""`scripts/montar_versao_meta.py` (#542), com uma API do GitHub falsa em memória."""

import json
from typing import Any

import pytest

from montar_versao_meta import main, montar_meta, prs_do_deploy

REPO = "dgd-dprj/maria-langgraph-pp"
CORPO = "## Solicitado por\nNicole\n\n## Resumo da mudança\nPede o nome completo.\n\nCloses #5\n"


def _pr(numero: int, base: str = "develop", corpo: str = CORPO, merged: bool = True) -> dict[str, Any]:
    return {
        "number": numero,
        "title": f"PR {numero}",
        "user": {"login": "dev"},
        "body": corpo,
        "base": {"ref": base},
        "merged_at": "2026-11-23T12:00:00Z" if merged else None,
    }


RESPOSTAS: dict[str, Any] = {
    f"repos/{REPO}/commits/deploy/pulls": [_pr(100, base="staging")],
    f"repos/{REPO}/pulls/100/commits": [{"sha": "c1"}, {"sha": "c2"}, {"sha": "c3"}],
    f"repos/{REPO}/commits/c1/pulls": [_pr(10)],
    f"repos/{REPO}/commits/c2/pulls": [_pr(10)],  # dois commits do mesmo PR
    f"repos/{REPO}/commits/c3/pulls": [_pr(11, corpo="sem seções"), _pr(90, base="staging")],  # a promoção anterior fica de fora
    f"repos/{REPO}/pulls/10/files": [{"filename": "src/maria/fluxos/pessoa_presa/graph.py"}],
    f"repos/{REPO}/pulls/11/files": [{"filename": "README.md"}],
    f"repos/{REPO}/pulls/10/reviews": [{"state": "APPROVED", "user": {"login": "Ana"}}, {"state": "COMMENTED", "user": {"login": "Bia"}}],
    f"repos/{REPO}/pulls/11/reviews": [],
}


def consulta(caminho: str) -> Any:
    return RESPOSTAS[caminho]


def test_junta_os_prs_da_promocao_sem_repetir_nem_pegar_promocao() -> None:
    prs = prs_do_deploy(REPO, "deploy", consulta)
    assert [p["numero"] for p in prs] == [10, 11]
    assert prs[0]["solicitante"] == "Nicole" and prs[0]["aprovado_por"] == ["Ana"] and prs[0]["issue_origem"] == 5
    assert prs[0]["areas"] == ["fluxo:pessoa_presa"]
    assert prs[1]["solicitante"] == "" and prs[1]["resumo"] == ""


def test_commit_sem_pr_de_promocao_devolve_lista_vazia() -> None:
    assert prs_do_deploy(REPO, "x", lambda _c: []) == []


def test_meta_leva_commit_tag_e_autor() -> None:
    meta = montar_meta(REPO, "deploy", "sha-deploy", "icaro", consulta)
    assert (meta["commit_sha"], meta["tag_imagem"], meta["executado_por"]) == ("deploy", "sha-deploy", "icaro")
    assert [p["numero"] for p in meta["prs"]] == [10, 11]


def test_falha_na_api_nao_impede_o_deploy(capsys: pytest.CaptureFixture[str]) -> None:
    def quebra(_caminho: str) -> Any:
        raise RuntimeError("api fora do ar")

    meta = montar_meta(REPO, "deploy", "sha-deploy", "icaro", quebra)
    assert meta["prs"] == [] and meta["commit_sha"] == "deploy"
    assert "::warning::" in capsys.readouterr().err


def test_main_imprime_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("montar_versao_meta._gh", consulta)
    assert main(["--repo", REPO, "--sha", "deploy", "--tag", "sha-deploy"]) == 0
    assert json.loads(capsys.readouterr().out)["prs"][0]["numero"] == 10


def test_promocao_com_250_commits_avisa_do_limite_da_api(capsys: pytest.CaptureFixture[str]) -> None:
    respostas = {**RESPOSTAS, f"repos/{REPO}/pulls/100/commits": [{"sha": "c1"}] * 250}
    prs_do_deploy(REPO, "deploy", lambda caminho: respostas[caminho])
    assert "250 commits" in capsys.readouterr().err
