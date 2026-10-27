"""Traduzido de `test/app.test.ts` (develop @ 1157a6d): a mecânica genérica das rotas.

PR 1 do módulo api (#246): os 12 testes que usam só `POST /atendimentos`,
`/health` e `/fluxos`. Os 11 que passam por `GET /atendimentos/:chatId` ou
`POST /atendimentos/respostas` entram no PR 2.

Violência doméstica é usada como fixture só para ter algum grafo real por trás.
"""

from itertools import count

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA

BASE = "/atendimentos"
FLOW_ID = ID_VIOLENCIA_DOMESTICA
_ids = count(1)


def novo_chat_id() -> str:
    return f"teste-app-{next(_ids)}"


async def test_post_atendimentos_sem_authorization_401(cliente: httpx.AsyncClient) -> None:
    r = await cliente.post(BASE, json={"flowId": FLOW_ID})
    assert r.status_code == 401


async def test_post_atendimentos_com_chave_errada_401(cliente: httpx.AsyncClient) -> None:
    r = await cliente.post(BASE, json={"flowId": FLOW_ID}, headers={"authorization": "Bearer chave-errada"})
    assert r.status_code == 401


async def test_health_nao_exige_authorization(cliente: httpx.AsyncClient) -> None:
    r = await cliente.get("/health")
    assert r.status_code == 200


async def test_fluxos_lista_pessoa_presa_violencia_domestica_e_plano_de_saude(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    # #329: o fluxo do NUDECON entra na lista; as gravações da versão TypeScript saíram da conferência (casos_aposentados.py).
    r = await cliente.get("/fluxos", headers=auth)
    assert r.status_code == 200
    corpo = r.json()
    assert sorted(f["id"] for f in corpo) == sorted([ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, ID_PROBLEMAS_PLANO_SAUDE])
    assert next(f for f in corpo if f["id"] == ID_PESSOA_PRESA)["nome"] == "pessoa-presa"
    assert next(f for f in corpo if f["id"] == ID_PROBLEMAS_PLANO_SAUDE)["nome"] == "problemas-plano-de-saude"


async def test_post_atendimentos_sem_flow_id_400(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(BASE, json={"chatId": novo_chat_id()}, headers=auth)
    assert r.status_code == 400


async def test_post_atendimentos_com_flow_id_desconhecido_404(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(BASE, json={"chatId": novo_chat_id(), "flowId": "00000000-0000-0000-0000-000000000000"}, headers=auth)
    assert r.status_code == 404


async def test_sem_chat_id_em_app_env_test_gera_uuid(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(BASE, json={"flowId": FLOW_ID}, headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "em_andamento"


async def test_sem_chat_id_fora_de_app_env_test_400(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    r = await cliente.post(BASE, json={"flowId": FLOW_ID}, headers=auth)
    assert r.status_code == 400


async def test_location_e_links_responder(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    r = await cliente.post(BASE, json={"chatId": chat_id, "flowId": FLOW_ID}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert r.headers["location"] == f"/atendimentos/{chat_id}"
    assert corpo["status"] == "em_andamento"
    assert corpo["_links"]["self"]["href"] == f"/atendimentos/{chat_id}"
    assert corpo["_links"]["responder"]["href"] == "/atendimentos/respostas"
    assert corpo["_links"]["responder"]["method"] == "POST"


async def test_metadados_e_dados_coletados_presentes_em_andamento(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(BASE, json={"chatId": novo_chat_id(), "flowId": FLOW_ID}, headers=auth)
    corpo = r.json()
    assert corpo["status"] == "em_andamento"
    assert isinstance(corpo["metadados"], dict)
    assert isinstance(corpo["dadosColetados"], dict)
    assert "cpf" not in corpo["dadosColetados"], "cpf ainda não foi coletado nesse ponto"


async def test_mesmo_chat_id_de_outro_flow_id_409(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    primeiro = await cliente.post(BASE, json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    assert primeiro.status_code == 200
    segundo = await cliente.post(BASE, json={"chatId": chat_id, "flowId": ID_PESSOA_PRESA}, headers=auth)
    assert segundo.status_code == 409


async def test_post_2x_no_mesmo_chat_id_nao_reinicia(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    primeira = await cliente.post(BASE, json={"chatId": chat_id, "flowId": FLOW_ID}, headers=auth)
    segunda = await cliente.post(BASE, json={"chatId": chat_id, "flowId": FLOW_ID}, headers=auth)
    assert segunda.status_code == 200
    assert segunda.json()["resposta"] == primeira.json()["resposta"], "não deveria reiniciar o fluxo"
