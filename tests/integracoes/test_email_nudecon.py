"""Cliente da função de e-mail do NUDECON (#405): contrato, tentativas com o mesmo protocolo e sigilo no log."""

import asyncio
import json

import httpx
import pytest

from maria.integracoes import email_nudecon
from maria.integracoes.email_nudecon import enviar_email_nudecon
from tests.integracoes.conftest import TransporteFalso

URL = "https://funcao.teste/"
CHAVE = "chave-ficticia-de-teste"
DADOS = {"Nome": "Fulano Fictício", "CPF": "00000000000"}
IMAGENS = {
    "carteirinhaFrente": "https://downloads.tykhe.dev/arquivos/id-frente?token=segredo-frente",
    "carteirinhaVerso": "https://downloads.tykhe.dev/arquivos/id-verso?token=segredo-verso",
}


@pytest.fixture(autouse=True)
def configurada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_NUDECON_URL", URL)
    monkeypatch.setenv("EMAIL_NUDECON_CHAVE", CHAVE)


def _responder(transporte: TransporteFalso, *respostas: httpx.Response) -> None:
    fila = list(respostas)

    async def tratador(_: httpx.Request) -> httpx.Response:
        return fila.pop(0) if len(fila) > 1 else fila[0]

    transporte.tratador = tratador


async def test_envia_protocolo_dados_e_imagens_com_a_chave(transporte: TransporteFalso) -> None:
    _responder(transporte, httpx.Response(200, json={"protocolo": "NUD-1", "idMensagem": "x", "repetido": False}))
    resultado = await enviar_email_nudecon("NUD-1", DADOS, IMAGENS)
    assert resultado.ok is True and resultado.repetido is False
    assert len(transporte.requisicoes) == 1
    requisicao = transporte.requisicoes[0]
    assert str(requisicao.url) == URL and requisicao.method == "POST"
    assert requisicao.headers["authorization"] == f"Bearer {CHAVE}"
    assert json.loads(transporte.corpos[0]) == {"protocolo": "NUD-1", "dados": DADOS, "imagens": IMAGENS}


async def test_sem_imagens_o_corpo_nao_leva_o_campo(transporte: TransporteFalso) -> None:
    _responder(transporte, httpx.Response(200, json={}))
    assert (await enviar_email_nudecon("NUD-1", DADOS, None)).ok is True
    assert "imagens" not in json.loads(transporte.corpos[0])


async def test_valor_acima_do_limite_do_contrato_e_cortado(transporte: TransporteFalso) -> None:
    _responder(transporte, httpx.Response(200, json={}))
    await enviar_email_nudecon("NUD-1", {"Situação": "a" * 2500})
    assert len(json.loads(transporte.corpos[0])["dados"]["Situação"]) == 2000


async def test_protocolo_repetido_conta_como_sucesso(transporte: TransporteFalso) -> None:
    _responder(transporte, httpx.Response(200, json={"protocolo": "NUD-1", "idMensagem": "x", "repetido": True}))
    resultado = await enviar_email_nudecon("NUD-1", DADOS)
    assert resultado.ok is True and resultado.repetido is True


async def test_5xx_e_repetido_com_o_mesmo_protocolo_ate_dar_certo(transporte: TransporteFalso) -> None:
    _responder(
        transporte,
        httpx.Response(502, json={"erro": "ses"}),
        httpx.Response(409, json={"erro": "em andamento"}),
        httpx.Response(200, json={}),
    )
    resultado = await enviar_email_nudecon("NUD-1", DADOS)
    assert resultado.ok is True
    assert len(transporte.requisicoes) == 3
    assert {json.loads(corpo)["protocolo"] for corpo in transporte.corpos} == {"NUD-1"}


async def test_5xx_nas_tres_tentativas_falha(transporte: TransporteFalso) -> None:
    _responder(transporte, httpx.Response(500, json={"erro": "x"}))
    resultado = await enviar_email_nudecon("NUD-1", DADOS)
    assert resultado.ok is False and resultado.motivo == "http_500"
    assert len(transporte.requisicoes) == email_nudecon.TENTATIVAS


@pytest.mark.parametrize("status", [400, 401, 413])
async def test_4xx_nao_e_repetido(transporte: TransporteFalso, status: int) -> None:
    _responder(transporte, httpx.Response(status, json={"erro": "x"}))
    resultado = await enviar_email_nudecon("NUD-1", DADOS)
    assert resultado.ok is False and resultado.motivo == f"http_{status}"
    assert len(transporte.requisicoes) == 1


async def test_falha_de_rede_e_repetida_e_depois_falha(transporte: TransporteFalso) -> None:
    async def cair(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede")

    transporte.tratador = cair
    resultado = await enviar_email_nudecon("NUD-1", DADOS)
    assert resultado.ok is False and resultado.motivo == "rede"
    assert len(transporte.requisicoes) == email_nudecon.TENTATIVAS


async def test_prazo_da_tentativa_estourado_falha(transporte: TransporteFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_nudecon, "PRAZO_TENTATIVA_S", 0.01)

    async def demorar(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    transporte.tratador = demorar
    resultado = await enviar_email_nudecon("NUD-1", DADOS)
    assert resultado.ok is False and resultado.motivo == "prazo"


@pytest.mark.parametrize("faltando", ["EMAIL_NUDECON_URL", "EMAIL_NUDECON_CHAVE"])
async def test_sem_url_ou_chave_nao_chama_e_falha(transporte: TransporteFalso, monkeypatch: pytest.MonkeyPatch, faltando: str) -> None:
    monkeypatch.delenv(faltando)
    resultado = await enviar_email_nudecon("NUD-1", DADOS, IMAGENS)
    assert resultado.ok is False and resultado.motivo == "nao_configurado"
    assert transporte.requisicoes == []


async def test_log_sem_dados_urls_nem_chave(transporte: TransporteFalso, capsys: pytest.CaptureFixture[str]) -> None:
    _responder(transporte, httpx.Response(502, json={"erro": "Fulano Fictício"}), httpx.Response(200, json={}))
    await enviar_email_nudecon("NUD-1", DADOS, IMAGENS)
    saida = capsys.readouterr()
    texto = saida.out + saida.err
    assert "NUD-1" in texto
    for segredo in (CHAVE, "segredo-frente", "segredo-verso", "id-frente", "Fulano", "00000000000"):
        assert segredo not in texto
