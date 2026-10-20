"""A documentação descreve o repositório como ele é (spec 09, seção 6, itens 1 e 2).

1. **Links e caminhos:** todo link relativo dos documentos aponta para um arquivo que existe, e
   todo caminho citado em código com `src/maria/`, `tests/` ou `scripts/` existe.
2. **Referências TypeScript só em registro histórico:** caminhos `.ts`/`.mts`, `pnpm` e
   `NODE_ENV` só podem aparecer em seções marcadas como registro histórico (spec 09, D-2): a
   seção começa com uma citação `> **Registro histórico`. Decisões datadas e incidentes ficam
   como estavam; o que alguém vai seguir hoje não pode mandar para a versão TypeScript.
3. **Variáveis de ambiente:** toda variável lida em `src/maria/` está na tabela do README, e
   toda variável da tabela é lida pelo código ou pelo SDK da AWS (lista explícita abaixo).

`MIGRACAO.md` e `docs/migracao/` ficam de fora: são o registro da migração (D-3).
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

DOCUMENTOS = sorted(
    [RAIZ / "README.md", RAIZ / "CLAUDE.md", RAIZ / "CONTRIBUTING.md", RAIZ / "scripts" / "README.md"]
    + [p for p in (RAIZ / "docs").glob("*.md")]
    + [p for p in (RAIZ / ".claude").rglob("*.md")]
    + [RAIZ / "src" / "maria" / "ia" / "CLAUDE.md", RAIZ / "infra" / "terraform" / "CLAUDE.md"]
)

# Lidas pelo SDK da AWS (boto3/botocore), e não por `os.environ` no código da Maria.
VARIAVEIS_DO_SDK = {"AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}

_LINK = re.compile(r"\]\(([^)\s]+)\)")
_CODIGO = re.compile(r"`([^`\n]+)`")
_CAMINHO = re.compile(r"^(?:\.\./)*((?:src/maria|tests|scripts)/[\w./-]*[\w/])")
_TYPESCRIPT = re.compile(r"[\w/.-]+\.(?:ts|mts)\b|\bpnpm\b|\bNODE_ENV\b")


def _nome(caminho: Path) -> str:
    return caminho.relative_to(RAIZ).as_posix()


def _secoes(texto: str) -> list[tuple[bool, str]]:
    """Divide o texto pelos títulos; uma seção é histórica se o primeiro parágrafo é a citação."""
    secoes: list[tuple[bool, str]] = []
    for bloco in re.split(r"(?m)^(?=#{1,6} )", texto):
        corpo = bloco.split("\n", 1)[1] if bloco.startswith("#") and "\n" in bloco else bloco
        historica = corpo.lstrip().startswith("> **Registro histórico")
        secoes.append((historica, bloco))
    return secoes


@pytest.mark.parametrize("documento", DOCUMENTOS, ids=_nome)
def test_links_relativos_apontam_para_arquivo_que_existe(documento: Path) -> None:
    quebrados = []
    for alvo in _LINK.findall(documento.read_text(encoding="utf-8")):
        if re.match(r"^(https?:|mailto:|#)", alvo):
            continue
        caminho = (documento.parent / alvo.split("#", 1)[0]).resolve()
        if not caminho.exists():
            quebrados.append(alvo)
    assert not quebrados, f"{_nome(documento)}: links quebrados: {quebrados}"


@pytest.mark.parametrize("documento", DOCUMENTOS, ids=_nome)
def test_caminhos_citados_existem(documento: Path) -> None:
    faltando = []
    for historica, secao in _secoes(documento.read_text(encoding="utf-8")):
        if historica:
            continue
        for trecho in _CODIGO.findall(secao):
            achado = _CAMINHO.match(trecho.strip())
            if not achado or "<" in trecho or "*" in trecho:
                continue
            caminho = achado.group(1).split(":", 1)[0]
            if not (RAIZ / caminho).exists():
                faltando.append(caminho)
    assert not faltando, f"{_nome(documento)}: caminhos que não existem: {sorted(set(faltando))}"


@pytest.mark.parametrize("documento", DOCUMENTOS, ids=_nome)
def test_referencias_typescript_so_em_registro_historico(documento: Path) -> None:
    fora = []
    for historica, secao in _secoes(documento.read_text(encoding="utf-8")):
        if not historica:
            fora += _TYPESCRIPT.findall(secao)
    assert not fora, f"{_nome(documento)}: referências à versão TypeScript fora de registro histórico: {sorted(set(fora))}"


def _variaveis_do_codigo() -> set[str]:
    padrao = re.compile(r"""os\.environ(?:\.get)?[(\[]\s*["']([A-Z][A-Z0-9_]+)["']""")
    return {v for arquivo in (RAIZ / "src" / "maria").rglob("*.py") for v in padrao.findall(arquivo.read_text(encoding="utf-8"))}


def _variaveis_do_readme() -> set[str]:
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    return set(re.findall(r"(?m)^\| `([A-Z][A-Z0-9_]+)`", readme))


def test_toda_variavel_lida_pelo_codigo_esta_no_readme() -> None:
    faltando = _variaveis_do_codigo() - _variaveis_do_readme()
    assert not faltando, f"variáveis lidas em src/maria/ sem documentação no README: {sorted(faltando)}"


def test_toda_variavel_do_readme_existe() -> None:
    sobrando = _variaveis_do_readme() - _variaveis_do_codigo() - VARIAVEIS_DO_SDK
    assert not sobrando, f"variáveis no README que ninguém lê: {sorted(sobrando)}"


def test_o_teste_encontra_as_variaveis_do_codigo() -> None:
    # Guarda contra o regex parar de achar: hoje são 25 (spec 09, seção 1.3).
    assert len(_variaveis_do_codigo()) >= 25
