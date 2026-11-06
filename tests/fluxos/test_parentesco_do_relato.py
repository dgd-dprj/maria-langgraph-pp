"""O parentesco tirado do relato pelas palavras, sem IA (#438)."""

from __future__ import annotations

import pytest

from maria.fluxos.pessoa_presa.graph import PARENTESCOS_PERMITIDOS
from maria.fluxos.pessoa_presa.parentesco import parentesco_do_relato


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
        ("o pai dos meus filhos, meu ex marido, foi preso", None),  # "meus filhos" deixa em dúvida
        # Quem fala é o inverso do parente citado.
        ("meu tio foi preso", "Sobrinho(a)"),
        ("minha sobrinha foi presa", "Tio(a)"),
        ("meu pai está preso", "Filho(a)"),
        ("minha mãe foi presa", "Filho(a)"),
        ("meu neto foi preso", "Avô/Avó"),
        ("meu genro foi preso", "Sogro(a)"),
        ("meu cunhado foi preso", "Cunhado(a)"),
        ("meu amigo foi preso", "Amigo(a)"),
        # "Sou a X dele": quem fala é X.
        ("sou a mãe dele e quero saber do processo", "Mãe"),
        ("sou o pai dela", "Pai"),
        ("sou prima dele", "Primo(a)"),
        ("sou esposa dele", "Esposo(a)"),
        # O mesmo parente duas vezes vale.
        ("meu primo foi preso, meu primo não fez nada", "Primo(a)"),
    ],
)
def test_parentesco_do_relato(relato: str, esperado: str | None) -> None:
    assert parentesco_do_relato(relato) == esperado


@pytest.mark.parametrize(
    "relato",
    [
        "meu filho foi preso",  # a mãe ou o pai?
        "minha filha está presa",
        "meu avô foi preso",  # quem fala é neto, que não está na lista
        "meu sogro foi preso",  # genro ou nora, que não estão na lista
        "meu namorado foi preso",
        "meu enteado foi preso",
        "meu primo e meu irmão foram presos",  # dois parentes
        "minha mãe disse que meu primo foi preso",  # dois parentes: quem está preso?
        "mu imao ta preso",  # erro de digitação: a Maria pergunta
        "quero saber de um preso",
        "",
        "meu ex cunhado foi preso",
    ],
)
def test_na_duvida_a_maria_pergunta(relato: str) -> None:
    assert parentesco_do_relato(relato) is None


def test_todo_parentesco_devolvido_esta_na_lista_do_fluxo() -> None:
    from maria.fluxos.pessoa_presa import parentesco as p

    devolvidos = set(p._DO_PRESO_PARA_QUEM_FALA.values()) | set(p._QUEM_FALA_E.values()) | {"Ex-esposo(a)"}
    assert devolvidos <= set(PARENTESCOS_PERMITIDOS)
