"""Atalho por palavra (#553) pela rota POST /atendimentos/orquestrador: o fluxo, os tokens e a linha de log.

O campo `atalho` da linha "orquestrador: fluxo identificado" é posterior à gravação das fixtures de contrato
(`campos_posteriores.py`): este teste cobre a presença dele com o atalho e a ausência sem o atalho.
"""

from __future__ import annotations

import json
from itertools import count
from typing import Any

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA
from maria.orquestrador.atalho import MOTIVO_PESSOA_PRESA

BASE = "/atendimentos/orquestrador"
_ids = count(1)


def _linha_identificado(saida: str) -> dict[str, Any]:
    [linha] = [json.loads(x) for x in saida.splitlines() if '"orquestrador_fluxo_identificado"' in x]
    return dict(linha)


@pytest.mark.parametrize("ambiente", ["producao", "release"])
async def test_so_a_palavra_vai_ao_fluxo_de_pessoa_presa_sem_ia(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], ambiente: str
) -> None:
    monkeypatch.setenv("MARIA_AMBIENTE", ambiente)
    # A IA simulada mandaria para "outros": quem decide é o atalho.
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", "tykhe:outros")
    capsys.readouterr()
    r = await cliente.post(BASE, json={"chatId": f"teste-atalho-{next(_ids)}", "mensagem": "PRESIDIÁRIA!"}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert corpo["status"] == "em_andamento", "a Maria faz a primeira pergunta do fluxo"
    saida = capsys.readouterr().out
    linha = _linha_identificado(saida)
    assert linha["atalho"] == MOTIVO_PESSOA_PRESA
    assert "tokensGastosTotal" not in linha, "nenhuma chamada de IA na rodada"
    assert "PRESIDIÁRIA" not in saida and "PRESIDI\\u00c1RIA" not in saida, "a mensagem nunca vai para o log"


async def test_sem_atalho_a_linha_nao_tem_o_campo(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    capsys.readouterr()
    r = await cliente.post(BASE, json={"chatId": f"teste-atalho-{next(_ids)}", "mensagem": "meu filho foi preso ontem"}, headers=auth)
    assert r.json()["flowId"] == ID_PESSOA_PRESA
    assert "atalho" not in _linha_identificado(capsys.readouterr().out)
