"""A depuração com IA (#503): a leitura da falha, o teto de custo, as fases e a issue sem conteúdo de log.

A IA, o git e o pytest são simulados: estes testes não gastam nada. A validação com o Bedrock de verdade foi
aprovada à parte pela Nicole (17/11).
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from depuracao import investigar as rotina
from depuracao.investigar import IA, EstourouTeto, Falha, Investigacao, Orcamento, corpo_da_issue, ler_falhas, titulo_da_issue

LOG = """2026-11-17T10:00:01.1Z ..F.
2026-11-17T10:00:01.2Z FAILED tests/shared/test_cpf.py::test_cpf_valido_com_resto_1 - AssertionError: assert False
2026-11-17T10:00:01.3Z FAILED tests/fluxos/test_pessoa_presa.py::test_497_cpf_e_depois_o_rg_segue_normal - assert 'RG'
2026-11-17T10:00:01.4Z FAILED tests/shared/test_cpf.py::test_cpf_valido_com_resto_1 - AssertionError: assert False
2026-11-17T10:00:02.0Z | Violência doméstica: CPF com a conta errada não vai ao Verde (#497) | **FALHOU** | passo 5 |
2026-11-17T10:00:03.0Z 2 failed, 80 passed
"""


def test_ler_falhas_traz_os_testes_e_os_cenarios_sem_repetir() -> None:
    falha = ler_falhas(LOG)
    assert falha.testes == [
        "tests/shared/test_cpf.py::test_cpf_valido_com_resto_1",
        "tests/fluxos/test_pessoa_presa.py::test_497_cpf_e_depois_o_rg_segue_normal",
    ]
    assert falha.cenarios == ["Violência doméstica: CPF com a conta errada não vai ao Verde (#497)"]
    assert "2026-11-17T" not in falha.trecho, "a hora das linhas sai do trecho"


def _modelo(respostas: list[str], tokens: tuple[int, int] = (1000, 100)) -> Any:
    fila = list(respostas)

    def chamar(_sistema: str, _pedido: str, _maximo: int) -> tuple[str, int, int]:
        return fila.pop(0), *tokens

    return chamar


def test_o_teto_para_antes_de_chamar() -> None:
    ia = IA(_modelo(["ok"], tokens=(80_000, 1000)), Orcamento(teto=0.10))
    ia.perguntar("1", "pedido", 500)
    assert ia.orcamento.gasto == pytest.approx((80_000 * 1.10 + 1000 * 5.50) / 1e6)
    with pytest.raises(EstourouTeto):
        ia.perguntar("2", "x" * 30_000, 900)  # a estimativa da próxima passaria do teto
    assert len(ia.orcamento.chamadas) == 1, "a chamada que estouraria nem acontece"


PATCH = "```diff\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n```"


@pytest.fixture
def sem_git(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Git e pytest simulados: o que cada passo devolve fica no dicionário."""
    estado: dict[str, Any] = {"consistente": True, "culpado": "abc1234", "patches_que_passam": {2}, "suite": True, "aplicados": 0}

    def rodar(comando: list[str], _pasta: Path, tempo: int = 600) -> Any:
        class Resultado:
            stdout = " x.py | 2 +-\n"
            returncode = 0 if (comando[-1] != "no:cacheprovider" or estado["suite"]) else 1

        return Resultado()

    def conferir(_pasta: Path, _patch: str, _testes: list[str]) -> bool:
        estado["aplicados"] += 1
        return bool(estado["aplicados"] in estado["patches_que_passam"])

    monkeypatch.setattr(rotina, "rodar", rodar)
    monkeypatch.setattr(rotina, "reproduzir", lambda *_: estado["consistente"])
    monkeypatch.setattr(rotina, "isolar", lambda *_: estado["culpado"])
    monkeypatch.setattr(rotina, "diff_do_commit", lambda *_: "diff do commit")
    monkeypatch.setattr(rotina, "conferir_patch", conferir)
    return estado


FALHA = Falha(testes=["tests/shared/test_cpf.py::test_x"], trecho="saída")


def test_a_segunda_hipotese_passa_e_a_correcao_fica_pronta(sem_git: dict[str, Any], tmp_path: Path) -> None:
    ia = IA(_modelo(["função\nresumo", f"hipótese 1\n{PATCH}", f"hipótese 2\n{PATCH}"]), Orcamento())
    inv = rotina.investigar(tmp_path, FALHA, "base000", "head111", "42", ia)
    assert (inv.tipo, inv.consistente, inv.commit_culpado, inv.fase, inv.parou) == ("função", True, "abc1234", "correção pronta", "")
    assert [h["testes_passaram"] for h in inv.hipoteses] == [False, True]
    assert inv.patch.startswith("--- a/x.py")
    assert len(ia.orcamento.chamadas) == 3


def test_tres_hipoteses_falham_e_precisa_de_pessoa(sem_git: dict[str, Any], tmp_path: Path) -> None:
    sem_git["patches_que_passam"] = set()
    ia = IA(_modelo(["função\nresumo"] + [f"h\n{PATCH}"] * 3), Orcamento())
    inv = rotina.investigar(tmp_path, FALHA, "b", "h", "42", ia)
    assert len(inv.hipoteses) == 3 and not inv.patch
    assert inv.parou == "3 hipóteses falharam: precisa de pessoa"


def test_intermitente_nao_gasta_com_hipotese(sem_git: dict[str, Any], tmp_path: Path) -> None:
    sem_git["consistente"] = False
    ia = IA(_modelo(["demora\nresumo"]), Orcamento())
    inv = rotina.investigar(tmp_path, FALHA, "b", "h", "42", ia)
    assert inv.fase == "intermitente" and len(ia.orcamento.chamadas) == 1


def test_o_teto_vira_parada_registrada(sem_git: dict[str, Any], tmp_path: Path) -> None:
    ia = IA(_modelo(["função\nresumo"], tokens=(85_000, 500)), Orcamento(teto=0.10))
    inv = rotina.investigar(tmp_path, FALHA, "b", "h", "42", ia)
    assert inv.parou.startswith("parou no teto de custo") and inv.custo > 0


def test_a_issue_leva_as_fases_e_os_dados_do_visor_mas_nunca_o_log() -> None:
    inv = Investigacao("42", "head111", "base000", ["tests/shared/test_cpf.py::test_x"], [], tipo="função", resumo="RESUMO COM SAÍDA DO CI")
    inv.consistente, inv.commit_culpado, inv.fase, inv.custo = True, "abc1234", "correção pronta", 0.0123
    inv.hipoteses = [{"tentativa": 1, "hipotese": "o resto 1 virou dígito 10", "testes_passaram": True}]
    corpo = corpo_da_issue(inv, "https://github.com/x/y/actions/runs/42")
    assert "RESUMO COM SAÍDA DO CI" not in corpo, "a issue pública não leva o resumo da saída do CI"
    assert corpo.count("- [x]") == 6 and "`abc1234`" in corpo and "US$ 0.0123" in corpo
    dados = json.loads(re.search(r"```json\n(.*?)\n```", corpo, re.DOTALL).group(1))  # type: ignore[union-attr]
    assert dados["fase"] == "correção pronta" and dados["patch"] is False and dados["resumo"] == ""
    assert titulo_da_issue(inv) == "[BUG] Depuração com IA: test_x (correção pronta)"
