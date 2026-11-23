"""Corpo do PR e metadados da versão (#542)."""

from typing import Any

from maria.versionamento.manifesto import montar_manifesto
from maria.versionamento.meta import conferir_pr, entrada_do_pr, extrair_secao, issue_de_origem, prs_do_compartilhado, prs_do_fluxo
from tests.versionamento.conftest import GRAFO, escrever

CORPO = """## Resumo

Texto solto.

## Solicitado por

Nicole, Ícaro

## Resumo da mudança

Troca a pergunta do nome para pedir o nome completo.

Closes #99
"""


def test_extrai_as_secoes_do_corpo() -> None:
    assert extrair_secao(CORPO, "Solicitado por") == "Nicole, Ícaro"
    assert extrair_secao(CORPO, "Resumo da mudança") == "Troca a pergunta do nome para pedir o nome completo. Closes #99"


def test_secao_so_com_comentario_ou_placeholder_conta_como_vazia() -> None:
    assert extrair_secao("## Solicitado por\n\n<!-- Nome de quem pediu -->\n\n## Resumo da mudança\nx", "Solicitado por") == ""
    assert extrair_secao("## Solicitado por\nn/a\n", "Solicitado por") == ""
    assert extrair_secao("## Solicitado por\n-\n", "Solicitado por") == ""
    assert extrair_secao("sem seções", "Solicitado por") == ""
    assert extrair_secao("## solicitado por\nAna\n", "Solicitado por") == "Ana"


def _dois_manifestos(raiz: Any, mudar: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    base = montar_manifesto(raiz)
    if mudar:
        escrever(raiz, "fluxos/exemplo/graph.py", GRAFO.replace("Qual o seu nome?", "Qual o nome completo?"))
    return base, montar_manifesto(raiz)


def test_pr_sem_mudanca_de_fluxo_passa_sem_as_secoes(raiz: Any) -> None:
    base, head = _dois_manifestos(raiz, mudar=False)
    resultado = conferir_pr(base, head, "")
    assert resultado.ok and not resultado.mudou and "Nenhum fluxo mudou" in resultado.markdown


def test_pr_que_muda_fluxo_sem_solicitante_falha(raiz: Any) -> None:
    base, head = _dois_manifestos(raiz, mudar=True)
    resultado = conferir_pr(base, head, "## Resumo da mudança\nTroca a pergunta.\n")
    assert resultado.mudou and not resultado.ok
    assert resultado.faltando == ["Solicitado por"]
    assert "exemplo" in resultado.markdown and "Solicitado por" in resultado.markdown


def test_pr_que_muda_fluxo_sem_resumo_falha(raiz: Any) -> None:
    base, head = _dois_manifestos(raiz, mudar=True)
    assert conferir_pr(base, head, "## Solicitado por\nAna\n").faltando == ["Resumo da mudança"]


def test_pr_que_muda_fluxo_com_as_duas_secoes_passa(raiz: Any) -> None:
    base, head = _dois_manifestos(raiz, mudar=True)
    resultado = conferir_pr(base, head, CORPO)
    assert resultado.ok and resultado.mudou and resultado.faltando == []


def test_mudanca_no_compartilhado_so_avisa(raiz: Any) -> None:
    base = montar_manifesto(raiz)
    escrever(raiz, "shared/util.py", "def util():\n    return 2\n")
    resultado = conferir_pr(base, montar_manifesto(raiz), "")
    assert resultado.ok and not resultado.mudou


def test_entrada_do_pr_junta_secoes_issue_aprovacao_e_arquivos() -> None:
    pr = {"number": 7, "title": ":sparkles: feat: x", "user": {"login": "dev"}, "body": CORPO}
    entrada = entrada_do_pr(pr, ["src/maria/fluxos/exemplo/graph.py", "README.md"], ["Nicole", "Nicole", "Ana"])
    assert entrada["numero"] == 7 and entrada["autor"] == "dev"
    assert entrada["solicitante"] == "Nicole, Ícaro"
    assert entrada["aprovado_por"] == ["Ana", "Nicole"]
    assert entrada["issue_origem"] == 99 == issue_de_origem(CORPO)
    assert entrada["arquivos"] == ["README.md", "src/maria/fluxos/exemplo/graph.py"]


def test_atribuicao_dos_prs_por_pasta_config_e_compartilhado() -> None:
    prs = [
        {"numero": 1, "arquivos": ["src/maria/fluxos/pessoa_presa/graph.py"]},
        {"numero": 2, "arquivos": ["src/maria/fluxos/violencia_domestica/api.py"]},
        {"numero": 3, "arquivos": ["src/maria/fluxos/__init__.py"]},
        {"numero": 4, "arquivos": ["src/maria/shared/trava.py"]},
        {"numero": 5, "arquivos": ["docs/x.md"]},
    ]
    assert [p["numero"] for p in prs_do_fluxo(prs, "pessoa_presa")] == [1, 3]
    assert [p["numero"] for p in prs_do_fluxo(prs, None)] == [3]
    assert [p["numero"] for p in prs_do_compartilhado(prs)] == [4]
