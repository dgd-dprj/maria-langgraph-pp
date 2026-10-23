"""Campo `destino` nas respostas de atendimento encerrado (issue #288, etapa 1).

Os valores são os que já iam para o log e para a tabela `atendimentos` (`destino_do_log`). O
`status` e o `metadados.motivoHandoff` não mudam.
"""

from itertools import count

import httpx
import pytest

from maria.api.atendimentos import destino_do_log, montar_resposta_atendimento
from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, buscar_fluxo

BASE = "/atendimentos"
_ids = count(1)


def novo_chat_id() -> str:
    return f"teste-destino-{next(_ids)}"


async def _handoff(cliente: httpx.AsyncClient, auth: dict[str, str]) -> str:
    chat_id = novo_chat_id()
    await cliente.post(BASE, json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    resposta = await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)
    assert resposta.json()["status"] == "handoff_humano"
    return chat_id


async def test_handoff_traz_destino_atendimento_humano_e_mantem_status_e_motivo(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = novo_chat_id()
    await cliente.post(BASE, json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    corpo = (await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)).json()
    assert corpo["status"] == "handoff_humano"
    assert corpo["destino"] == "atendimento_humano"
    assert corpo["tipoResposta"] == "texto"
    assert corpo["resposta"]
    assert corpo["metadados"]["motivoHandoff"] == "nao_e_vitima"


async def test_get_do_atendimento_encerrado_traz_o_destino(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = await _handoff(cliente, auth)
    corpo = (await cliente.get(f"{BASE}/{chat_id}", headers=auth)).json()
    assert corpo["destino"] == "atendimento_humano"


async def test_409_de_atendimento_encerrado_repete_o_destino(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = await _handoff(cliente, auth)
    r = await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "qualquer coisa"}, headers=auth)
    assert r.status_code == 409
    assert r.json()["destino"] == "atendimento_humano"


async def test_pergunta_em_andamento_nao_traz_destino(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(BASE, json={"chatId": novo_chat_id(), "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    assert r.json()["status"] == "em_andamento"
    assert "destino" not in r.json()


async def test_expirado_traz_destino_sessao_expirada(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = novo_chat_id()
    await cliente.post(BASE, json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    monkeypatch.setenv("TTL_INATIVIDADE_HORAS", "0")
    await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "true"}, headers=auth)
    monkeypatch.delenv("TTL_INATIVIDADE_HORAS")
    corpo = (await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)).json()
    assert corpo["status"] == "expirado"
    assert corpo["destino"] == "sessao_expirada"


async def test_violencia_domestica_concluida_vai_para_agendamento() -> None:
    fluxo = await buscar_fluxo(ID_VIOLENCIA_DOMESTICA)
    assert fluxo is not None
    corpo = montar_resposta_atendimento(fluxo, ID_VIOLENCIA_DOMESTICA, "chat-ficticio", None, {"statusFinal": "concluido"})
    assert corpo["status"] == "concluido"
    assert corpo["destino"] == "agendamento"


async def test_fluxo_concluido_sem_destino_definido_nao_traz_o_campo() -> None:
    fluxo = await buscar_fluxo(ID_PESSOA_PRESA)
    assert fluxo is not None
    corpo = montar_resposta_atendimento(fluxo, ID_PESSOA_PRESA, "chat-ficticio", None, {"statusFinal": "concluido"})
    assert corpo["status"] == "concluido"
    assert "destino" not in corpo
    assert destino_do_log(ID_PESSOA_PRESA, "concluido") is None
