"""Fluxo Problemas com plano de saúde (NUDECON, #329): canal, "para quem", imagens, renda e confirmação."""

import pytest

from maria.fluxos.plano_saude.api import MENSAGEM_OUTRA_PESSOA
from maria.fluxos.plano_saude.graph import interpretar_canal, interpretar_renda, montar_resumo, obter_grafo
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


DADOS = {
    "cpf": "00000000000",
    "nome": "Pessoa de Teste",
    "dataNascimento": "1990-01-01",
    "email": "teste@exemplo.org",
    "telefone": "21999990000",
    "endereco": {
        "cep": "20000000",
        "logradouro": "Rua de Teste",
        "numero": "1",
        "complemento": "",
        "bairro": "Centro",
        "municipio": "Rio de Janeiro",
        "uf": "RJ",
    },
}


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("2500", 2500.0),
        ("R$ 2.500,50", 2500.5),
        ("2.500", 2500.0),
        ("2500,5", 2500.5),
        ("1.200.000", 1_200_000.0),
        ("uns 3 mil", 3000.0),
        ("0", 0.0),
        ("não tenho renda", 0.0),
        ("sem renda", 0.0),
        ("-100", None),
        ("muita", None),
        ("", None),
        ("99999999999", None),
    ],
)
def test_interpretar_renda(resposta: str, esperado: float | None) -> None:
    assert interpretar_renda(resposta) == esperado


async def test_para_mim_sem_aviso_das_imagens_pergunta_se_ja_enviou() -> None:
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("por e-mail", "true")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao"
    assert "carteirinha" in texto(r)
    assert (await f.estado())["paraSi"] is True


async def test_com_imagens_recebidas_pula_direto_para_a_renda() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "texto"
    assert "renda" in texto(r)


async def test_imagens_nao_enviadas_tres_vezes_encerram_com_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("por aqui", "true", "não")
    assert "Ainda não recebi" in texto(r)
    r = await f.responder("não", "não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "imagens_pendentes"


async def test_imagens_enviadas_seguem_para_a_renda() -> None:
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("por aqui", "true", "sim")
    assert "renda" in texto(r)
    assert (await f.estado())["imagensRecebidas"] is True


async def test_renda_invalida_repete_e_na_terceira_encerra() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "muita")
    assert "Não entendi" in texto(r)
    r = await f.responder("-50", "nada")
    assert pergunta(r) is None
    assert r["motivoHandoff"] == "renda_nao_entendida"


async def test_resumo_mostra_os_dados_como_vieram_e_a_renda() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "R$ 2.500,00")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao" and p["opcoes"] == ["Sim", "Não"]
    resumo = texto(r)
    for esperado in (
        "Nome: Pessoa de Teste",
        "CPF: 00000000000",
        "Data de nascimento: 1990-01-01",
        "E-mail: teste@exemplo.org",
        "Telefone: 21999990000",
        "Endereço: Rua de Teste, 1, Centro, Rio de Janeiro/RJ, CEP 20000000",
        "Renda mensal: R$ 2.500,00",
    ):
        assert esperado in resumo


def test_resumo_trata_vazio_e_ausente_como_nao_informado_e_aceita_cpf_numerico() -> None:
    resumo = montar_resumo({"cpf": 11111111111, "nome": "", "endereco": {}, "renda": 0.0})  # type: ignore[typeddict-item]
    assert "CPF: 11111111111" in resumo
    for rotulo in ("Nome", "Data de nascimento", "E-mail", "Telefone", "Endereço"):
        assert f"{rotulo}: não informado" in resumo
    assert "Renda mensal: R$ 0,00" in resumo


async def test_confirmar_conclui_com_a_renda_nos_metadados() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "2500", "sim")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    estado = await f.estado()
    assert (estado["renda"], estado["confirmado"]) == (2500.0, True)


async def test_nao_confirmar_volta_para_a_renda_e_conserva_o_resto() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "2500", "não")
    assert "Vamos corrigir" in texto(r)
    r = await f.responder("3000")
    assert "Renda mensal: R$ 3.000,00" in texto(r)
    estado = await f.estado()
    assert (estado["canal"], estado["paraSi"], estado["cpf"]) == ("aqui", True, "00000000000")


async def test_tres_nao_na_confirmacao_encerram_com_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "2500", "não", "2500", "não", "2500", "não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "dados_nao_confirmados"


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
