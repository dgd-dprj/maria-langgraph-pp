"""Monta o JSON de metadados da versão que vai dentro da imagem (#542).

Uso (no deploy, antes do `docker build`; precisa do `gh` autenticado por GH_TOKEN):

    PYTHONPATH=src python3 scripts/montar_versao_meta.py --repo dgd-dprj/maria-langgraph-pp --sha "$GITHUB_SHA" \
        --tag "sha-$GITHUB_SHA" --autor "$GITHUB_ACTOR" > versao-meta.json

O deploy acontece num push em `staging` ou `main`, que é o merge de um PR de promoção (develop→staging, staging→main).
O script acha esse PR, lista os commits dele, e para cada commit acha o PR de origem (os PRs para a `develop`, onde
mora o "Solicitado por" e o "Resumo da mudança"). Para cada um guarda quem pediu, o resumo, quem aprovou e os arquivos
mexidos, resumidos em áreas (o JSON vai como argumento do `docker build`, que tem limite de tamanho); a Maria atribui
cada fluxo aos PRs que mexeram na pasta dele. Falha ao consultar o GitHub não impede o
deploy: o JSON sai só com o commit e a tag, e o aviso vai para o stderr.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from maria.versionamento.meta import entrada_do_pr

Consulta = Callable[[str], Any]
# `GET pulls/{n}/commits` devolve no máximo 250 commits.
LIMITE_DE_COMMITS_DA_API = 250


def _gh(caminho: str) -> Any:
    saida = subprocess.run(["gh", "api", "--paginate", "--slurp", caminho], check=True, capture_output=True, text=True).stdout
    paginas = json.loads(saida)
    # --slurp devolve uma lista de páginas; cada página é lista (coleções) ou objeto.
    if paginas and all(isinstance(p, list) for p in paginas):
        return [item for pagina in paginas for item in pagina]
    return paginas[0] if len(paginas) == 1 else paginas


def prs_do_deploy(repo: str, sha: str, consulta: Consulta) -> list[dict[str, Any]]:
    promocao = [pr for pr in consulta(f"repos/{repo}/commits/{sha}/pulls") if pr.get("merged_at")]
    if not promocao:
        return []
    numero_promocao = promocao[0]["number"]
    vistos: dict[int, dict[str, Any]] = {}
    commits = consulta(f"repos/{repo}/pulls/{numero_promocao}/commits")
    if len(commits) >= LIMITE_DE_COMMITS_DA_API:
        sys.stderr.write("::warning::A promoção tem 250 commits ou mais (limite da API): alguns PRs podem ficar sem solicitante\n")
    for commit in commits:
        for pr in consulta(f"repos/{repo}/commits/{commit['sha']}/pulls"):
            if pr["number"] == numero_promocao or pr.get("base", {}).get("ref") != "develop" or not pr.get("merged_at"):
                continue
            vistos.setdefault(pr["number"], pr)
    entradas: list[dict[str, Any]] = []
    for numero, pr in sorted(vistos.items()):
        arquivos = [a["filename"] for a in consulta(f"repos/{repo}/pulls/{numero}/files")]
        revisoes = consulta(f"repos/{repo}/pulls/{numero}/reviews")
        aprovadores = [r["user"]["login"] for r in revisoes if r.get("state") == "APPROVED" and r.get("user")]
        entradas.append(entrada_do_pr(pr, arquivos, aprovadores))
    return entradas


def montar_meta(repo: str, sha: str, tag: str, autor: str, consulta: Consulta) -> dict[str, Any]:
    meta: dict[str, Any] = {"commit_sha": sha, "tag_imagem": tag, "executado_por": autor, "prs": []}
    try:
        meta["prs"] = prs_do_deploy(repo, sha, consulta)
    except Exception as erro:
        sys.stderr.write(f"::warning::Não consegui listar os PRs do deploy; a versão sai só com o commit e a tag ({erro})\n")
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--autor", default="")
    args = parser.parse_args(argv)
    sys.stdout.write(json.dumps(montar_meta(args.repo, args.sha, args.tag, args.autor, _gh), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
