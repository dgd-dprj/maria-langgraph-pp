"""Linha de comando das versões dos fluxos (#542).

python -m maria.versionamento manifesto [--raiz src/maria]
python -m maria.versionamento verificar-pr --base base.json --head head.json --corpo corpo.md [--resumo arquivo]
python -m maria.versionamento listar <fluxo-ou-nome> [--ambiente release] [--limite 20]   (usa DATABASE_URL)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from maria.versionamento.manifesto import montar_manifesto
from maria.versionamento.meta import conferir_pr
from maria.versionamento.registro import listar_versoes


def _manifesto(args: argparse.Namespace) -> int:
    sys.stdout.write(json.dumps(montar_manifesto(Path(args.raiz) if args.raiz else None), sort_keys=True, ensure_ascii=False) + "\n")
    return 0


def _verificar_pr(args: argparse.Namespace) -> int:
    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    head = json.loads(Path(args.head).read_text(encoding="utf-8"))
    corpo = Path(args.corpo).read_text(encoding="utf-8") if Path(args.corpo).exists() else ""
    resultado = conferir_pr(base, head, corpo)
    sys.stdout.write(resultado.markdown)
    if args.resumo:
        with Path(args.resumo).open("a", encoding="utf-8") as saida:
            saida.write(resultado.markdown)
    if not resultado.ok:
        faltando = ", ".join(f"'## {t}'" for t in resultado.faltando)
        aviso = f"Este PR muda um fluxo e o corpo não tem a seção {faltando} preenchida (ver docs/padroes-pull-request.md)."
        sys.stdout.write(f"::error::{aviso}\n")
        return 1
    return 0


def _listar(args: argparse.Namespace) -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.stderr.write("DATABASE_URL não definida\n")
        return 2
    for v in asyncio.run(listar_versoes(url, args.fluxo, args.ambiente, args.limite)):
        sys.stdout.write(
            f"#{v['id']} {v['registrado_em']:%Y-%m-%d %H:%M} [{v['ambiente']}] {v['nome_fluxo']} {v['hash'][:8]} "
            f"solicitante={v['solicitante'] or '-'} autor={v['autor_commit'] or '-'} pr={v['pr_numero'] or '-'} "
            f"imagem={v['tag_imagem'] or '-'}\n    {v['resumo']}\n"
        )
        if args.detalhes:
            sys.stdout.write(json.dumps(v["alteracoes"], ensure_ascii=False, indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m maria.versionamento")
    sub = parser.add_subparsers(dest="comando", required=True)
    m = sub.add_parser("manifesto")
    m.add_argument("--raiz", help="pasta do pacote maria a analisar (padrão: a instalada)")
    m.set_defaults(funcao=_manifesto)
    v = sub.add_parser("verificar-pr")
    v.add_argument("--base", required=True)
    v.add_argument("--head", required=True)
    v.add_argument("--corpo", required=True)
    v.add_argument("--resumo", help="arquivo onde acrescentar o resumo em Markdown (GITHUB_STEP_SUMMARY)")
    v.set_defaults(funcao=_verificar_pr)
    li = sub.add_parser("listar")
    li.add_argument("fluxo")
    li.add_argument("--ambiente")
    li.add_argument("--limite", type=int, default=20)
    li.add_argument("--detalhes", action="store_true", help="mostra o antes e o depois de cada versão")
    li.set_defaults(funcao=_listar)
    args = parser.parse_args(argv)
    return int(args.funcao(args))


if __name__ == "__main__":
    raise SystemExit(main())
