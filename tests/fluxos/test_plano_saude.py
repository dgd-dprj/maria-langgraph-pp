"""Fluxo Problemas com plano de saúde (NUDECON, #329): canal e "para quem"."""

import pytest

from maria.fluxos.plano_saude.api import MENSAGEM_CONCLUIDO, MENSAGEM_OUTRA_PESSOA, extrair_metadados_plano_saude
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


DADOS_DA_TYKHE = {
    "cpf": "00000000000",
    "nome": "Fulano de Tal",
    "dataNascimento": "1990-01-31",
    "email": "fulano@example.com",
    "telefone": "21999990000",
    "endereco": {
        "cep": "20000000",
        "logradouro": "Rua de Teste",
        "numero": "1",
        "bairro": "Centro",
        "municipio": "Rio de Janeiro",
        "uf": "RJ",
    },
}


async def test_para_mim_sem_aviso_da_tykhe_pergunta_se_ja_enviou_as_imagens() -> None:
    f = _fluxo()
    await f.iniciar(DADOS_DA_TYKHE)
    r = await f.responder("por e-mail", "true")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao" and p["opcoes"] == ["Sim", "Não"]
    assert "fotos dos documentos" in texto(r)
    estado = await f.estado()
    assert (estado["canal"], estado["paraSi"]) == ("email", True)


async def test_com_o_aviso_da_tykhe_pula_a_pergunta_das_imagens_e_vai_para_a_renda() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS_DA_TYKHE, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "texto"
    assert "renda mensal" in texto(r)


async def test_imagens_ja_enviadas_seguem_para_a_renda() -> None:
    f = _fluxo()
    await f.iniciar(DADOS_DA_TYKHE)
    r = await f.responder("por aqui", "true", "sim")
    assert "renda mensal" in texto(r)
    assert (await f.estado())["imagensRecebidas"] is True


async def test_imagens_nao_enviadas_repetem_a_pergunta_com_outro_texto() -> None:
    f = _fluxo()
    await f.iniciar(DADOS_DA_TYKHE)
    primeira = await f.responder("por aqui", "true")
    r = await f.responder("não")
    assert pergunta(r) is not None
    assert texto(r) != texto(primeira)
    assert "Ainda não recebi" in texto(r)


async def test_tres_nao_nas_imagens_encerram_com_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar(DADOS_DA_TYKHE)
    r = await f.responder("por aqui", "true", "não", "não", "não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "imagens_pendentes"


async def test_resumo_mostra_os_dados_da_tykhe_como_vieram_e_a_renda() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS_DA_TYKHE, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "R$ 2.500,00 por mês")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao" and p["opcoes"] == ["Sim", "Não"]
    resumo = texto(r)
    assert "Nome: Fulano de Tal" in resumo
    assert "CPF: 00000000000" in resumo
    assert "Data de nascimento: 31/01/1990" in resumo
    assert "E-mail: fulano@example.com" in resumo
    assert "Telefone: 21999990000" in resumo
    assert "Endereço: Rua de Teste, 1, Centro, Rio de Janeiro/RJ, CEP 20000000" in resumo
    assert "Renda mensal: R$ 2.500,00 por mês" in resumo


async def test_resumo_aceita_endereco_em_texto_e_marca_o_que_falta() -> None:
    f = _fluxo()
    await f.iniciar({"nome": "Fulano de Tal", "endereco": "Rua Fictícia, 1", "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "2000")
    resumo = texto(r)
    assert "Endereço: Rua Fictícia, 1" in resumo
    assert "CPF: não informado" in resumo
    assert "E-mail: não informado" in resumo


async def test_chave_vazia_e_tratada_como_ausente_no_resumo() -> None:
    f = _fluxo()
    await f.iniciar({"cpf": "", "nome": "Fulano de Tal", "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "2000")
    assert "CPF: não informado" in texto(r)


async def test_confirmar_encaminha_e_devolve_os_dados_preenchidos() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS_DA_TYKHE, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "2000", "sim")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    assert r["mensagemFinal"] == MENSAGEM_CONCLUIDO
    estado = await f.estado()
    assert (estado["renda"], estado["confirmou"], estado["canal"]) == ("2000", True, "aqui")
    metadados = extrair_metadados_plano_saude(estado)
    assert metadados == {"canal": "aqui", "paraSi": True, "imagensRecebidas": True, "renda": "2000", "confirmou": True}


async def test_nao_confirmar_encerra_com_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS_DA_TYKHE, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "2000", "não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "dados_nao_confirmados"


async def test_renda_vazia_repete_a_pergunta_e_tres_vezes_encerra() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS_DA_TYKHE, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "  ")
    assert "Não entendi" in texto(r)
    r = await f.responder("", " ")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "renda_nao_informada"


async def test_a_ia_de_reescrita_nao_mexe_no_resumo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com a reescrita ligada, só a pergunta é reescrita; o resumo vem intacto depois dela."""

    async def reescrever(campo: str, base: str) -> dict[str, object]:
        return {"perguntaAtualTexto": "Reescrita pela IA?", "perguntaAtualViaIA": True, "perguntaAtualTokensTotal": 1}

    monkeypatch.setattr("maria.fluxos.plano_saude.graph.preparar_pergunta", reescrever)
    f = _fluxo()
    await f.iniciar({**DADOS_DA_TYKHE, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "2000")
    assert texto(r).startswith("Reescrita pela IA?\n\nNome: Fulano de Tal\nCPF: 00000000000")


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
