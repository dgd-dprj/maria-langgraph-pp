"""Os erros da API (#210 e #211, decisão da Nicole, 2026-11-18, um PR só).

- #211: o 400 de validação e de leitura do corpo traz o motivo em português, no formato dos erros de negócio
  (`{"erro": …}`), em vez do `{}` do Fastify. O status continua 400, e não o 422 padrão do FastAPI.
- #210: o 500 não devolve o texto da exceção. O corpo traz um texto fixo e o `reqId` da requisição, que é o mesmo de
  todas as linhas de log dela, inclusive a que guarda a exceção e a stack.

Os casos gravados que mudaram saíram da conferência por `casos_aposentados.py`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from maria.api.pipeline import MENSAGEM_500, ErroFastify, motivo_400
from maria.api.validacao import ErroValidacao

ID_VIOLENCIA_DOMESTICA = "cabb2495-4e12-4f4a-9956-3d20649059bc"
JSON = {"content-type": "application/json"}


def _linhas_de_log(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    linhas = []
    for linha in capsys.readouterr().out.splitlines():
        try:
            linhas.append(json.loads(linha))
        except json.JSONDecodeError:
            continue
    return linhas


# ---- #211: o 400 com o motivo ---------------------------------------------------------------------------------------

# Os cinco casos da #211, gravados em develop com `400 {}`.
CASOS_400 = {
    "flowId que não é UUID": (
        "/atendimentos",
        json.dumps({"chatId": "erro-400-1", "flowId": "nao-e-uuid"}),
        JSON,
        "flowId com formato inválido (esperado um UUID)",
    ),
    "JSON malformado": ("/atendimentos", '{"chatId": "erro-400-2", ', JSON, "JSON inválido no corpo"),
    "content-type JSON com corpo vazio": ("/atendimentos", "", JSON, "corpo vazio, mas o content-type é application/json"),
    "content-type text/plain": ("/atendimentos", "oi", {"content-type": "text/plain"}, "o corpo precisa ser um objeto JSON"),
    "mensagem de tipo objeto no orquestrador": (
        "/atendimentos/orquestrador",
        json.dumps({"chatId": "erro-400-5", "mensagem": {"texto": "oi"}}),
        JSON,
        "mensagem precisa ser texto",
    ),
}


@pytest.mark.parametrize("caso", list(CASOS_400))
async def test_211_o_400_traz_o_motivo_e_continua_400(cliente: httpx.AsyncClient, auth: dict[str, str], caso: str) -> None:
    caminho, corpo, cabecalhos, motivo = CASOS_400[caso]
    r = await cliente.post(caminho, content=corpo.encode("utf-8"), headers={**auth, **cabecalhos})
    assert r.status_code == 400  # e não 422: o contrato com a Tykhe é 400
    assert r.headers["content-type"] == "application/json; charset=utf-8"
    assert r.json() == {"erro": motivo}


async def test_211_o_400_de_negocio_nao_muda(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post("/atendimentos", json={"chatId": "erro-400-negocio"}, headers=auth)
    assert r.status_code == 400
    assert r.json() == {"erro": "flowId obrigatório"}


async def test_211_o_motivo_nao_repete_o_valor_recebido(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    # O valor recusado pode ser um relato: o motivo fala do campo, nunca do conteúdo.
    relato = {"texto": "meu marido me ameaçou"}
    r = await cliente.post("/atendimentos/orquestrador", json={"chatId": "erro-400-relato", "mensagem": relato}, headers=auth)
    assert r.status_code == 400
    assert "ameaçou" not in r.text


@pytest.mark.parametrize(
    ("erro", "motivo"),
    [
        (ErroValidacao("", "#/type", "type", {"type": "object"}, "must be object"), "o corpo precisa ser um objeto JSON"),
        (ErroValidacao("/chatId", "#/properties/chatId/type", "type", {"type": "string"}, "must be string"), "chatId precisa ser texto"),
        (
            ErroValidacao("/dadosConhecidos", "#/properties/dadosConhecidos/type", "type", {"type": "object"}, "must be object"),
            "dadosConhecidos precisa ser um objeto",
        ),
        (
            ErroFastify(400, "FST_ERR_CTP_INVALID_CONTENT_LENGTH", "Request body size did not match Content-Length"),
            "o tamanho do corpo não bate com o Content-Length (o corpo precisa estar em UTF-8)",
        ),
        (ErroFastify(400, "FST_ERR_QUALQUER_OUTRO", "x"), "requisição inválida"),
    ],
)
def test_211_motivos(erro: Exception, motivo: str) -> None:
    assert motivo_400(erro) == motivo


async def test_211_rota_sem_o_400_declarado_mantem_o_corpo_do_fastify(cliente: httpx.AsyncClient) -> None:
    # O webhook não declara o 400: a #211 vale para as rotas que já respondiam `{"erro": …}`.
    r = await cliente.post("/webhook/whatsapp", content=b"{", headers=JSON)
    assert r.status_code == 400
    assert r.json() == {
        "statusCode": 400,
        "code": "FST_ERR_CTP_INVALID_JSON_BODY",
        "error": "Bad Request",
        "message": "Body is not valid JSON but content-type is set to 'application/json'",
    }


# ---- #210: o 500 sem o texto da exceção, com o reqId --------------------------------------------------------------


async def test_210_o_500_nao_mostra_a_excecao_e_traz_o_reqid_do_log(cliente: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]) -> None:
    # Gatilho real, o mesmo da gravação `erro-nao-tratado-webhook-mensagem-null-500`: um item nulo na lista de mensagens.
    capsys.readouterr()
    corpo = {"entry": [{"changes": [{"value": {"messages": [None]}}]}]}
    r = await cliente.post("/webhook/whatsapp", json=corpo)

    assert r.status_code == 500
    resposta = r.json()
    assert list(resposta) == ["statusCode", "error", "message", "reqId"]
    assert resposta["statusCode"] == 500
    assert resposta["error"] == "Internal Server Error"
    assert resposta["message"] == MENSAGEM_500

    linhas = _linhas_de_log(capsys)
    erro = next(linha for linha in linhas if linha.get("level") == 50)
    # A exceção e a stack ficam no log, e só nele.
    assert erro["err"]["message"]
    assert erro["err"]["stack"]
    assert erro["err"]["message"] not in r.text
    # Um reqId só por requisição: o do corpo é o da linha do erro e o de todas as outras linhas da mesma requisição.
    assert erro["reqId"] == resposta["reqId"]
    da_requisicao = [linha for linha in linhas if linha.get("reqId") == resposta["reqId"]]
    assert da_requisicao[0]["msg"] == "incoming request"
    assert da_requisicao[-1]["msg"] == "request completed"


async def test_210_cada_requisicao_tem_o_seu_reqid(cliente: httpx.AsyncClient) -> None:
    corpo = {"entry": [{"changes": [{"value": {"messages": [None]}}]}]}
    primeiro = (await cliente.post("/webhook/whatsapp", json=corpo)).json()["reqId"]
    segundo = (await cliente.post("/webhook/whatsapp", json=corpo)).json()["reqId"]
    assert primeiro != segundo
