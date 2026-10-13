"""WhatsApp: testes novos 15 e 16 da spec do módulo integracoes (#219)."""

import json

import httpx
import pytest

from maria.integracoes import whatsapp
from maria.integracoes.whatsapp import enviar_mensagem_whatsapp, extrair_mensagem_whatsapp, extrair_status_whatsapp
from tests.integracoes.conftest import TransporteFalso


def _payload(**valor: object) -> dict[str, object]:
    return {"entry": [{"changes": [{"value": valor}]}]}


def test_15_extracao_tolera_estruturas_estranhas_nos_niveis_com_encadeamento_opcional() -> None:
    assert extrair_mensagem_whatsapp({"entry": [None, 1, {"changes": "x"}]}) is None
    assert extrair_mensagem_whatsapp(None) is None
    assert extrair_mensagem_whatsapp("texto") is None
    assert extrair_status_whatsapp({"entry": [{"changes": [None, {"value": None}]}]}) is None


def test_15_so_o_primeiro_item_de_cada_change_conta() -> None:
    payload = _payload(messages=[{"type": "audio", "from": "5521"}, {"type": "text", "from": "5521", "text": {"body": "oi"}}])
    assert extrair_mensagem_whatsapp(payload) is None
    valido = {
        "entry": [
            {
                "changes": [
                    {"value": {"messages": [{"type": "audio"}]}},
                    {"value": {"messages": [{"type": "text", "from": "5521", "text": {"body": "oi"}}]}},
                ]
            }
        ]
    }
    assert extrair_mensagem_whatsapp(valido) == {"de": "5521", "texto": "oi"}


def test_15_texto_vazio_descarta_a_mensagem() -> None:
    assert extrair_mensagem_whatsapp(_payload(messages=[{"type": "text", "from": "5521", "text": {"body": ""}}])) is None


def test_15_item_nulo_lanca_como_develop() -> None:
    # Achado da tradução: o 1º item é acessado sem `?.` em develop (whatsapp.ts:81 e :115).
    with pytest.raises(TypeError):
        extrair_mensagem_whatsapp(_payload(messages=[None]))
    with pytest.raises(TypeError):
        extrair_status_whatsapp(_payload(statuses=[None]))


def test_status_de_entrega_com_e_sem_erro() -> None:
    assert extrair_status_whatsapp(_payload(statuses=[{"status": "delivered", "recipient_id": "5521999"}])) == {"status": "delivered"}
    assert extrair_status_whatsapp(_payload(statuses=[{"status": "failed", "errors": [{"code": 131026, "title": "Indisponível"}]}])) == {
        "status": "failed",
        "erroCodigo": 131026,
        "erroTitulo": "Indisponível",
    }


async def test_16_envio_com_erro_registra_so_codigo_e_tipo(whatsapp_real: TransporteFalso, capsys: pytest.CaptureFixture[str]) -> None:
    numero = "+5521987654321"

    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 131026, "type": "OAuthException", "message": f"destinatário inválido {numero}"}})

    whatsapp_real.tratador = tratar
    capsys.readouterr()
    await enviar_mensagem_whatsapp(numero, "texto sensível", "chat-1")
    saida = capsys.readouterr().out
    assert numero not in saida
    assert "texto sensível" not in saida
    [linha] = [json.loads(x) for x in saida.splitlines() if x.strip()]
    assert linha["evento"] == "whatsapp_envio_falhou"
    assert linha["erroDetalhe"] == {"codigo": 131026, "tipo": "OAuthException"}


async def test_envio_nunca_lanca(whatsapp_real: TransporteFalso, capsys: pytest.CaptureFixture[str]) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede")

    whatsapp_real.tratador = tratar
    await enviar_mensagem_whatsapp("+55", "oi", "chat-2")
    [linha] = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert linha["evento"] == "whatsapp_envio_erro"


async def test_envio_monta_a_requisicao_da_graph_api(whatsapp_real: TransporteFalso) -> None:
    await enviar_mensagem_whatsapp("5521", "olá", "chat-3")
    [req] = whatsapp_real.requisicoes
    assert str(req.url) == "https://graph.teste/v21.0/123456/messages"
    assert req.headers["authorization"] == "Bearer token-meta"
    assert whatsapp_real.corpos[0] == '{"messaging_product":"whatsapp","to":"5521","type":"text","text":{"body":"olá"}}'.encode()


async def test_modo_mock_sem_token(capsys: pytest.CaptureFixture[str]) -> None:
    assert whatsapp.WHATSAPP_ACCESS_TOKEN == ""
    await enviar_mensagem_whatsapp("5521", "oi", "chat-4")
    [linha] = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert linha["evento"] == "whatsapp_envio_mock"
    assert linha["level"] == 40
