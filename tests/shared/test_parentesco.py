"""Quem é quem no relato, pelas palavras, sem IA (#438)."""

from __future__ import annotations

import pytest

from maria.fluxos.pessoa_presa.graph import PARENTESCOS_PERMITIDOS
from maria.shared import parentesco as p

# ---- pessoa presa: o parentesco pronto ----------------------------------------------


@pytest.mark.parametrize(
    ("relato", "esperado"),
    [
        # O caso do teste pela Tykhe (06/11).
        ("Meu primo foi preso e quero saber quando sai", "Primo(a)"),
        ("minha prima ta presa em bangu", "Primo(a)"),
        ("meu irmão está preso faz dois anos", "Irmão(a)"),
        ("MINHA IRMÃ FOI PRESA", "Irmão(a)"),
        ("meu marido ta na cana", "Esposo(a)"),
        ("minha mulher foi presa ontem", "Esposo(a)"),
        ("meu companheiro rodou", "Companheiro(a)"),
        ("meu ex foi preso", "Ex-esposo(a)"),
        ("meu ex-marido está preso", "Ex-esposo(a)"),
        # Quem fala é o inverso do parente citado.
        ("meu tio foi preso", "Sobrinho(a)"),
        ("minha sobrinha foi presa", "Tio(a)"),
        ("meu pai está preso", "Filho(a)"),
        ("minha mãe foi presa", "Filho(a)"),
        ("meu avô foi preso", "Neto(a)"),  # decisão da Nicole: avô entra
        ("minha avó está presa", "Neto(a)"),
        ("meu neto foi preso", "Avô/Avó"),
        ("meu genro foi preso", "Sogro(a)"),
        ("meu cunhado foi preso", "Cunhado(a)"),
        ("meu amigo foi preso", "Amigo(a)"),
        # "Sou a X dele": quem fala é X.
        ("sou a mãe dele e quero saber do processo", "Mãe"),
        ("sou o pai dela", "Pai"),
        ("sou prima dele", "Primo(a)"),
        # Dois parentes: o que está preso (decisão da Nicole: reconhecer).
        ("minha mãe disse que meu primo foi preso", "Primo(a)"),
        ("meu irmao ta preso e o plano da minha mae n quer libera a cirurgia dela", "Irmão(a)"),
        ("a polícia levou meu sobrinho e minha irmã está desesperada", "Tio(a)"),
        ("prenderam meu tio ontem, minha mãe não sabe de nada", "Sobrinho(a)"),
        ("meu primo foi preso, meu primo não fez nada", "Primo(a)"),
    ],
)
def test_parentesco_pronto(relato: str, esperado: str) -> None:
    assert p.quem_esta_preso(relato) == {"parentesco": esperado}


# ---- pessoa presa: a pergunta curta -------------------------------------------------


@pytest.mark.parametrize(
    ("relato", "pergunta"),
    [
        ("meu filho foi preso e quero saber quando sai", "Você é a mãe ou o pai dele?"),
        ("minha filha está presa", "Você é a mãe ou o pai dela?"),
        ("meu filho rodou ontem e a polícia levou ele", "Você é a mãe ou o pai dele?"),
    ],
)
def test_meu_filho_pergunta_so_se_e_mae_ou_pai(relato: str, pergunta: str) -> None:
    assert p.quem_esta_preso(relato) == {"perguntaParentesco": pergunta, "opcoesParentesco": {"mae": "Mãe", "pai": "Pai"}}


def test_dois_presos_pergunta_qual_deles() -> None:
    analise = p.quem_esta_preso("meu primo e meu irmão foram presos ontem")
    assert analise == {
        "perguntaParentesco": "Você falou do seu primo e do seu irmão. Sobre qual deles é este atendimento?",
        "opcoesParentesco": {"primo": "Primo(a)", "irmao": "Irmão(a)"},
    }


def test_dois_presos_com_filho_leva_a_mae_ou_pai_depois() -> None:
    analise = p.quem_esta_preso("minha filha e meu sobrinho foram presos")
    assert analise["opcoesParentesco"] == {"filha": p.MAE_OU_PAI_DELA, "sobrinho": "Tio(a)"}
    assert analise["perguntaParentesco"] == "Você falou da sua filha e do seu sobrinho. Sobre qual deles é este atendimento?"


