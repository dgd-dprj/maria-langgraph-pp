"""Validação dos dados da outra pessoa sem cadastro no Verde (#446): só por regra, sem IA."""

import pytest

from maria.fluxos.pessoa_presa.graph import PARENTESCOS_PERMITIDOS
from maria.fluxos.plano_saude import dados_outra as d


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("Maria de Teste", "Maria de Teste"),
        ("  Ana   Maria  d'Ávila-Souza ", "Ana Maria d'Ávila-Souza"),
        ("Maria", None),
        ("Maria 2", None),
        ("", None),
        ("12 34", None),
    ],
)
def test_nome_pede_nome_e_sobrenome(resposta: str, esperado: str | None) -> None:
    assert d.interpretar_nome(resposta, {}) == esperado


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("02/02/1991", "02/02/1991"),
        ("2/2/1991", "02/02/1991"),
        ("02-02-1991", "02/02/1991"),
        ("02021991", "02/02/1991"),
        ("31/02/1990", None),
        ("01/01/2999", None),
        ("01/01/1850", None),
        ("abc", None),
    ],
)
def test_data_de_nascimento_aceita_data_real_e_passada(resposta: str, esperado: str | None) -> None:
    assert d.interpretar_data_nascimento(resposta, {}) == esperado


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("casada", "Casado(a)"),
        ("Solteiro", "Solteiro(a)"),
        ("união estável", "União estável"),
        ("uniao estavel", "União estável"),
        ("viuva", "Viúvo(a)"),
        ("divorciado(a)", "Divorciado(a)"),
        ("sep", "Separado(a)"),
        ("complicado", None),
        ("", None),
    ],
)
def test_estado_civil_casa_com_a_lista(resposta: str, esperado: str | None) -> None:
    assert d.interpretar_estado_civil(resposta, {}) == esperado


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("mãe", "Mãe"),
        ("mae", "Mãe"),
        ("irmã", "Irmã"),
        ("avó", "Avô/Avó"),
        ("tia", "Tio(a)"),
        ("esposa", "Esposo(a)"),
        ("ex-esposa", "Ex-esposo(a)"),
        ("vizinho", None),
    ],
)
def test_parentesco_casa_com_a_lista(resposta: str, esperado: str | None) -> None:
    assert d.interpretar_parentesco(resposta, {}) == esperado
    assert esperado is None or esperado in PARENTESCOS_PERMITIDOS


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [("12.345.678-9", "12.345.678-9"), ("não tenho", ""), ("Não", ""), ("1", None), ("@@@@@@", None), ("x" * 30, None)],
)
def test_rg_e_opcional(resposta: str, esperado: str | None) -> None:
    assert d.interpretar_rg(resposta, {}) == esperado


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("(21) 98888-0000", "21988880000"),
        ("21 3333-4444", "2133334444"),
        ("+55 21 98888-0000", "21988880000"),
        ("988880000", None),
        ("21 8888-00001", None),
        ("21 88888-0000", None),
        ("00 98888-0000", None),
        ("abc", None),
    ],
)
def test_telefone_com_ddd(resposta: str, esperado: str | None) -> None:
    assert d.interpretar_telefone(resposta, {}) == esperado


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [("mesmo", "21988880000"), ("o mesmo", "21988880000"), ("não tem", ""), ("(21) 97777-0000", "21977770000"), ("123", None)],
)
def test_whatsapp_pode_ser_o_mesmo_telefone(resposta: str, esperado: str | None) -> None:
    assert d.interpretar_whatsapp(resposta, {"telefone": "21988880000"}) == esperado


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [("Maria@Exemplo.org", "maria@exemplo.org"), ("não tenho", ""), ("maria@", None), ("maria exemplo.org", None), ("a@b", None)],
)
def test_email_e_opcional(resposta: str, esperado: str | None) -> None:
    assert d.interpretar_email(resposta, {}) == esperado


def test_a_ordem_das_etapas_e_o_endereco_fica_no_meio() -> None:
    assert d.ETAPAS == (
        "nome",
        "dataNascimento",
        "estadoCivil",
        "profissao",
        "rg",
        "endereco",
        "telefone",
        "whatsapp",
        "email",
        "parentesco",
    )
    assert d.etapa_depois_de("rg") == "endereco" and d.etapa_depois_de("parentesco") is None
