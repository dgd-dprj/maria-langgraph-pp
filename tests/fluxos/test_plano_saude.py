"""Fluxo Problemas com plano de saúde (NUDECON, #329): canal e "para quem"."""

import pytest

from maria.fluxos.plano_saude.api import MENSAGEM_OUTRA_PESSOA
from maria.fluxos.plano_saude.graph import interpretar_canal, obter_grafo
from tests.fluxos.conftest import Fluxo, pergunta, texto


def _fluxo() -> Fluxo:
    return Fluxo(obter_grafo(), "teste-plano-saude")


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("por aqui mesmo", "aqui"),
        ("Pelo WhatsApp", "aqui"),
        ("por e-mail", "email"),
        ("email", "email"),
        ("E-MAIL, por favor", "email"),
        ("presencial", "presencial"),
        ("Prefiro ir pessoalmente", "presencial"),
        ("PRESENCIALMENTE", "presencial"),
        ("tanto faz", None),
        ("", None),
        ("por aqui ou por e-mail", None),
    ],
)
def test_interpretar_canal(resposta: str, esperado: str | None) -> None:
    assert interpretar_canal(resposta) == esperado


async def test_primeira_pergunta_e_o_canal_com_o_horario_do_nudecon() -> None:
    r = await _fluxo().iniciar()
    p = pergunta(r)
    assert p is not None and p["tipo"] == "texto"
    assert "das 11h às 16h" in texto(r)
    assert "presencialmente" in texto(r)


async def test_presencial_encerra_sem_perguntar_para_quem() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("presencial")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    assert "presencial" in r["mensagemFinal"]
    assert (await f.estado())["canal"] == "presencial"


@pytest.mark.parametrize("canal", ["por aqui", "por e-mail"])
async def test_aqui_ou_email_seguem_para_a_pergunta_de_para_quem(canal: str) -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder(canal)
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao" and p["opcoes"] == ["Sim", "Não"]
    assert "para você" in texto(r)


async def test_outra_pessoa_encerra_com_o_texto_mock_e_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("por aqui", "false")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "outra_pessoa"
    assert r["mensagemFinal"] == MENSAGEM_OUTRA_PESSOA
    # Não coleta nada da outra pessoa.
    estado = await f.estado()
    assert estado["paraSi"] is False
    assert not {"cpf", "nome", "endereco"} & estado.keys()


async def test_para_mim_conclui_com_a_mensagem_provisoria() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("por e-mail", "true")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    assert "ainda está sendo construído" in r["mensagemFinal"]
    estado = await f.estado()
    assert (estado["canal"], estado["paraSi"]) == ("email", True)


async def test_resposta_que_nao_e_canal_repete_a_pergunta_com_outro_texto() -> None:
    f = _fluxo()
    primeira = await f.iniciar()
    r = await f.responder("tanto faz")
    assert pergunta(r) is not None
    assert texto(r) != texto(primeira)
    assert "Não entendi" in texto(r)


async def test_tres_respostas_sem_canal_encerram_com_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar()
    r = await f.responder("tanto faz", "não sei", "qualquer um")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "canal_nao_entendido"


async def test_dados_conhecidos_viram_estado_e_chave_desconhecida_e_ignorada() -> None:
    f = _fluxo()
    await f.iniciar({"cpf": "00000000000", "nome": "Fulano de Tal", "endereco": {"uf": "RJ"}, "chaveQueNaoExiste": "x"})
    estado = await f.estado()
    assert estado["cpf"] == "00000000000"
    assert estado["endereco"] == {"uf": "RJ"}
    assert "chaveQueNaoExiste" not in estado
