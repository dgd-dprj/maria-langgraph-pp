"""O mecanismo das conferências contra as fixtures para campos novos (#294)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.api.campos_posteriores import CAMPOS_POSTERIORES, CampoPosterior, sem_campos_posteriores


@pytest.mark.parametrize(
    ("corpo", "esperado"),
    [
        ('{"destino":"agendamento","status":"concluido","resposta":"ok"}', '{"status":"concluido","resposta":"ok"}'),
        ('{"status":"concluido","destino":"agendamento","resposta":"ok"}', '{"status":"concluido","resposta":"ok"}'),
        ('{"status":"concluido","resposta":"ok","destino":"agendamento"}', '{"status":"concluido","resposta":"ok"}'),
        ('{"destino":"agendamento"}', "{}"),
    ],
    ids=["primeira", "meio", "ultima", "unica"],
)
def test_tira_o_campo_em_qualquer_posicao(corpo: str, esperado: str) -> None:
    assert sem_campos_posteriores(corpo) == esperado


def test_corpo_sem_o_campo_volta_o_mesmo_objeto() -> None:
    corpo = '{"status":"em_andamento","resposta":"Qual é o seu CPF?"}'
    assert sem_campos_posteriores(corpo) is corpo


def test_nada_e_reserializado() -> None:
    # Número em notação do JavaScript, acento cru e escapado, espaços: tudo como foi gravado.
    corpo = '{ "metadados" : {"ehVitima":1e-7} , "destino" : "agendamento" , "a":"é","b":"\\u00e9" }'
    assert sem_campos_posteriores(corpo) == '{ "metadados" : {"ehVitima":1e-7} , "a":"é","b":"\\u00e9" }'


def test_nao_tira_campo_aninhado_nem_dentro_de_texto() -> None:
    aninhado = '{"metadados":{"destino":"agendamento"},"status":"concluido"}'
    em_texto = '{"resposta":"veja \\"destino\\":\\"agendamento\\"","status":"concluido"}'
    em_lista = '{"itens":[{"destino":"agendamento"}],"status":"concluido"}'
    for corpo in (aninhado, em_texto, em_lista):
        assert sem_campos_posteriores(corpo) is corpo


def test_tira_o_campo_do_primeiro_nivel_mesmo_com_o_nome_aninhado_tambem() -> None:
    corpo = '{"metadados":{"destino":"x"},"destino":"agendamento","status":"concluido"}'
    assert sem_campos_posteriores(corpo) == '{"metadados":{"destino":"x"},"status":"concluido"}'


@pytest.mark.parametrize("valor", ['"agendamento"', "null", "3", '{"tipo":"x"}', '["a","b"]'])
def test_tira_qualquer_tipo_de_valor(valor: str) -> None:
    assert sem_campos_posteriores(f'{{"status":"concluido","destino":{valor},"resposta":"ok"}}') == '{"status":"concluido","resposta":"ok"}'


@pytest.mark.parametrize("corpo", ["", "[]", '["destino"]', '"destino"', "null", '{"destino":', '{"destino":"a"} lixo', "<html></html>"])
def test_corpo_que_nao_e_objeto_json_volta_o_mesmo(corpo: str) -> None:
    assert sem_campos_posteriores(corpo) is corpo


def test_campo_fora_da_lista_continua_no_corpo() -> None:
    corpo = '{"status":"concluido","campoNovoSemRegistro":"x"}'
    assert sem_campos_posteriores(corpo) is corpo


def _conferir_registro(campo: str, registro: CampoPosterior) -> None:
    assert registro.issue > 0, f"{campo}: sem issue"
    teste = Path(registro.teste)
    assert teste.is_file(), f"{campo}: o teste citado não existe: {registro.teste}"
    assert teste.name.startswith("test_"), f"{campo}: {registro.teste} não é coletado pelo pytest"
    assert f'"{campo}"' in teste.read_text(encoding="utf-8"), f"{campo}: {registro.teste} não menciona o campo"


@pytest.mark.parametrize(("campo", "registro"), sorted(CAMPOS_POSTERIORES.items()))
def test_cada_campo_cita_a_issue_e_um_teste_que_existe_e_cobre_o_campo(campo: str, registro: CampoPosterior) -> None:
    _conferir_registro(campo, registro)


def test_registro_com_teste_inexistente_falha() -> None:
    with pytest.raises(AssertionError, match="não existe"):
        _conferir_registro("fantasma", CampoPosterior(issue=1, teste="tests/api/test_que_nao_existe.py"))