@pytest.mark.parametrize(
    "relato",
    [
        "meu sogro foi preso",  # genro ou nora: fora da lista
        "meu namorado foi preso",
        "meu enteado foi preso",
        "meu ex cunhado foi preso",
        "mu imao ta preso",  # erro de digitação: a pergunta de sempre
        "quero saber de um preso",
        "",
    ],
)
def test_sem_saber_a_pergunta_de_sempre(relato: str) -> None:
    assert p.quem_esta_preso(relato) == {}


@pytest.mark.parametrize(
    ("resposta", "opcoes", "esperado"),
    [
        ("sou a mãe", p.OPCOES_MAE_PAI, "Mãe"),
        ("Mãe", p.OPCOES_MAE_PAI, "Mãe"),
        ("o pai", p.OPCOES_MAE_PAI, "Pai"),
        ("2", p.OPCOES_MAE_PAI, "Pai"),
        ("tanto faz", p.OPCOES_MAE_PAI, None),
        ("o primo", {"primo": "Primo(a)", "irmao": "Irmão(a)"}, "Primo(a)"),
        ("do meu irmão", {"primo": "Primo(a)", "irmao": "Irmão(a)"}, "Irmão(a)"),
        ("dos dois", {"primo": "Primo(a)", "irmao": "Irmão(a)"}, None),
        ("a filha", {"filha": p.MAE_OU_PAI_DELA, "sobrinho": "Tio(a)"}, p.MAE_OU_PAI_DELA),
    ],
)
def test_ler_resposta_parentesco(resposta: str, opcoes: dict[str, str], esperado: str | None) -> None:
    assert p.ler_resposta_parentesco(resposta, opcoes) == esperado


def test_todo_parentesco_devolvido_esta_na_lista_do_fluxo() -> None:
    especiais = {p.MAE_OU_PAI_DELE, p.MAE_OU_PAI_DELA, p.DUVIDA}
    devolvidos = {x.de_quem_fala for x in p.PARENTES.values()} | set(p.QUEM_FALA_E.values()) | set(p.OPCOES_MAE_PAI.values())
    assert devolvidos - especiais <= set(PARENTESCOS_PERMITIDOS)


# ---- plano de saúde: para quem é o atendimento ----------------------------------------


@pytest.mark.parametrize(
    ("relato", "esperado"),
    [
        ("o plano da minha mãe negou a cirurgia dela", False),
        ("a unimed negou a operaçao do meu pai", False),
        ("minha mae precisa operar o joelho urgente", False),
        ("meu plano negou minha cirurgia", True),
        ("o plano negou minha cirurgia", True),
        ("preciso de uma cirurgia e o convenio nao libera", True),
        ("meu plano de saúde negou a cirurgia", True),
        ("o plano negou a cirurgia", None),  # não diz de quem
        ("meu marido e eu precisamos, o plano negou minha cirurgia", None),  # os dois
    ],
)
def test_atendimento_para_si(relato: str, esperado: bool | None) -> None:
    assert p.atendimento_para_si(relato) is esperado


# ---- violência doméstica: quem fala é a vítima ----------------------------------------


@pytest.mark.parametrize(
    "relato",
    [
        "meu marido me bate qnd bebe",
        "meu ex me ameaçou de novo ontem",
        "eu apanho do meu companheiro",
        "fui agredida pelo meu marido",
        "ele bate em mim",
    ],
)
def test_fala_como_vitima(relato: str) -> None:
    assert p.fala_como_vitima(relato) is True


@pytest.mark.parametrize(
    "relato",
    ["o ex da minha filha ta ameaçando ela", "minha irmã apanha do marido", "quero uma medida protetiva", ""],
)
def test_na_duvida_a_violencia_pergunta(relato: str) -> None:
    """Nunca False: o Não encerra o atendimento, então a Maria pergunta."""
    assert p.fala_como_vitima(relato) is None
