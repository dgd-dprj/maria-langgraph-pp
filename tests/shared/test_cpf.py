"""#497: o CPF conferido pelos dígitos verificadores (exemplos fictícios)."""

import pytest

from maria.shared.cpf import cpf_valido


@pytest.mark.parametrize(
    "texto",
    [
        "12345678909",
        "123.456.789-09",
        " 123 456 789 09 ",
        "123.456.789–09",  # traço do celular
        "52998224725",
        "00000000191",  # a sentinela do mock do Verde para "não encontrado"
        "66666666070",  # a sentinela do mock do Verde para a falha de infra
    ],
)
def test_cpf_que_fecha_a_conta(texto: str) -> None:
    assert cpf_valido(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "12345678900",  # 1º dígito certo, 2º errado
        "12345678919",  # 1º dígito errado
        "11111111111",  # dígitos iguais fecham a conta, mas não são CPF
        "00000000000",
        "1234567890",  # 10 dígitos
        "123456789091",  # 12 dígitos
        "123456789",  # o tamanho do RG do RJ
        "CPF 12345678909",  # com letra: não é a resposta só com o número
        "123.456.789/09",  # barra não é separador do CPF
        "١٢٣٤٥٦٧٨٩٠٩",  # dígitos arábico-índicos
        "",
    ],
)
def test_o_que_nao_e_cpf(texto: str) -> None:
    assert not cpf_valido(texto)


@pytest.mark.parametrize("valor", [None, 12345678909, ["12345678909"]])
def test_nao_texto_nao_e_cpf(valor: object) -> None:
    assert not cpf_valido(valor)
