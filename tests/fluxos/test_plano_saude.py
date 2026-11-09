"""Fluxo Problemas com plano de saúde (NUDECON, #329): "para quem", imagens, renda e confirmação (sem pergunta do canal, #430)."""

import json
from typing import Any, get_args

import pytest

from maria.fluxos.plano_saude.api import (
    MENSAGEM_CPF_OUTRA_INVALIDO,
    MENSAGEM_CPF_OUTRA_NAO_ENCONTRADO,
    MENSAGEM_ERRO_INTERNO,
    MENSAGEM_FALHA_ENVIO_EMAIL,
    MENSAGEM_FALHA_INFRA_VERDE,
    MENSAGEM_IMAGENS_NAO_ANEXADAS,
)
from maria.fluxos.plano_saude.graph import interpretar_renda, montar_resumo, obter_grafo
from maria.fluxos.plano_saude.state import MotivoHandoffPlanoSaude
from maria.integracoes.email_nudecon import ResultadoEmail
from maria.shared.types import DadosPessoa
from tests.fluxos.conftest import Fluxo, pergunta, texto

# Sem CEP o fluxo nem começa (#331); o mock do Verde devolve o Rio para qualquer CEP que não seja "00000000".
COM_CEP = {"endereco": {"cep": "20000000"}}


def _fluxo() -> Fluxo:
    return Fluxo(obter_grafo(), "teste-plano-saude")


async def test_primeira_pergunta_e_para_quem_e_nao_tem_mais_o_canal() -> None:
    r = await _fluxo().iniciar(COM_CEP)
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao" and p["opcoes"] == ["Sim", "Não"]
    assert "para você" in texto(r)
    for fora in ("por aqui", "por e-mail", "presencial", "das 11h às 16h"):
        assert fora not in texto(r).lower()
    assert "canal" not in await _fluxo_estado(COM_CEP)


async def _fluxo_estado(entrada: dict[str, Any]) -> dict[str, Any]:
    f = _fluxo()
    await f.iniciar(entrada)
    return dict(await f.estado())


# ── Outra pessoa (#433): CPF dela, dados do Verde e o resto do fluxo ────────────────────────────────────────────────
CPF_OUTRA = "52998224725"
PESSOA_DO_VERDE: DadosPessoa = {
    "encontrado": True,
    "idPessoa": 4436248,
    "nome": "MARIA DE TESTE FICTICIA",
    "endereco": "Rua Fictícia, nº 2, Centro, Niterói - RJ, CEP. 24020-005",
    "dataNascimento": "02/02/1991",
    "email": "maria@exemplo.org",
    "telefonesAssistido": [
        {"numeroTelefone": "21988880000", "inWhatsapp": False, "tipo": "Fixo"},
        {"numeroTelefone": "21977770000", "inWhatsapp": True, "tipo": "Celular"},
    ],
}


def _verde_pessoa(monkeypatch: pytest.MonkeyPatch, *respostas: DadosPessoa) -> list[tuple[str, bool]]:
    """Cada consulta devolve a próxima resposta (a última se repete). Registra (cpf, completo)."""
    consultas: list[tuple[str, bool]] = []
    fila = list(respostas)

    async def consultar(cpf: str, *, completo: bool = False) -> DadosPessoa:
        consultas.append((cpf, completo))
        return fila.pop(0) if len(fila) > 1 else fila[0]

    monkeypatch.setattr("maria.fluxos.plano_saude.graph.consultar_pessoa_por_cpf", consultar)
    return consultas


async def test_nao_a_para_quem_pergunta_o_cpf_da_outra_pessoa_e_nao_encerra() -> None:
    f = _fluxo()
    await f.iniciar(COM_CEP)
    r = await f.responder("false")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "texto"
    assert "CPF da pessoa que será atendida" in texto(r)
    assert "statusFinal" not in r
    assert (await f.estado())["paraSi"] is False


