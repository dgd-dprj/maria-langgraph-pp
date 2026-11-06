"""O parentesco do relato chega ao fluxo de pessoa presa pelo orquestrador (#438).

Verde simulado: o processo 0000088-95.2026.8.19.0010 é encontrado, e o RG 11111111111 também.
"""

from __future__ import annotations

from itertools import count
from typing import Any

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, fluxos_por_id
from maria.fluxos.pessoa_presa.graph import TEXTO_PARENTESCO

BASE = "/atendimentos/orquestrador"
_ids = count(1)


def _chat() -> str:
    return f"teste-orq-parentesco-{next(_ids)}"


def _pessoa_presa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Depois do fixture `cliente`, que apaga as variáveis do simulado."""
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    monkeypatch.delenv("MOCK_NECESSIDADES", raising=False)
    monkeypatch.delenv("EXTRACAO_LIVRE_IA", raising=False)


async def _estado(chat: str) -> dict[str, Any]:
    estado = await fluxos_por_id[ID_PESSOA_PRESA].obter_grafo().aget_state({"configurable": {"thread_id": chat}})
    return dict(estado.values)


async def _perguntas_ate_o_fim(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str, primeira: dict[str, Any]) -> list[str]:
    """Responde o caminho feliz e devolve todas as perguntas que a Maria fez."""
    perguntas = [primeira["resposta"]]
    corpo = primeira
    for _ in range(12):
        if corpo["status"] != "em_andamento":
            break
        pergunta = corpo["resposta"]
        if "número do processo?" in pergunta.lower() or "qual o número" in pergunta.lower():
            resposta = "0000088-95.2026.8.19.0010"
        elif "RG" in pergunta:
            resposta = "11111111111"
        elif pergunta == TEXTO_PARENTESCO:
            resposta = "primo"
        elif corpo["tipoResposta"] == "sim_nao":
            resposta = "true"
        else:
            resposta = "não sei"
        r = await cliente.post("/atendimentos/respostas", json={"chatId": chat, "resposta": resposta}, headers=auth)
        corpo = r.json()
        perguntas.append(corpo["resposta"])
    return perguntas


@pytest.mark.parametrize("ambiente", [None, "release"])
async def test_meu_primo_foi_preso_nao_pergunta_o_parentesco(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, ambiente: str | None
) -> None:
    _pessoa_presa(monkeypatch)
    if ambiente:
        monkeypatch.setenv("MARIA_AMBIENTE", ambiente)
    chat = _chat()
    r = await cliente.post(BASE, json={"chatId": chat, "mensagem": "Meu primo foi preso e quero saber quando sai"}, headers=auth)
    primeira = r.json()
    assert primeira["flowId"] == ID_PESSOA_PRESA
    assert (await _estado(chat))["parentesco"] == "Primo(a)"
    perguntas = await _perguntas_ate_o_fim(cliente, auth, chat, primeira)
    assert TEXTO_PARENTESCO not in perguntas


async def test_meu_filho_foi_preso_continua_perguntando(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _pessoa_presa(monkeypatch)
    chat = _chat()
    r = await cliente.post(BASE, json={"chatId": chat, "mensagem": "meu filho foi preso e quero saber do processo"}, headers=auth)
    primeira = r.json()
    assert "parentesco" not in await _estado(chat)
    perguntas = await _perguntas_ate_o_fim(cliente, auth, chat, primeira)
    assert TEXTO_PARENTESCO in perguntas
    assert (await _estado(chat))["parentesco"] == "Outro"  # o mock da classificação devolve "Outro"


async def test_parentesco_da_tykhe_nao_e_trocado(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _pessoa_presa(monkeypatch)
    chat = _chat()
    corpo = {"chatId": chat, "mensagem": "Meu primo foi preso", "dadosConhecidos": {"parentesco": "Amigo(a)"}}
    await cliente.post(BASE, json=corpo, headers=auth)
    assert (await _estado(chat))["parentesco"] == "Amigo(a)"
