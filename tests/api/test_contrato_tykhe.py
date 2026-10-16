"""Traduzido de `test/contratoTykhe.test.ts` (develop @ 1157a6d, issue #117): o
"envelope" que a Tykhe consome (status, tipoResposta, opcoes, resposta, _links).

PR 1: os 2 casos de 1ª pergunta. Os 2 de "concluído" passam por
`POST /atendimentos/respostas` e entram no PR 2.
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