async def test_outra_pessoa_encontrada_segue_o_fluxo_normal_com_os_dados_do_verde(monkeypatch: pytest.MonkeyPatch) -> None:
    consultas = _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    chamadas = _email_devolve(monkeypatch, True)
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("false", "529.982.247-25")
    assert consultas == [(CPF_OUTRA, True)], "CPF só com dígitos, e a consulta completa"
    assert "o que aconteceu" not in texto(r) and "renda" in texto(r), "relato já veio e imagens já estavam: vai à renda"
    r = await f.responder("2500")
    resumo = texto(r)
    # Os dados dela, do Verde, no lugar dos de quem pede.
    assert "Nome: MARIA DE TESTE FICTICIA" in resumo and f"CPF: {CPF_OUTRA}" in resumo
    assert "Data de nascimento: 02/02/1991" in resumo and "E-mail: maria@exemplo.org" in resumo
    assert "Telefone: 21988880000" in resumo and "WhatsApp: 21977770000" in resumo
    assert "Endereço: Rua Fictícia, nº 2, Centro, Niterói - RJ, CEP. 24020-005" in resumo, "o endereço dela vem do Verde"
    assert "Atendimento para: outra pessoa" in resumo
    for de_quem_pede in ("Pessoa de Teste", "00000000000", "teste@exemplo.org", "21999990000"):
        assert de_quem_pede not in resumo
    r = await f.responder("sim")
    assert (r["statusFinal"], r["destino"]) == ("concluido", "email_enviado")
    [(_, dados, _)] = chamadas
    assert dados["Nome"] == "MARIA DE TESTE FICTICIA" and dados["CPF"] == CPF_OUTRA and dados["WhatsApp"] == "21977770000"
    assert dados["Atendimento para"] == "outra pessoa (dados do cadastro do Verde)"
    assert dados["Endereço"] == "Rua Fictícia, nº 2, Centro, Niterói - RJ, CEP. 24020-005"


async def test_outra_pessoa_pede_as_imagens_e_a_situacao_quando_faltam(monkeypatch: pytest.MonkeyPatch) -> None:
    _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    f = _fluxo()
    await f.iniciar({k: v for k, v in DADOS.items() if k != "relato"})
    r = await f.responder("false", CPF_OUTRA)
    p = pergunta(r)
    assert p is not None and p["tipo"] == "link_imagem" and p["tipoImagem"] == "carteirinha_frente"
    r = await f.responder(LINK_FRENTE, LINK_VERSO)
    assert "o que aconteceu" in texto(r)


async def test_campo_que_o_verde_nao_trouxe_fica_nao_informado_sem_cair_nos_dados_de_quem_pede(monkeypatch: pytest.MonkeyPatch) -> None:
    _verde_pessoa(monkeypatch, {"encontrado": True, "idPessoa": 1, "nome": "SO NOME", "dataNascimento": "01/01/1990"})
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("false", CPF_OUTRA, "2500")
    resumo = texto(r)
    assert "Nome: SO NOME" in resumo
    for rotulo in ("E-mail", "Telefone", "WhatsApp", "Endereço"):
        assert f"{rotulo}: não informado" in resumo


@pytest.mark.parametrize("cpf_errado", ["123", "abc", "123456789012", ""])
async def test_cpf_com_formato_invalido_repete_e_no_terceiro_erro_vai_ao_atendimento_humano(
    monkeypatch: pytest.MonkeyPatch, cpf_errado: str
) -> None:
    consultas = _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    f = _fluxo()
    await f.iniciar(COM_CEP)
    r = await f.responder("false", cpf_errado)
    assert pergunta(r) is not None and "Não entendi esse CPF" in texto(r)
    r = await f.responder(cpf_errado)
    assert pergunta(r) is not None
    r = await f.responder(cpf_errado)
    assert pergunta(r) is None
    assert (r["statusFinal"], r["motivoHandoff"]) == ("handoff_humano", "cpf_outra_pessoa_invalido")
    assert r["mensagemFinal"] == MENSAGEM_CPF_OUTRA_INVALIDO
    assert consultas == [], "formato inválido nunca chega ao Verde"


