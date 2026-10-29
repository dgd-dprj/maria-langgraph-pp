"""Fluxo Problemas com plano de saúde (NUDECON, #329): canal, "para quem", imagens, renda e confirmação."""

import pytest

from maria.fluxos.plano_saude.api import (
    HORARIO_UNIDADE_PADRAO,
    ID_ASSUNTO_UNIDADE_FORA_DO_RIO,
    ID_MUNICIPIO_RIO,
    MENSAGEM_ERRO_INTERNO,
    MENSAGEM_FALHA_INFRA_VERDE,
    MENSAGEM_FORA_DO_RIO,
    MENSAGEM_MUNICIPIO_NAO_IDENTIFICADO,
    MENSAGEM_OUTRA_PESSOA,
)
from maria.fluxos.plano_saude.graph import interpretar_canal, interpretar_renda, montar_resumo, obter_grafo
from maria.shared.types import DadosCep, DadosPessoa, OrgaoAtendimento, OrgaosPrimeiroAtendimento
from tests.fluxos.conftest import Fluxo, pergunta, texto

# Sem CEP o fluxo nem começa (#331); o mock do Verde devolve o Rio para qualquer CEP que não seja "00000000".
COM_CEP = {"endereco": {"cep": "20000000"}}


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
    r = await _fluxo().iniciar(COM_CEP)
    p = pergunta(r)
    assert p is not None and p["tipo"] == "texto"
    assert "das 11h às 16h" in texto(r)
    assert "presencialmente" in texto(r)


async def test_presencial_encerra_sem_perguntar_para_quem() -> None:
    f = _fluxo()
    await f.iniciar(COM_CEP)
    r = await f.responder("presencial")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    assert "presencial" in r["mensagemFinal"]
    assert (await f.estado())["canal"] == "presencial"


@pytest.mark.parametrize("canal", ["por aqui", "por e-mail"])
async def test_aqui_ou_email_seguem_para_a_pergunta_de_para_quem(canal: str) -> None:
    f = _fluxo()
    await f.iniciar(COM_CEP)
    r = await f.responder(canal)
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao" and p["opcoes"] == ["Sim", "Não"]
    assert "para você" in texto(r)


async def test_outra_pessoa_encerra_com_o_texto_mock_e_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar(COM_CEP)
    r = await f.responder("por aqui", "false")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "outra_pessoa"
    assert r["mensagemFinal"] == MENSAGEM_OUTRA_PESSOA
    # Não coleta nada da outra pessoa.
    estado = await f.estado()
    assert estado["paraSi"] is False
    assert not {"cpf", "nome"} & estado.keys()
    assert estado["endereco"] == COM_CEP["endereco"]


DADOS = {
    "relato": "O plano negou a minha cirurgia",
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


async def test_sem_relato_pergunta_a_situacao_antes_da_renda() -> None:
    f = _fluxo()
    await f.iniciar({k: v for k, v in DADOS.items() if k != "relato"} | {"imagensRecebidas": True})
    r = await f.responder("por aqui", "true")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "texto"
    assert "o que aconteceu" in texto(r)
    r = await f.responder("O plano negou a minha cirurgia")
    assert "renda" in texto(r)
    assert (await f.estado())["relato"] == "O plano negou a minha cirurgia"


async def test_com_relato_nao_pergunta_a_situacao() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("por aqui", "true")
    assert "o que aconteceu" not in texto(r)
    assert "renda" in texto(r)


async def test_situacao_com_menos_de_tres_palavras_repete_e_na_terceira_encerra() -> None:
    f = _fluxo()
    await f.iniciar({k: v for k, v in DADOS.items() if k != "relato"} | {"imagensRecebidas": True})
    r = await f.responder("por aqui", "true", "ajuda")
    assert "um pouco mais de detalhe" in texto(r)
    r = await f.responder("negaram tudo", "")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "situacao_nao_informada"


async def test_situacao_pergunta_depois_das_imagens_quando_sem_aviso() -> None:
    f = _fluxo()
    await f.iniciar({k: v for k, v in DADOS.items() if k != "relato"})
    r = await f.responder("por aqui", "true", "sim")
    assert "o que aconteceu" in texto(r)


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
        "Situação: O plano negou a minha cirurgia",
        "Renda mensal: R$ 2.500,00",
    ):
        assert esperado in resumo


def test_resumo_trata_vazio_e_ausente_como_nao_informado_e_aceita_cpf_numerico() -> None:
    resumo = montar_resumo({"cpf": 11111111111, "nome": "", "endereco": {}, "renda": 0.0})  # type: ignore[typeddict-item]
    assert "CPF: 11111111111" in resumo
    for rotulo in ("Nome", "Data de nascimento", "E-mail", "Telefone", "Endereço", "Situação"):
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
    primeira = await f.iniciar(COM_CEP)
    r = await f.responder("tanto faz")
    assert pergunta(r) is not None
    assert texto(r) != texto(primeira)
    assert "Não entendi" in texto(r)


async def test_tres_respostas_sem_canal_encerram_com_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar(COM_CEP)
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


