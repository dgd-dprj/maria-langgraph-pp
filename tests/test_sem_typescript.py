"""Nenhum arquivo TypeScript ou JavaScript fora da lista MANTER (#268).

A aplicação é Python desde a migração (#208). Um merge mal resolvido pode trazer
arquivos de volta **sem conflito nenhum**: foi o que aconteceu ao mergear develop
na branch do corte, em 2026-10-20. Quatro `.ts` que develop criou depois da base
da `migration` (`tiposTykhe.ts`, `respostaSimNao.ts` e dois testes) entravam no
merge já preparados para o commit, sem que o git avisasse. Este teste é o que
impede o "nenhum arquivo TypeScript" de virar falso em silêncio.

Varre o disco, e não só o que o git rastreia: um arquivo ainda não adicionado
também conta. Se um arquivo novo precisar ficar, ele entra em MANTER com o motivo.
"""

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

EXTENSOES = {".ts", ".mts", ".cts", ".tsx", ".js", ".mjs", ".cjs", ".jsx"}
NOMES = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
IGNORAR = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}

MANTER = {
    # Hooks do Claude Code: continuam em Node, por decisão da fundação (#209).
    ".claude/hooks/block-secrets.mjs": "hook do Claude Code",
    ".claude/hooks/typecheck-after-edit.mjs": "hook do Claude Code",
    # Evidência da tradução: executores e sondas que rodaram contra develop, guardados
    # junto das respostas que gravaram. Não rodam na suíte.
    "tests/fixtures/contrato/conferencia-api-pr1/executor-develop.mts": "executor da conferência do api, PR 1",
    "tests/fixtures/contrato/conferencia-api-pr2/executor-develop.mts": "executor da conferência do api, PR 2",
    "tests/fixtures/contrato/serializacao-fastify.mts": "sonda da serialização do Fastify",
    "tests/fixtures/ia/caracterizacao-ia.mts": "caracterização das chamadas de IA de develop",
    "tests/fixtures/js/numeros-js.mts": "sonda da semântica de números do JS",
    "tests/fixtures/scripts/extrair_seed.mjs": "extração dos 74 fluxos planejados",
    # O seed de develop @ 1157a6d, byte a byte: o teste confere o id do blob git.
    "tests/fixtures/scripts/seedFluxosPlanejados-1157a6d.ts": "seed original, conferido pelo id do blob",
}


def _javascript_no_disco() -> set[str]:
    achados: set[str] = set()
    for caminho in RAIZ.rglob("*"):
        relativo = caminho.relative_to(RAIZ)
        if any(parte in IGNORAR for parte in relativo.parts) or not caminho.is_file():
            continue
        nome = caminho.name
        if caminho.suffix in EXTENSOES or nome in NOMES or (nome.startswith("tsconfig") and nome.endswith(".json")):
            achados.add(relativo.as_posix())
    return achados


def test_nenhum_typescript_ou_javascript_fora_da_lista_manter() -> None:
    fora = sorted(_javascript_no_disco() - set(MANTER))
    assert not fora, (
        "arquivos TypeScript/JavaScript fora de MANTER (merge mal resolvido? "
        f"se precisam ficar, entram em MANTER com o motivo): {fora}"
    )


def test_cada_item_de_manter_existe() -> None:
    # A lista não pode guardar exceções para arquivos que já saíram.
    faltando = sorted(caminho for caminho in MANTER if not (RAIZ / caminho).is_file())
    assert not faltando, f"itens de MANTER que não existem mais: {faltando}"