async def test_cpf_invalido_e_depois_certo_na_segunda_tentativa_segue(monkeypatch: pytest.MonkeyPatch) -> None:
    _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    await f.responder("false", "123")
    r = await f.responder(CPF_OUTRA)
    assert "renda" in texto(r)


async def test_cpf_nao_encontrado_repete_e_no_terceiro_vai_ao_atendimento_humano(monkeypatch: pytest.MonkeyPatch) -> None:
    consultas = _verde_pessoa(monkeypatch, {"encontrado": False})
    f = _fluxo()
    await f.iniciar(COM_CEP)
    r = await f.responder("false", CPF_OUTRA)
    assert pergunta(r) is not None and "Não encontrei esse CPF" in texto(r)
    r = await f.responder(CPF_OUTRA)
    assert pergunta(r) is not None
    r = await f.responder(CPF_OUTRA)
    assert pergunta(r) is None
    assert (r["statusFinal"], r["motivoHandoff"]) == ("handoff_humano", "cpf_outra_pessoa_nao_encontrado")
    assert r["mensagemFinal"] == MENSAGEM_CPF_OUTRA_NAO_ENCONTRADO
    assert len(consultas) == 3


async def test_cpf_nao_encontrado_e_depois_encontrado_segue(monkeypatch: pytest.MonkeyPatch) -> None:
    _verde_pessoa(monkeypatch, {"encontrado": False}, PESSOA_DO_VERDE)
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    await f.responder("false", CPF_OUTRA)
    r = await f.responder(CPF_OUTRA)
    assert "renda" in texto(r)


async def test_verde_fora_do_ar_na_consulta_da_outra_pessoa_vai_ao_atendimento_humano(monkeypatch: pytest.MonkeyPatch) -> None:
    consultas = _verde_pessoa(monkeypatch, {"encontrado": False, "falhaInfra": True})
    f = _fluxo()
    await f.iniciar(COM_CEP)
    r = await f.responder("false", CPF_OUTRA)
    assert pergunta(r) is None
    assert (r["statusFinal"], r["motivoHandoff"]) == ("handoff_humano", "falha_infra_verde")
    assert r["mensagemFinal"] == MENSAGEM_FALHA_INFRA_VERDE
    assert len(consultas) == 1, "falha de infra não repete a pergunta"


async def test_dados_da_outra_pessoa_nao_vao_para_metadados_nem_para_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from maria.fluxos.plano_saude.api import extrair_metadados_plano_saude

    _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    await f.responder("false", CPF_OUTRA)
    estado = await f.estado()
    metadados = json.dumps(extrair_metadados_plano_saude(estado), ensure_ascii=False)
    for dado in (CPF_OUTRA, "MARIA DE TESTE", "maria@exemplo.org", "21977770000", "Niterói"):
        assert dado not in metadados
    saida = capsys.readouterr().out
    for dado in (CPF_OUTRA, "MARIA DE TESTE", "maria@exemplo.org", "21977770000", "21988880000", "Niterói", "02/02/1991"):
        assert dado not in saida


async def test_o_endereco_de_quem_fala_nao_vai_para_log_nem_para_metadados(capsys: pytest.CaptureFixture[str]) -> None:
    from maria.fluxos.plano_saude.api import extrair_metadados_plano_saude

    f = _fluxo()
    await f.iniciar(
        {**DADOS, "imagensRecebidas": True, "endereco": {"cep": "24020005", "logradouro": "Rua Sigilosa", "municipio": "Niterói"}}
    )
    await f.responder("true", "2500")
    estado = await f.estado()
    assert "Rua Sigilosa" not in json.dumps(extrair_metadados_plano_saude(estado), ensure_ascii=False)
    saida = capsys.readouterr().out
    for dado in ("Rua Sigilosa", "24020005", "Niterói"):
        assert dado not in saida


