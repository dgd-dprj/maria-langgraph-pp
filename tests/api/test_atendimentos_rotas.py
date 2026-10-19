"""Traduzido de `test/app.test.ts` (develop @ 1157a6d): os 11 testes que passam por
`GET /atendimentos/:chatId` ou `POST /atendimentos/respostas` (PR 2 do módulo api,
#246). Os outros 12 estão em `test_app.py`.

Violência doméstica é usada como fixture só para ter algum grafo real por trás.
"""

import re
from itertools import count

import httpx

from maria.fluxos import ID_VIOLENCIA_DOMESTICA

BASE = "/atendimentos"
FLOW_ID = ID_VIOLENCIA_DOMESTICA
_ids = count(1)


def novo_chat_id() -> str:
    return f"teste-app-pr2-{next(_ids)}"


async def _criar(cliente: httpx.AsyncClient, auth: dict[str, str], chat_id: str, **extra: object) -> httpx.Response:
    return await cliente.post(BASE, json={"chatId": chat_id, "flowId": FLOW_ID, **extra}, headers=auth)


async def test_flow_id_em_toda_resposta_criacao_get_e_respostas(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    criado = await _criar(cliente, auth, chat_id)
    assert criado.json()["flowId"] == FLOW_ID
    get = await cliente.get(f"{BASE}/{chat_id}", headers=auth)
    assert get.json()["flowId"] == FLOW_ID
    resposta = await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)
    assert resposta.json()["flowId"] == FLOW_ID


async def test_get_chat_id_inexistente_404(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.get(f"{BASE}/nao-existe-nunca-foi-criado", headers=auth)
    assert r.status_code == 404


async def test_get_depois_de_criado_mesmo_estado_sem_avancar(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    criado = await _criar(cliente, auth, chat_id)
    r = await cliente.get(f"{BASE}/{chat_id}", headers=auth)
    assert r.status_code == 200
    assert r.json()["resposta"] == criado.json()["resposta"], "GET não deve avançar o fluxo"
    assert r.json()["status"] == "em_andamento"


async def test_respostas_sem_chat_id_400(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(f"{BASE}/respostas", json={"resposta": "qualquer coisa"}, headers=auth)
    assert r.status_code == 400


async def test_respostas_sem_resposta_400_e_nao_500(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    await _criar(cliente, auth, chat_id)
    r = await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id}, headers=auth)
    assert r.status_code == 400


async def test_respostas_com_resposta_vazia_400_e_nao_500(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    # #185: "" virava Command(resume="") e um 500 cru.
    chat_id = novo_chat_id()
    await _criar(cliente, auth, chat_id)
    r = await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": ""}, headers=auth)
    assert r.status_code == 400


async def test_respostas_em_chat_id_nunca_criado_404(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(f"{BASE}/respostas", json={"chatId": "nunca-criado", "resposta": "qualquer coisa"}, headers=auth)
    assert r.status_code == 404


async def test_respostas_sem_flow_id_resolve_pelo_chat_id(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    await _criar(cliente, auth, chat_id)
    r = await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)
    assert r.status_code == 200


async def test_fluxo_terminado_sem_opcoes_e_sem_link_responder(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    await _criar(cliente, auth, chat_id)
    r = await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] != "em_andamento"
    assert "opcoes" not in corpo
    assert "responder" not in corpo["_links"], "atendimento terminado não oferece link para responder de novo"
    assert corpo["_links"]["self"]["href"] == f"{BASE}/{chat_id}"
    # #35/#92: {0,0,0}, e não ausente; em APP_ENV=test nenhuma IA é chamada.
    assert corpo["tokensGastos"] == {"input": 0, "output": 0, "total": 0}


async def test_respostas_em_chat_id_ja_concluido_409(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    await _criar(cliente, auth, chat_id)
    await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)
    r = await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "qualquer coisa"}, headers=auth)
    assert r.status_code == 409


async def test_409_enriquecido_com_metadados_dados_coletados_e_flow_id(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    # Achado em uso real em 2026-09-09: o 409 não pode jogar fora o que foi coletado.
    chat_id = novo_chat_id()
    await _criar(cliente, auth, chat_id, dadosConhecidos={"cpf": "11111111111"})
    await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)
    r = await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "qualquer coisa"}, headers=auth)
    corpo = r.json()
    assert r.status_code == 409
    assert re.search("já foi concluído", corpo["erro"])
    assert corpo["flowId"] == FLOW_ID
    assert corpo["status"] == "handoff_humano"
    assert corpo["dadosColetados"]["cpf"] == "11111111111", "não pode perder o cpf já coletado"
    assert isinstance(corpo["metadados"], dict)
