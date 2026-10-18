"""Traduzido de `src/fluxos/{violenciaDomestica,pessoaPresa}/http.test.ts` (develop @ 1157a6d).

PR 1: a 1ª pergunta de cada fluxo pela rota. Os outros 8 testes (7 de violência
doméstica e 2 de pessoa presa, menos a 1ª pergunta) respondem pelo
`POST /atendimentos/respostas` e entram no PR 2.
"""

from itertools import count

import httpx

from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA

_ids = count(1)


async def test_violencia_domestica_primeira_pergunta_sim_nao_sobre_ser_vitima(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post("/atendimentos", json={"chatId": f"teste-vd-http-{next(_ids)}", "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["tipoResposta"] == "sim_nao"
    assert "vítima de violência doméstica" in corpo["resposta"]


async def test_pessoa_presa_primeira_pergunta_sim_nao_sobre_numero_do_processo(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post("/atendimentos", json={"chatId": f"teste-pp-http-{next(_ids)}", "flowId": ID_PESSOA_PRESA}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["tipoResposta"] == "sim_nao"
    assert "número do processo" in corpo["resposta"]