async def test_para_outra_pessoa_o_email_leva_nome_e_cpf_do_solicitante_e_o_resumo_nao(monkeypatch: pytest.MonkeyPatch) -> None:
    # #444: o NUDECON precisa saber quem pediu; o resumo mostrado a quem pede não muda.
    _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    chamadas = _email_devolve(monkeypatch, True)
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("false", CPF_OUTRA, "2500")
    assert "Solicitante" not in texto(r)
    await f.responder("sim")
    [(_, dados, _)] = chamadas
    assert dados["Solicitante - Nome"] == "Pessoa de Teste" and dados["Solicitante - CPF"] == "00000000000"
    assert dados["Nome"] == "MARIA DE TESTE FICTICIA" and dados["CPF"] == CPF_OUTRA
    assert list(dados)[:3] == ["Atendimento para", "Solicitante - Nome", "Solicitante - CPF"]


async def test_solicitante_sem_nome_e_cpf_vai_como_nao_informado_sem_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    chamadas = _email_devolve(monkeypatch, True)
    f = _fluxo()
    await f.iniciar({k: v for k, v in {**DADOS, "imagensRecebidas": True}.items() if k not in ("nome", "cpf")})
    await f.responder("false", CPF_OUTRA, "2500")
    r = await f.responder("sim")
    assert (r["statusFinal"], r["destino"]) == ("concluido", "email_enviado")
    [(_, dados, _)] = chamadas
    assert dados["Solicitante - Nome"] == dados["Solicitante - CPF"] == "não informado"


async def test_nome_e_cpf_do_solicitante_nao_vao_para_metadados_nem_para_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from maria.fluxos.plano_saude.api import extrair_metadados_plano_saude

    _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    _email_devolve(monkeypatch, True)
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    await f.responder("false", CPF_OUTRA, "2500", "sim")
    estado = await f.estado()
    metadados = json.dumps(extrair_metadados_plano_saude(estado), ensure_ascii=False)
    saida = capsys.readouterr().out
    for dado in ("Pessoa de Teste", "00000000000"):
        assert dado not in metadados and dado not in saida


async def test_quem_fala_por_si_nao_muda(monkeypatch: pytest.MonkeyPatch) -> None:
    consultas = _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("true", "2500")
    assert consultas == []
    assert "Nome: Pessoa de Teste" in texto(r) and "Atendimento para" not in texto(r)
    chamadas = _email_devolve(monkeypatch, True)
    await f.responder("sim")
    assert not any(rotulo.startswith("Solicitante") for rotulo in chamadas[0][1]), "para si, sem linhas de solicitante"


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


LINK_FRENTE = "https://downloads.tykhe.dev/arquivos/id-frente-fake?token=token-frente-fake"
LINK_VERSO = "https://downloads.tykhe.dev/arquivos/id-verso-fake?token=token-verso-fake"


async def test_para_mim_sem_aviso_das_imagens_pede_a_frente_da_carteirinha() -> None:
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("true")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "link_imagem" and p["tipoImagem"] == "carteirinha_frente"
    assert "frente" in texto(r)
    assert (await f.estado())["paraSi"] is True


async def test_depois_da_frente_pede_o_verso_e_guarda_os_links() -> None:
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("true", LINK_FRENTE)
    p = pergunta(r)
    assert p is not None and p["tipo"] == "link_imagem" and p["tipoImagem"] == "carteirinha_verso"
    r = await f.responder(LINK_VERSO)
    assert "renda" in texto(r)
    estado = await f.estado()
    assert estado["imagensRecebidas"] is True
    assert estado["imagensLinks"] == {"carteirinhaFrente": LINK_FRENTE, "carteirinhaVerso": LINK_VERSO}


