"""E-mail ao NUDECON pela Lambda `maria-email-nudecon` (#405): contrato da chamada, falhas e privacidade."""

import json

import httpx
import pytest

from maria.integracoes import email_nudecon
from maria.integracoes.email_nudecon import ResultadoEmail, enviar_email_nudecon, protocolo_do_atendimento
from tests.integracoes.conftest import TransporteFalso

LINK = "https://downloads.tykhe.dev/arquivos/abc?token=segredo-do-link"
DADOS = {"Nome": "Fulano de Tal", "CPF": "11111111111"}
IMAGENS = {"carteirinhaFrente": LINK, "carteirinhaVerso": LINK}


def test_protocolo_e_estavel_valido_e_nao_revela_o_chat_id() -> None:
    protocolo = protocolo_do_atendimento("chat-123")
    assert protocolo == protocolo_do_atendimento("chat-123")
    assert protocolo != protocolo_do_atendimento("chat-124")
    assert protocolo.startswith("NUD-") and len(protocolo) == 16
    assert "chat-123" not in protocolo


async def test_monta_a_chamada_do_contrato_da_lambda(email_real: TransporteFalso) -> None:
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is True
    [req] = email_real.requisicoes
    assert str(req.url) == "https://email.teste/"
    assert req.headers["authorization"] == "Bearer chave-de-teste"
    assert json.loads(email_real.corpos[0]) == {"protocolo": "NUD-0001", "dados": DADOS, "imagens": IMAGENS}


async def test_sem_imagens_o_campo_nao_vai(email_real: TransporteFalso) -> None:
    assert (await enviar_email_nudecon("NUD-0001", DADOS, {})).enviado is True
    assert "imagens" not in json.loads(email_real.corpos[0])


async def test_protocolo_repetido_conta_como_enviado(email_real: TransporteFalso) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"protocolo": "NUD-0001", "idMensagem": "x", "repetido": True})

    email_real.tratador = tratar
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is True


@pytest.mark.parametrize("status", [400, 401, 409, 413, 500, 502])
async def test_resposta_de_erro_da_funcao_nao_conta_como_enviado(email_real: TransporteFalso, status: int) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"erro": "x"})

    email_real.tratador = tratar
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is False


async def test_falha_de_rede_nunca_lanca(email_real: TransporteFalso) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede")

    email_real.tratador = tratar
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is False


async def test_prazo_esgotado_nao_conta_como_enviado(email_real: TransporteFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        raise TimeoutError

    monkeypatch.setattr(email_nudecon, "TIMEOUT_EMAIL_NUDECON_S", 0.05)
    email_real.tratador = tratar
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is False


async def test_log_nao_leva_dados_link_nem_chave(email_real: TransporteFalso, capsys: pytest.CaptureFixture[str]) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"erro": f"{LINK} Fulano de Tal"})

    email_real.tratador = tratar
    await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)
    saida = capsys.readouterr().out
    for segredo in ("segredo-do-link", "downloads.tykhe.dev", "Fulano", "11111111111", "chave-de-teste"):
        assert segredo not in saida
    linhas = [json.loads(x) for x in saida.splitlines() if x.strip()]
    assert len(linhas) == email_nudecon.TENTATIVAS_EMAIL_NUDECON  # 502 é repetido
    assert {(x["evento"], x["protocolo"], x["status"]) for x in linhas} == {("email_nudecon_falha", "NUD-0001", 502)}


async def test_modo_mock_sem_url_ou_chave_nao_chama_a_funcao(transporte: TransporteFalso, capsys: pytest.CaptureFixture[str]) -> None:
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is True
    assert transporte.requisicoes == []
    [linha] = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert linha["evento"] == "email_nudecon_mock"
    assert "segredo-do-link" not in json.dumps(linha)


async def test_fora_dos_testes_sem_configuracao_conta_como_falha(
    transporte: TransporteFalso, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("APP_ENV")
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is False
    assert transporte.requisicoes == []
    [linha] = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert (linha["evento"], linha["motivo"]) == ("email_nudecon_falha", "sem_configuracao")


def _responder(email_real: TransporteFalso, *respostas: httpx.Response) -> None:
    fila = list(respostas)

    async def tratar(_req: httpx.Request) -> httpx.Response:
        return fila.pop(0) if len(fila) > 1 else fila[0]

    email_real.tratador = tratar


async def test_5xx_e_409_sao_repetidos_com_o_mesmo_protocolo_ate_dar_certo(email_real: TransporteFalso) -> None:
    _responder(
        email_real,
        httpx.Response(502, json={"erro": "ses"}),
        httpx.Response(409, json={"erro": "em andamento"}),
        httpx.Response(200, json={}),
    )
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is True
    assert len(email_real.requisicoes) == 3
    assert {json.loads(corpo)["protocolo"] for corpo in email_real.corpos} == {"NUD-0001"}


async def test_5xx_nas_tres_tentativas_falha(email_real: TransporteFalso) -> None:
    _responder(email_real, httpx.Response(500, json={"erro": "x"}))
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is False
    assert len(email_real.requisicoes) == email_nudecon.TENTATIVAS_EMAIL_NUDECON


@pytest.mark.parametrize("status", [400, 401, 413])
async def test_4xx_nao_e_repetido(email_real: TransporteFalso, status: int) -> None:
    _responder(email_real, httpx.Response(status, json={"erro": "x"}))
    assert (await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)).enviado is False
    assert len(email_real.requisicoes) == 1


# ── #423: anexosFalhos da resposta da função ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("corpo", "esperado"),
    [
        ({"protocolo": "NUD-0001", "anexos": 0, "anexosFalhos": 2}, 2),
        ({"protocolo": "NUD-0001", "anexos": 2, "anexosFalhos": 0}, 0),
        ({"protocolo": "NUD-0001", "repetido": True}, 0),  # protocolo repetido e função antiga: sem o campo
        ({"anexosFalhos": "2"}, 0),
        ({"anexosFalhos": True}, 0),
        ({"anexosFalhos": -1}, 0),
        ([1, 2], 0),
    ],
)
async def test_anexos_falhos_vem_do_corpo_da_resposta_e_o_invalido_conta_como_zero(
    email_real: TransporteFalso, corpo: object, esperado: int
) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=corpo)

    email_real.tratador = tratar

    assert await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS) == ResultadoEmail(True, esperado)


async def test_corpo_que_nao_e_json_conta_como_zero_falhos(email_real: TransporteFalso) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    email_real.tratador = tratar

    assert await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS) == ResultadoEmail(True, 0)


async def test_log_leva_a_contagem_de_anexos_falhos_sem_link(email_real: TransporteFalso, capsys: pytest.CaptureFixture[str]) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"anexos": 0, "anexosFalhos": 2})

    email_real.tratador = tratar
    await enviar_email_nudecon("NUD-0001", DADOS, IMAGENS)

    saida = capsys.readouterr().out
    [linha] = [json.loads(x) for x in saida.splitlines() if x.strip()]
    assert (linha["evento"], linha["anexosFalhos"]) == ("email_nudecon_enviado", 2)
    assert "segredo-do-link" not in saida and "downloads.tykhe.dev" not in saida