def _verde_devolve(monkeypatch: pytest.MonkeyPatch, dados: DadosCep) -> list[str]:
    ceps: list[str] = []

    async def consultar_cep(cep: str) -> DadosCep:
        ceps.append(cep)
        return dados

    monkeypatch.setattr("maria.fluxos.plano_saude.graph.consultar_cep", consultar_cep)
    return ceps


async def test_cep_do_rio_segue_para_a_pergunta_do_canal(monkeypatch: pytest.MonkeyPatch) -> None:
    ceps = _verde_devolve(monkeypatch, {"encontrado": True, "idMunicipio": ID_MUNICIPIO_RIO})
    r = await _fluxo().iniciar(COM_CEP)
    assert ceps == ["20000000"]
    assert "Como você prefere seguir" in texto(r)
    assert "statusFinal" not in r


@pytest.mark.parametrize(
    ("dados", "motivo", "mensagem"),
    [
        ({"encontrado": True, "idMunicipio": 3000}, "fora_do_rio", MENSAGEM_FORA_DO_RIO),
        ({"encontrado": True, "idUf": 19}, "municipio_nao_identificado", MENSAGEM_MUNICIPIO_NAO_IDENTIFICADO),
        ({"encontrado": False}, "municipio_nao_identificado", MENSAGEM_MUNICIPIO_NAO_IDENTIFICADO),
        ({"encontrado": False, "falhaInfra": True}, "falha_infra_verde", MENSAGEM_FALHA_INFRA_VERDE),
    ],
)
async def test_fora_do_rio_e_falhas_da_conferencia_encerram_com_atendimento_humano(
    monkeypatch: pytest.MonkeyPatch, dados: DadosCep, motivo: str, mensagem: str
) -> None:
    _verde_devolve(monkeypatch, dados)
    f = _fluxo()
    r = await f.iniciar(COM_CEP)
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == motivo
    assert r["mensagemFinal"] == mensagem
    # Não chega a perguntar nada: o canal fica vazio.
    assert "canal" not in await f.estado()


@pytest.mark.parametrize("entrada", [{}, {"endereco": {}}, {"endereco": {"cep": "  "}}, {"endereco": {"municipio": "Rio de Janeiro"}}])
async def test_sem_cep_encerra_sem_consultar_o_verde(monkeypatch: pytest.MonkeyPatch, entrada: dict[str, object]) -> None:
    ceps = _verde_devolve(monkeypatch, {"encontrado": True, "idMunicipio": ID_MUNICIPIO_RIO})
    r = await _fluxo().iniciar(entrada)
    assert ceps == []
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "municipio_nao_identificado"


async def test_mock_do_verde_trata_cep_00000000_como_nao_encontrado() -> None:
    r = await _fluxo().iniciar({"endereco": {"cep": "00000000"}})
    assert r["motivoHandoff"] == "municipio_nao_identificado"


FORA_DO_RIO: DadosCep = {"encontrado": True, "idMunicipio": 3000}
UNIDADE: OrgaoAtendimento = {
    "id": 1358,
    "nome": "NÚCLEO DE PRIMEIRO ATENDIMENTO CÍVEL DE NITERÓI",
    "enderecos": [
        {
            "logradouro": "Rua Visconde de Sepetiba",
            "numero": "519",
            "complemento": "3º andar",
            "bairro": "Centro",
            "municipio": "Niterói",
            "uf": "RJ",
            "horariosUrgenciaFormatado": "Seg a Sex, 11:00-17:00",
        }
    ],
}


def _verde_fora_do_rio(monkeypatch: pytest.MonkeyPatch, pessoa: DadosPessoa, orgaos: OrgaosPrimeiroAtendimento) -> list[tuple[int, int]]:
    _verde_devolve(monkeypatch, FORA_DO_RIO)
    consultas: list[tuple[int, int]] = []

    async def consultar_pessoa(cpf: str) -> DadosPessoa:
        return pessoa

    async def consultar_orgaos(id_pessoa: int, id_assunto: int) -> OrgaosPrimeiroAtendimento:
        consultas.append((id_pessoa, id_assunto))
        return orgaos

    monkeypatch.setattr("maria.fluxos.plano_saude.graph.consultar_pessoa_por_cpf", consultar_pessoa)
    monkeypatch.setattr("maria.fluxos.plano_saude.graph.consultar_orgaos_primeiro_atendimento", consultar_orgaos)
    return consultas


async def test_fora_do_rio_com_pessoa_no_verde_conclui_com_a_unidade(monkeypatch: pytest.MonkeyPatch) -> None:
    consultas = _verde_fora_do_rio(monkeypatch, {"encontrado": True, "idPessoa": 12}, {"encontrado": True, "orgaos": [UNIDADE]})
    f = _fluxo()
    r = await f.iniciar({**COM_CEP, "cpf": "11111111111"})
    assert consultas == [(12, ID_ASSUNTO_UNIDADE_FORA_DO_RIO)]
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    assert "motivoHandoff" not in r
    assert (await f.estado())["foraDoRio"] is True
    assert "CÍVEL DE NITERÓI, Rua Visconde de Sepetiba, 519 3º andar, Centro, Niterói/RJ" in r["mensagemFinal"]
    assert "Horário: Seg a Sex, 11:00-17:00" in r["mensagemFinal"]