@pytest.mark.parametrize(
    "resposta",
    [
        "true",
        "já enviei",
        "http://downloads.tykhe.dev/arquivos/x?token=y",
        "https://outro-dominio.com/arquivos/x?token=y",
        "https://downloads.tykhe.dev.malicioso.com/arquivos/x?token=y",
        "https://usuario:senha@downloads.tykhe.dev/arquivos/x?token=y",
        "https://downloads.tykhe.dev/arquivos/x token=y",
        "https://downloads.tykhe.dev:8443/arquivos/x?token=y",
        "https://downloads.tykhe.dev/outro/x?token=y",
        "https://downloads.tykhe.dev/arquivos/",
    ],
)
async def test_resposta_que_nao_e_link_permitido_repete_a_pergunta_sem_guardar(resposta: str) -> None:
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("true", resposta)
    p = pergunta(r)
    assert p is not None and p["tipoImagem"] == "carteirinha_frente"
    assert "Não recebi" in texto(r)
    assert not (await f.estado()).get("imagensLinks")


async def test_com_imagens_recebidas_pula_direto_para_a_renda() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("true")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "texto"
    assert "renda" in texto(r)


async def test_imagens_invalidas_tres_vezes_encerram_com_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("true", "não")
    assert "Não recebi" in texto(r)
    r = await f.responder("não", "não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "imagens_pendentes"


async def test_imagens_enviadas_seguem_para_a_renda() -> None:
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("true", LINK_FRENTE, LINK_VERSO)
    assert "renda" in texto(r)
    assert (await f.estado())["imagensRecebidas"] is True


async def test_renda_invalida_repete_e_na_terceira_encerra() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("true", "muita")
    assert "Não entendi" in texto(r)
    r = await f.responder("-50", "nada")
    assert pergunta(r) is None
    assert r["motivoHandoff"] == "renda_nao_entendida"


async def test_sem_relato_pergunta_a_situacao_antes_da_renda() -> None:
    f = _fluxo()
    await f.iniciar({k: v for k, v in DADOS.items() if k != "relato"} | {"imagensRecebidas": True})
    r = await f.responder("true")
    p = pergunta(r)
    assert p is not None and p["tipo"] == "texto"
    assert "o que aconteceu" in texto(r)
    r = await f.responder("O plano negou a minha cirurgia")
    assert "renda" in texto(r)
    assert (await f.estado())["relato"] == "O plano negou a minha cirurgia"


async def test_com_relato_nao_pergunta_a_situacao() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("true")
    assert "o que aconteceu" not in texto(r)
    assert "renda" in texto(r)


async def test_situacao_com_menos_de_tres_palavras_repete_e_na_terceira_encerra() -> None:
    f = _fluxo()
    await f.iniciar({k: v for k, v in DADOS.items() if k != "relato"} | {"imagensRecebidas": True})
    r = await f.responder("true", "ajuda")
    assert "um pouco mais de detalhe" in texto(r)
    r = await f.responder("negaram tudo", "")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "situacao_nao_informada"


async def test_situacao_pergunta_depois_das_imagens_quando_sem_aviso() -> None:
    f = _fluxo()
    await f.iniciar({k: v for k, v in DADOS.items() if k != "relato"})
    r = await f.responder("true", LINK_FRENTE, LINK_VERSO)
    assert "o que aconteceu" in texto(r)


async def test_resumo_mostra_os_dados_como_vieram_e_a_renda() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("true", "R$ 2.500,00")
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
    r = await f.responder("true", "2500", "sim")
    assert pergunta(r) is None
    assert r["statusFinal"] == "concluido"
    estado = await f.estado()
    assert (estado["renda"], estado["confirmado"]) == (2500.0, True)


async def test_nao_confirmar_volta_para_a_renda_e_conserva_o_resto() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("true", "2500", "não")
    assert "Vamos corrigir" in texto(r)
    r = await f.responder("3000")
    assert "Renda mensal: R$ 3.000,00" in texto(r)
    estado = await f.estado()
    assert (estado["paraSi"], estado["cpf"]) == (True, "00000000000")


async def test_tres_nao_na_confirmacao_encerram_com_atendimento_humano() -> None:
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("true", "2500", "não", "2500", "não", "2500", "não")
    assert pergunta(r) is None
    assert r["statusFinal"] == "handoff_humano"
    assert r["motivoHandoff"] == "dados_nao_confirmados"


async def test_dados_conhecidos_viram_estado_e_chave_desconhecida_e_ignorada() -> None:
    f = _fluxo()
    await f.iniciar({"cpf": "00000000000", "nome": "Fulano de Tal", "endereco": {"uf": "RJ"}, "chaveQueNaoExiste": "x"})
    estado = await f.estado()
    assert estado["cpf"] == "00000000000"
    assert estado["endereco"] == {"uf": "RJ"}
    assert "chaveQueNaoExiste" not in estado


# ── Sem verificação de município e sem endereço (#439) ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "entrada",
    [
        {},
        {"endereco": {}},
        COM_CEP,
        {"endereco": {"cep": "24020005", "municipio": "Niterói", "uf": "RJ"}},
        {"cpf": "11111111111", "endereco": {"cep": "00000000"}},
    ],
    ids=["sem endereço", "endereço vazio", "CEP do Rio", "CEP de outro município", "CEP que o Verde não acha"],
)
async def test_o_fluxo_comeca_direto_em_para_voce_com_ou_sem_endereco_e_de_qualquer_municipio(
    monkeypatch: pytest.MonkeyPatch, entrada: dict[str, Any]
) -> None:
    consultas = _verde_pessoa(monkeypatch, PESSOA_DO_VERDE)
    r = await _fluxo().iniciar(entrada)
    p = pergunta(r)
    assert p is not None and p["tipo"] == "sim_nao" and "para você" in texto(r)
    assert "statusFinal" not in r
    assert consultas == [], "nenhuma consulta ao Verde antes da primeira pergunta"


