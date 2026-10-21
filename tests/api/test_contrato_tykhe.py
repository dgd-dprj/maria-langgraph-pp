"""Traduzido de `test/contratoTykhe.test.ts` (develop @ 1157a6d, issue #117): o
"envelope" que a Tykhe consome (status, tipoResposta, opcoes, resposta, _links).

PR 1 do api: os 2 casos de 1ª pergunta. PR 2: os 2 de "concluído", que passam
por `POST /atendimentos/respostas`.
"""

from itertools import count
from typing import Any

import httpx

from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA

_ids = count(1)


def assert_contrato_tykhe(corpo: dict[str, Any], contexto: str) -> None:
    assert isinstance(corpo["status"], str), f"{contexto}: status deveria ser string"
    assert corpo["status"] in ("em_andamento", "concluido", "handoff_humano"), f"{contexto}: status fora do contrato"
    assert isinstance(corpo["flowId"], str), f"{contexto}: flowId deveria ser string"
    assert isinstance(corpo["metadados"], dict), f"{contexto}: metadados deveria existir (mesmo vazio)"
    assert isinstance(corpo["dadosColetados"], dict), f"{contexto}: dadosColetados deveria existir (mesmo vazio)"
    links = corpo["_links"]
    assert isinstance(links["self"], dict) and isinstance(links["self"]["href"], str), f"{contexto}: _links.self.href"
    if corpo["status"] == "em_andamento":
        assert isinstance(corpo["resposta"], str), f"{contexto}: resposta deveria ser string"
        assert corpo["tipoResposta"] in ("sim_nao", "texto"), f"{contexto}: tipoResposta fora do contrato"
        assert links["responder"]["method"] == "POST", f"{contexto}: _links.responder.method deveria ser POST"
        if corpo["tipoResposta"] == "sim_nao":
            assert isinstance(corpo["opcoes"], list) and all(isinstance(o, str) for o in corpo["opcoes"]), f"{contexto}: opcoes"
    else:
        assert "responder" not in links, f"{contexto}: concluído não deveria ter _links.responder"


async def test_pessoa_presa_primeira_pergunta(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post("/atendimentos", json={"chatId": f"teste-contrato-pp-{next(_ids)}", "flowId": ID_PESSOA_PRESA}, headers=auth)
    assert r.status_code == 200
    assert_contrato_tykhe(r.json(), "pessoa presa, 1ª pergunta")


async def test_violencia_domestica_primeira_pergunta(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(
        "/atendimentos", json={"chatId": f"teste-contrato-vd-{next(_ids)}", "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth
    )
    assert r.status_code == 200
    assert_contrato_tykhe(r.json(), "violência doméstica, 1ª pergunta")


async def _responder(cliente: httpx.AsyncClient, auth: dict[str, str], chat_id: str, resposta: str) -> httpx.Response:
    return await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": resposta}, headers=auth)


async def test_pessoa_presa_concluido_handoff_sem_processo(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-contrato-pp-fim-{next(_ids)}"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_PESSOA_PRESA}, headers=auth)
    await _responder(cliente, auth, chat_id, "false")  # sem processo
    await _responder(cliente, auth, chat_id, "11111111111")  # RG (o mock acha)
    await _responder(cliente, auth, chat_id, "true")  # confirma o nome
    r = await _responder(cliente, auth, chat_id, "mae")  # parentesco: conclui direto (#191, rota direta = Tykhe)
    assert r.status_code == 200
    assert r.json()["status"] == "handoff_humano"
    assert_contrato_tykhe(r.json(), "pessoa presa, concluído")


async def test_violencia_domestica_concluido_handoff_nao_e_vitima(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-contrato-vd-fim-{next(_ids)}"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    r = await _responder(cliente, auth, chat_id, "false")  # não é vítima
    assert r.status_code == 200
    assert r.json()["status"] == "handoff_humano"
    assert_contrato_tykhe(r.json(), "violência doméstica, concluído")