async def test_fora_do_rio_sem_horario_no_verde_usa_o_horario_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    sem_horario: OrgaoAtendimento = {
        "id": 1,
        "nome": "NÚCLEO DE TESTE",
        "enderecos": [{"logradouro": "Rua A", "municipio": "Niterói", "uf": "RJ"}],
    }
    _verde_fora_do_rio(monkeypatch, {"encontrado": True, "idPessoa": 12}, {"encontrado": True, "orgaos": [sem_horario]})
    r = await _fluxo().iniciar({**COM_CEP, "cpf": "11111111111"})
    assert r["statusFinal"] == "concluido"
    assert f"Horário: {HORARIO_UNIDADE_PADRAO}" in r["mensagemFinal"]
    assert HORARIO_UNIDADE_PADRAO == "de segunda a sexta, das 10h às 17h"


@pytest.mark.parametrize(
    ("entrada", "pessoa", "orgaos"),
    [
        ({}, {"encontrado": True, "idPessoa": 12}, {"encontrado": True, "orgaos": [UNIDADE]}),
        ({"cpf": "11111111111"}, {"encontrado": False}, {"encontrado": True, "orgaos": [UNIDADE]}),
        ({"cpf": "11111111111"}, {"encontrado": False, "falhaInfra": True}, {"encontrado": True, "orgaos": [UNIDADE]}),
        ({"cpf": "11111111111"}, {"encontrado": True, "idPessoa": 12}, {"encontrado": False, "orgaos": []}),
        ({"cpf": "11111111111"}, {"encontrado": True, "idPessoa": 12}, {"encontrado": False, "orgaos": [], "falhaInfra": True}),
        ({"cpf": "11111111111"}, {"encontrado": True, "idPessoa": 12}, {"encontrado": True, "orgaos": [{"id": 1, "nome": "Sem endereço"}]}),
    ],
)
async def test_fora_do_rio_sem_unidade_encerra_com_a_mensagem_generica(
    monkeypatch: pytest.MonkeyPatch, entrada: dict[str, object], pessoa: DadosPessoa, orgaos: OrgaosPrimeiroAtendimento
) -> None:
    _verde_fora_do_rio(monkeypatch, pessoa, orgaos)
    r = await _fluxo().iniciar({**COM_CEP, **entrada})
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "fora_do_rio"
    assert r["mensagemFinal"] == MENSAGEM_FORA_DO_RIO


async def test_fora_do_rio_pula_orgao_sem_endereco_e_usa_o_proximo(monkeypatch: pytest.MonkeyPatch) -> None:
    _verde_fora_do_rio(
        monkeypatch,
        {"encontrado": True, "idPessoa": 12},
        {"encontrado": True, "orgaos": [{"id": 1, "nome": "Sem endereço"}, UNIDADE]},
    )
    r = await _fluxo().iniciar({**COM_CEP, "cpf": "11111111111"})
    assert r["statusFinal"] == "concluido"
    assert "NITERÓI" in r["mensagemFinal"]
    assert "Sem endereço" not in r["mensagemFinal"]


def _quebrar(monkeypatch: pytest.MonkeyPatch, alvo: str) -> None:
    def falhar(*args: object, **kwargs: object) -> None:
        raise RuntimeError("falha de teste com CPF 11111111111")

    monkeypatch.setattr(f"maria.fluxos.plano_saude.graph.{alvo}", falhar)


async def test_falha_inesperada_na_entrada_encerra_com_atendimento_humano(monkeypatch: pytest.MonkeyPatch) -> None:
    _quebrar(monkeypatch, "consultar_cep")
    f = _fluxo()
    r = await f.iniciar(COM_CEP)
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "erro_interno"
    assert r["mensagemFinal"] == MENSAGEM_ERRO_INTERNO
    assert "11111111111" not in r["mensagemFinal"]


@pytest.mark.parametrize(
    ("alvo", "respostas"),
    [
        ("interpretar_canal", ["por aqui"]),
        ("resposta_eh_sim", ["por aqui", "true"]),
        ("interpretar_renda", ["por aqui", "true", "2500"]),
    ],
)
async def test_falha_inesperada_no_meio_da_conversa_encerra_sem_perguntar_mais_nada(
    monkeypatch: pytest.MonkeyPatch, alvo: str, respostas: list[str]
) -> None:
    f = _fluxo()
    await f.iniciar({**COM_CEP, "imagensRecebidas": True, "relato": "O plano negou a minha cirurgia"})
    _quebrar(monkeypatch, alvo)
    r = await f.responder(*respostas)
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "erro_interno"
    assert r["mensagemFinal"] == MENSAGEM_ERRO_INTERNO


async def test_falha_ao_preparar_a_pergunta_encerra_com_atendimento_humano(monkeypatch: pytest.MonkeyPatch) -> None:
    f = _fluxo()
    await f.iniciar(COM_CEP)
    _quebrar(monkeypatch, "preparar_pergunta")
    r = await f.responder("por aqui")
    assert pergunta(r) is None
    assert r["motivoHandoff"] == "erro_interno"