async def test_o_endereco_de_quem_fala_continua_no_estado_e_os_motivos_de_municipio_nao_existem_mais() -> None:
    estado = await _fluxo_estado({**DADOS, "endereco": {"cep": "20040020", "municipio": "Rio de Janeiro"}})
    assert estado["endereco"] == {"cep": "20040020", "municipio": "Rio de Janeiro"}
    assert "foraDoRio" not in estado
    motivos = get_args(MotivoHandoffPlanoSaude)
    for removido in ("fora_do_rio", "municipio_nao_identificado", "outra_pessoa", "canal_nao_entendido"):
        assert removido not in motivos


async def test_quem_mora_fora_do_rio_segue_o_fluxo_normal_ate_o_e_mail_com_o_endereco_que_a_tykhe_mandou(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chamadas = _email_devolve(monkeypatch, True)
    endereco = {"cep": "24020005", "logradouro": "Rua Fictícia", "numero": "10", "municipio": "Niterói", "uf": "RJ"}
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True, "endereco": endereco})
    r = await f.responder("true", "2500")
    assert "Endereço: Rua Fictícia, 10, Niterói/RJ, CEP 24020005" in texto(r), "o município não decide nada: só aparece"
    r = await f.responder("sim")
    assert (r["statusFinal"], r["destino"]) == ("concluido", "email_enviado")
    [(_, dados, _)] = chamadas
    assert dados["Endereço"] == "Rua Fictícia, 10, Niterói/RJ, CEP 24020005"


async def test_sem_endereco_o_resumo_e_o_e_mail_mostram_nao_informado_sem_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _email_devolve(monkeypatch, True)
    f = _fluxo()
    await f.iniciar({k: v for k, v in DADOS.items() if k != "endereco"} | {"imagensRecebidas": True})
    r = await f.responder("true", "2500")
    assert "Endereço: não informado" in texto(r)
    r = await f.responder("sim")
    assert (r["statusFinal"], r["destino"]) == ("concluido", "email_enviado")
    assert chamadas[0][1]["Endereço"] == "não informado"


def _quebrar(monkeypatch: pytest.MonkeyPatch, alvo: str) -> None:
    def falhar(*args: object, **kwargs: object) -> None:
        raise RuntimeError("falha de teste com CPF 11111111111")

    monkeypatch.setattr(f"maria.fluxos.plano_saude.graph.{alvo}", falhar)


