"""Campo `destino` nas respostas de atendimento encerrado (issue #288).

Aditivo: `status` e `motivoHandoff` ficam como estavam. As fixtures de contrato não trazem o campo
(`tests/api/sem_campos_posteriores.py`), então ele é coberto aqui.
"""

import json
from itertools import count
from typing import Any

import httpx
import pytest

from maria.api.atendimentos import montar_resposta_atendimento
from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, fluxos_por_id

_ids = count(1)


def _chat_id() -> str:
    return f"teste-destino-{next(_ids)}"


def _montar(fluxo_id: str, valores: dict[str, Any]) -> dict[str, Any]:
    return montar_resposta_atendimento(fluxos_por_id[fluxo_id], fluxo_id, "chat-x", None, valores)


# --- a montagem da resposta, por fluxo e desfecho --------------------------------


@pytest.mark.parametrize(
    ("fluxo_id", "valores", "destino"),
    [
        (ID_VIOLENCIA_DOMESTICA, {"statusFinal": "handoff_humano"}, "atendimento_humano"),
        (ID_PESSOA_PRESA, {"statusFinal": "handoff_humano"}, "atendimento_humano"),
        (ID_VIOLENCIA_DOMESTICA, {"statusFinal": "concluido"}, "agendamento"),
        (ID_VIOLENCIA_DOMESTICA, {}, "agendamento"),  # sem statusFinal vale "concluido"
        (ID_VIOLENCIA_DOMESTICA, {"statusFinal": "expirado"}, "sessao_expirada"),
        (ID_PESSOA_PRESA, {"statusFinal": "expirado"}, "sessao_expirada"),
    ],
)
def test_destino_por_fluxo_e_desfecho(fluxo_id: str, valores: dict[str, Any], destino: str) -> None:
    assert _montar(fluxo_id, valores)["destino"] == destino


def test_pessoa_presa_concluida_nao_tem_destino() -> None:
    corpo = _montar(ID_PESSOA_PRESA, {"statusFinal": "concluido"})
    assert corpo["status"] == "concluido"
    assert "destino" not in corpo


def test_pergunta_em_andamento_nao_tem_destino() -> None:
    fluxo = fluxos_por_id[ID_VIOLENCIA_DOMESTICA]
    pergunta = {"pergunta": "Você é a vítima de violência doméstica?", "tipo": "sim_nao", "opcoes": ["Sim", "Não"]}
    corpo = montar_resposta_atendimento(fluxo, ID_VIOLENCIA_DOMESTICA, "chat-x", pergunta, {})
    assert corpo["status"] == "em_andamento"
    assert "destino" not in corpo


def test_destino_nao_muda_status_nem_o_resto_da_resposta() -> None:
    corpo = _montar(ID_VIOLENCIA_DOMESTICA, {"statusFinal": "handoff_humano", "motivoHandoff": "nao_e_vitima", "ehVitima": False})
    assert corpo["status"] == "handoff_humano"
    assert corpo["metadados"]["motivoHandoff"] == "nao_e_vitima"
    assert list(corpo)[:4] == ["resposta", "tipoResposta", "status", "destino"]


# --- pela rota --------------------------------------------------------------------


async def _handoff_nao_vitima(cliente: httpx.AsyncClient, auth: dict[str, str]) -> tuple[str, httpx.Response]:
    chat_id = _chat_id()
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    fim = await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)
    return chat_id, fim


async def test_resposta_do_handoff_traz_destino_e_mantem_o_resto(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    _, fim = await _handoff_nao_vitima(cliente, auth)
    corpo = fim.json()
    assert fim.status_code == 200
    assert corpo["status"] == "handoff_humano"
    assert corpo["destino"] == "atendimento_humano"
    assert corpo["metadados"]["motivoHandoff"] == "nao_e_vitima"
    assert [chave for chave in json.loads(fim.text)][:4] == ["resposta", "tipoResposta", "status", "destino"]


async def test_get_do_atendimento_encerrado_traz_destino(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id, _ = await _handoff_nao_vitima(cliente, auth)
    r = await cliente.get(f"/atendimentos/{chat_id}", headers=auth)
    assert r.status_code == 200
    assert r.json()["destino"] == "atendimento_humano"


async def test_409_de_atendimento_encerrado_repete_o_destino(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id, _ = await _handoff_nao_vitima(cliente, auth)
    r = await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": "oi"}, headers=auth)
    assert r.status_code == 409
    assert r.json()["status"] == "handoff_humano"
    assert r.json()["destino"] == "atendimento_humano"


async def test_pergunta_em_andamento_pela_rota_nao_traz_destino(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post("/atendimentos", json={"chatId": _chat_id(), "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    assert r.json()["status"] == "em_andamento"
    assert "destino" not in r.json()


async def test_expirado_pela_rota_traz_sessao_expirada(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = _chat_id()
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    monkeypatch.setenv("TTL_INATIVIDADE_HORAS", "0")
    confirmacao = await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": "true"}, headers=auth)
    assert confirmacao.json()["tipoResposta"] == "sim_nao"
    recusa = await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": "false"}, headers=auth)
    assert recusa.json()["status"] == "expirado"
    assert recusa.json()["destino"] == "sessao_expirada"
    de_novo = await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": "oi"}, headers=auth)
    assert de_novo.status_code == 409
    assert de_novo.json()["destino"] == "sessao_expirada"


# --- a documentação ---------------------------------------------------------------


async def test_openapi_documenta_destino(cliente: httpx.AsyncClient) -> None:
    documento = (await cliente.get("/docs/json")).json()
    schema = documento["paths"]["/atendimentos/respostas"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    destino = schema["properties"]["destino"]
    assert destino["enum"] == ["atendimento_humano", "agendamento", "sessao_expirada"]
    assert "para onde" in destino["description"]
