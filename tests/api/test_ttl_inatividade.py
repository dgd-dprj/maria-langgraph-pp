"""Traduzido de `test/ttlInatividade.test.ts` (develop @ 1157a6d): TTL de
inatividade (#166) e a confirmação tolerante (#227, #234).

`TTL_INATIVIDADE_HORAS=0` força "sempre expirado": qualquer intervalo maior que
zero conta, sem esperar tempo real. A variável é lida a cada requisição.
"""

import re
from itertools import count

import httpx
import pytest

from maria.fluxos import ID_VIOLENCIA_DOMESTICA

BASE = "/atendimentos"
FLOW_ID = ID_VIOLENCIA_DOMESTICA
_ids = count(1)


def novo_chat_id() -> str:
    return f"teste-ttl-{next(_ids)}"


async def _responder(cliente: httpx.AsyncClient, auth: dict[str, str], chat_id: str, resposta: str) -> httpx.Response:
    return await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": resposta}, headers=auth)


async def _com_confirmacao_pendente(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, resposta_original: str
) -> str:
    chat_id = novo_chat_id()
    await cliente.post(BASE, json={"chatId": chat_id, "flowId": FLOW_ID}, headers=auth)
    monkeypatch.setenv("TTL_INATIVIDADE_HORAS", "0")
    confirmacao = await _responder(cliente, auth, chat_id, resposta_original)
    assert confirmacao.json()["tipoResposta"] == "sim_nao"
    monkeypatch.delenv("TTL_INATIVIDADE_HORAS")
    return chat_id


async def test_dentro_do_ttl_processa_sem_confirmacao(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    await cliente.post(BASE, json={"chatId": chat_id, "flowId": FLOW_ID}, headers=auth)
    r = await _responder(cliente, auth, chat_id, "true")
    assert r.status_code == 200
    assert "resposta" in r.json()
    assert not re.search("Já faz um tempo", r.json()["resposta"])


async def test_fora_do_ttl_pergunta_se_quer_continuar(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = novo_chat_id()
    await cliente.post(BASE, json={"chatId": chat_id, "flowId": FLOW_ID}, headers=auth)
    monkeypatch.setenv("TTL_INATIVIDADE_HORAS", "0")
    r = await _responder(cliente, auth, chat_id, "true")
    assert r.status_code == 200
    assert r.json()["tipoResposta"] == "sim_nao"
    assert re.search("Já faz um tempo", r.json()["resposta"])


async def test_confirma_continuar_processa_a_resposta_original(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = await _com_confirmacao_pendente(cliente, auth, monkeypatch, "false")
    # "sim" processa a resposta original ("false" = não é vítima): handoff.
    r = await _responder(cliente, auth, chat_id, "true")
    assert r.status_code == 200
    assert r.json()["status"] == "handoff_humano"
    assert r.json()["metadados"]["motivoHandoff"] == "nao_e_vitima"


async def test_confirma_recomecar_expira_e_bloqueia_com_409(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = await _com_confirmacao_pendente(cliente, auth, monkeypatch, "true")
    r = await _responder(cliente, auth, chat_id, "false")
    assert r.status_code == 200
    assert r.json()["status"] == "expirado"
    assert re.search("inicie um novo atendimento", r.json()["resposta"])
    bloqueado = await _responder(cliente, auth, chat_id, "true")
    assert bloqueado.status_code == 409
    assert bloqueado.json()["erro"] == "atendimento expirado por inatividade — inicie um novo atendimento"


@pytest.mark.parametrize("confirmacao", ["sim", "Sim", "SIM", " s ", "quero continuar", "Continuar"])
async def test_confirmacao_que_continua_227(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, confirmacao: str
) -> None:
    chat_id = await _com_confirmacao_pendente(cliente, auth, monkeypatch, "false")
    r = await _responder(cliente, auth, chat_id, confirmacao)
    assert r.status_code == 200
    assert r.json()["status"] == "handoff_humano"
    assert r.json()["metadados"]["motivoHandoff"] == "nao_e_vitima"


@pytest.mark.parametrize("confirmacao", ["não", "nao", "N", "Recomeçar"])
async def test_confirmacao_que_expira_227(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, confirmacao: str
) -> None:
    chat_id = await _com_confirmacao_pendente(cliente, auth, monkeypatch, "false")
    r = await _responder(cliente, auth, chat_id, confirmacao)
    assert r.status_code == 200
    assert r.json()["status"] == "expirado"


async def test_confirmacao_nao_reconhecida_pergunta_de_novo_sem_perder_a_original(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = await _com_confirmacao_pendente(cliente, auth, monkeypatch, "false")
    repetida = await _responder(cliente, auth, chat_id, "meu marido me ameaçou ontem")
    assert repetida.status_code == 200
    assert repetida.json()["status"] == "em_andamento"
    assert repetida.json()["tipoResposta"] == "sim_nao"
    assert re.search("Já faz um tempo", repetida.json()["resposta"])
    r = await _responder(cliente, auth, chat_id, "sim")
    assert r.json()["status"] == "handoff_humano"
    assert r.json()["metadados"]["motivoHandoff"] == "nao_e_vitima"
