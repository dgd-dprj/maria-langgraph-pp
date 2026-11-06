"""Conferência do e-mail sem internet (#425): formato e erros comuns de digitação."""

import pytest

from maria.shared.conferir_email import conferir_email


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("nome@gmail.com", "nome@gmail.com"),
        ("  Nome.Sobrenome@Hotmail.com.br  ", "nome.sobrenome@hotmail.com.br"),
        ("meu e-mail é nome@gmail.com.", "nome@gmail.com"),
        ("nome+teste@example.com", "nome+teste@example.com"),
        ("nome_1@yahoo.com.br", "nome_1@yahoo.com.br"),
        ("nome@outlook.com.br", "nome@outlook.com.br"),
        ("nome@rj.gov.br", "nome@rj.gov.br"),
        ("nome@empresa.co", "nome@empresa.co"),
        # Nomes certos que ficam a uma letra de um provedor.
        ("nome@email.com", "nome@email.com"),
        ("nome@ymail.com", "nome@ymail.com"),
        ("nome@mail.com", "nome@mail.com"),
        ("nome@me.com", "nome@me.com"),
    ],
)
def test_email_certo_volta_em_minusculas(resposta: str, esperado: str) -> None:
    assert conferir_email(resposta) == esperado


@pytest.mark.parametrize(
    "resposta",
    [
        None,
        "",
        "nome",
        "nome@",
        "@gmail.com",
        "nome @gmail.com",
        "nome@gmail,com",
        "nome@gmail",
        "nome@@gmail.com",
        "nome..sobrenome@gmail.com",
        ".nome@gmail.com",
        "nome@-gmail.com",
        "nome@gmail.c",
        "nome@gmail.123",
        "um@example.com outro@example.com",
    ],
)
def test_formato_errado(resposta: str | None) -> None:
    assert conferir_email(resposta) is None


@pytest.mark.parametrize(
    "resposta",
    [
        "nome@gmial.com",
        "nome@gmal.com",
        "nome@gamil.com",
        "nome@gmaill.com",
        "nome@hotmal.com",
        "nome@hotmial.com",
        "nome@homail.com",
        "nome@outlok.com",
        "nome@yaho.com.br",
        "nome@iclod.com",
        "nome@gmail.con",
        "nome@hotmail.cmo",
        "nome@empresa.comm",
        "nome@gmail.co",
        "nome@hotmail.cm",
        "nome@gmail.com.br",
    ],
)
def test_erro_comum_de_digitacao(resposta: str) -> None:
    assert conferir_email(resposta) is None