async def test_falha_inesperada_na_entrada_encerra_com_atendimento_humano(monkeypatch: pytest.MonkeyPatch) -> None:
    _quebrar(monkeypatch, "preparar_pergunta")
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
        ("resposta_eh_sim", ["true"]),
        ("interpretar_renda", ["true", "2500"]),
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
    r = await f.responder("true")
    assert pergunta(r) is None
    assert r["motivoHandoff"] == "erro_interno"


async def test_tentativas_de_imagem_zeram_a_cada_imagem_recebida() -> None:
    f = _fluxo()
    await f.iniciar(DADOS)
    await f.responder("true", "oi", "oi")
    r = await f.responder(LINK_FRENTE)
    assert pergunta(r)["tipoImagem"] == "carteirinha_verso"  # type: ignore[index]
    assert (await f.estado())["tentativasImagens"] == 0


# ── #405: a Maria chama a Lambda de e-mail ao concluir ──────────────────────────────────────────────────────────
def _email_devolve(
    monkeypatch: pytest.MonkeyPatch, enviado: bool, anexos_falhos: int = 0
) -> list[tuple[str, dict[str, str], dict[str, str]]]:
    chamadas: list[tuple[str, dict[str, str], dict[str, str]]] = []

    async def enviar(protocolo: str, dados: dict[str, str], imagens: dict[str, str]) -> ResultadoEmail:
        chamadas.append((protocolo, dados, imagens))
        return ResultadoEmail(enviado, anexos_falhos)

    monkeypatch.setattr("maria.fluxos.plano_saude.graph.enviar_email_nudecon", enviar)
    return chamadas


async def test_concluir_envia_o_e_mail_com_os_dados_e_os_links_antes_de_devolver_email_enviado(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _email_devolve(monkeypatch, True)
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("true", LINK_FRENTE, LINK_VERSO, "Preciso de um remédio", "2500", "sim")
    assert (r["statusFinal"], r["destino"]) == ("concluido", "email_enviado")
    [(protocolo, dados, imagens)] = chamadas
    assert protocolo.startswith("NUD-")
    assert dados["Renda mensal"] == "R$ 2.500,00"
    assert dados["Nome"] == DADOS["nome"]
    assert imagens == {"carteirinhaFrente": LINK_FRENTE, "carteirinhaVerso": LINK_VERSO}


async def test_falha_no_envio_do_e_mail_encerra_com_atendimento_humano_sem_destino(monkeypatch: pytest.MonkeyPatch) -> None:
    _email_devolve(monkeypatch, False)
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("true", "2500", "sim")
    assert (r["statusFinal"], r["motivoHandoff"]) == ("handoff_humano", "falha_envio_email")
    assert r["mensagemFinal"] == MENSAGEM_FALHA_ENVIO_EMAIL
    assert r.get("destino") is None


async def test_email_enviado_com_imagem_nao_anexada_vai_ao_atendimento_humano(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _email_devolve(monkeypatch, True, anexos_falhos=2)
    f = _fluxo()
    await f.iniciar(DADOS)
    r = await f.responder("true", LINK_FRENTE, LINK_VERSO, "Preciso de um remédio", "2500", "sim")
    assert (r["statusFinal"], r["motivoHandoff"]) == ("handoff_humano", "imagens_nao_anexadas")
    assert r["mensagemFinal"] == MENSAGEM_IMAGENS_NAO_ANEXADAS
    assert r.get("destino") is None
    assert len(chamadas) == 1, "o e-mail com os dados saiu uma vez"


async def test_email_enviado_sem_falha_de_imagem_segue_concluido(monkeypatch: pytest.MonkeyPatch) -> None:
    _email_devolve(monkeypatch, True, anexos_falhos=0)
    f = _fluxo()
    await f.iniciar({**DADOS, "imagensRecebidas": True})
    r = await f.responder("true", "2500", "sim")
    assert (r["statusFinal"], r["destino"]) == ("concluido", "email_enviado")
