"""O que a esteira sabe de cada mudança (#542): PR, solicitante, resumo e aprovação.

Só biblioteca padrão: a esteira usa este módulo antes de instalar as dependências (script de metadados do deploy).

A mudança de fluxo precisa de duas seções no corpo do PR para a `develop`:

    ## Solicitado por
    Nome ou login de quem pediu a mudança (mais de um, separados por vírgula).

    ## Resumo da mudança
    Uma ou duas frases do que mudou e por quê.

O texto de ajuda do modelo fica em comentário HTML, que a conferência ignora: seção só com o comentário conta como vazia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from maria.versionamento.alteracoes import comparar_compartilhado, comparar_fluxo, contagem

SECAO_SOLICITANTE = "Solicitado por"
SECAO_RESUMO = "Resumo da mudança"
VAZIOS = frozenset({"", "-", "--", "n/a", "na", "nenhum", "nenhuma", "tbd", "todo", "a preencher"})
CAMINHOS_DE_CONFIG = ("src/maria/fluxos/__init__.py", "src/maria/fluxos/tipos_tykhe.py")
PASTAS_COMPARTILHADAS = tuple(f"src/maria/{p}/" for p in ("shared", "ia", "subgrafos", "integracoes"))

_COMENTARIO_HTML = re.compile(r"<!--.*?-->", re.DOTALL)
_ISSUE = re.compile(r"\b(?:closes|fixes|resolves|refs)\s+#(\d+)", re.IGNORECASE)


def extrair_secao(corpo: str, titulo: str) -> str:
    """O texto da seção `## <titulo>` do corpo do PR, sem comentários; vazio se não houver ou for só placeholder."""
    limpo = _COMENTARIO_HTML.sub("", corpo or "")
    achado = re.search(rf"^#{{2,3}}\s*{re.escape(titulo)}\s*:?\s*$(.*?)(?=^#{{1,3}}\s|\Z)", limpo, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    if not achado:
        return ""
    texto = " ".join(achado.group(1).split())
    return "" if texto.lower().strip(" .") in VAZIOS else texto


@dataclass
class ResultadoPr:
    mudou: bool
    faltando: list[str] = field(default_factory=list)
    markdown: str = ""

    @property
    def ok(self) -> bool:
        return not self.mudou or not self.faltando


def conferir_pr(base: dict[str, Any], head: dict[str, Any], corpo: str) -> ResultadoPr:
    """Falha (`ok` falso) quando algum fluxo mudou em relação à base e o PR não diz quem pediu nem resume."""
    linhas: list[str] = []
    for id_, entrada in head["fluxos"].items():
        antes = base["fluxos"].get(id_)
        if antes is None or antes["hash"] != entrada["hash"]:
            alteracoes = comparar_fluxo(antes["snapshot"] if antes else None, entrada["snapshot"])
            linhas.append(f"- **{entrada['nome']}** (`{id_}`): {contagem(alteracoes)}")
    for id_ in base["fluxos"]:
        if id_ not in head["fluxos"]:
            linhas.append(f"- **{base['fluxos'][id_]['nome']}** (`{id_}`): fluxo removido")
    compartilhado = base["compartilhado"]["hash"] != head["compartilhado"]["hash"]
    mudou = bool(linhas)
    faltando = [t for t in (SECAO_SOLICITANTE, SECAO_RESUMO) if not extrair_secao(corpo, t)] if mudou else []
    titulo = "### Versão dos fluxos (#542)\n"
    if not mudou:
        texto = titulo + "Nenhum fluxo mudou neste PR."
    else:
        texto = titulo + "Fluxos que mudam neste PR:\n" + "\n".join(linhas)
        if compartilhado:
            alt = comparar_compartilhado(base["compartilhado"]["snapshot"], head["compartilhado"]["snapshot"])
            texto += f"\n\nCódigo compartilhado também mudou ({len(alt)} arquivo(s)): confira o impacto nos outros fluxos."
        if faltando:
            texto += "\n\n**Faltando no corpo do PR:** " + ", ".join(f"`## {t}`" for t in faltando)
    return ResultadoPr(mudou=mudou, faltando=faltando, markdown=texto + "\n")


def issue_de_origem(corpo: str) -> int | None:
    achado = _ISSUE.search(corpo or "")
    return int(achado.group(1)) if achado else None


def entrada_do_pr(pr: dict[str, Any], arquivos: list[str], aprovadores: list[str]) -> dict[str, Any]:
    """Uma linha do `prs` do arquivo de metadados, a partir do PR (JSON da API do GitHub)."""
    corpo = pr.get("body") or ""
    return {
        "numero": pr["number"],
        "titulo": pr.get("title", ""),
        "autor": (pr.get("user") or {}).get("login", ""),
        "aprovado_por": sorted(set(aprovadores)),
        "solicitante": extrair_secao(corpo, SECAO_SOLICITANTE),
        "resumo": extrair_secao(corpo, SECAO_RESUMO),
        "issue_origem": issue_de_origem(corpo),
        "arquivos": sorted(arquivos),
    }


def prs_do_fluxo(prs: list[dict[str, Any]], pasta: str | None) -> list[dict[str, Any]]:
    """Os PRs que mexeram na pasta do fluxo ou na configuração dos fluxos (fluxos/__init__.py, tipos_tykhe.py)."""
    prefixo = f"src/maria/fluxos/{pasta}/" if pasta else None
    return [pr for pr in prs if any(a in CAMINHOS_DE_CONFIG or (prefixo and a.startswith(prefixo)) for a in pr.get("arquivos", []))]


def prs_do_compartilhado(prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [pr for pr in prs if any(a.startswith(PASTAS_COMPARTILHADAS) for a in pr.get("arquivos", []))]
