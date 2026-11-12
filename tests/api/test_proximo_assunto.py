"""A rota do próximo assunto (#450, fase 1b do multi-fluxo): a Maria gera o `chatId` de cada assunto
depois do primeiro (`<chatId>-assunto-N`) e abre o fluxo dele, com o que a pessoa já disse (#442).

A classificação é simulada (`MOCK_NECESSIDADES`); os fluxos e o Verde simulado são os de verdade.
Na produção, a rota responde 404.
"""

from __future__ import annotations

import json
from itertools import count
from typing import Any

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, fluxos_por_id
from maria.orquestrador.graph import assuntos_pendentes_do_chat
from maria.shared.atendimentos_db import obter_atendimentos_store

ORQ = "/atendimentos/orquestrador"
PROXIMO = "/atendimentos/proximo-assunto"
RESPOSTAS = "/atendimentos/respostas"
# O CPF da Tykhe (CPF de teste do Verde simulado) vai para o fluxo em `dadosConhecidos`, e o fluxo não o pergunta.
CPF = "11111111111"
DADOS_NO_RIO = {"endereco": {"cep": "20000000"}, "cpf": CPF}
PLANO = {"id": ID_PROBLEMAS_PLANO_SAUDE, "evidencia": "o plano negou a cirurgia", "urgente": True}
PP = {"id": ID_PESSOA_PRESA, "evidencia": "meu irmão está preso"}
NOVO_PROCESSO = {"id": "tykhe:novo-processo", "evidencia": "quero entrar com um processo de pensão"}
PENDENTE_PP = {
    "nome": "a pessoa presa",
    "urgente": False,
    "urgencia": "urgente",
    "flowId": ID_PESSOA_PRESA,
    "dadosConhecidos": {"parentesco": "Irmão(a)"},
}
PENDENTE_NOVO = {"nome": "o caso novo", "urgente": False, "urgencia": "menos_urgente", "tipoCaso": "novo-processo"}
# No fim do 1º assunto, o CPF que o fluxo recebeu segue para o próximo assunto da Maria (#442).
PENDENTE_PP_FIM = {**PENDENTE_PP, "dadosConhecidos": {"cpf": CPF, "parentesco": "Irmão(a)"}}

_ids = count(1)


def _chat() -> str:
    return f"teste-proximo-{next(_ids)}"


async def _primeiro_assunto_ate_o_fim(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str) -> dict[str, Any]:
    """Aceita a ordem e leva o fluxo do plano até o fim (3 respostas sem a foto: atendimento humano)."""
    r = await cliente.post(
        ORQ, json={"chatId": chat, "mensagem": "relato com vários assuntos", "dadosConhecidos": DADOS_NO_RIO}, headers=auth
    )
    assert r.json()["tipoResposta"] == "sim_nao"
    r = await cliente.post(ORQ, json={"chatId": chat, "resposta": "true"}, headers=auth)
    assert r.json()["flowId"] == ID_PROBLEMAS_PLANO_SAUDE
    await cliente.post(RESPOSTAS, json={"chatId": chat, "resposta": "true"}, headers=auth)
    for _ in range(3):
        r = await cliente.post(RESPOSTAS, json={"chatId": chat, "resposta": "mandei"}, headers=auth)
    corpo: dict[str, Any] = r.json()
    assert corpo["status"] == "handoff_humano"
    return corpo


@pytest.fixture
def release(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.delenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", raising=False)
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    return monkeypatch


async def test_abre_o_segundo_assunto_com_chat_id_gerado_e_o_que_a_pessoa_ja_disse(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    fim = await _primeiro_assunto_ate_o_fim(cliente, auth, chat)
    assert fim["assuntosPendentes"] == [PENDENTE_PP_FIM]

    r = await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["chatId"] == f"{chat}-assunto-2"
    assert (corpo["status"], corpo["flowId"]) == ("em_andamento", ID_PESSOA_PRESA)
    assert corpo["resposta"].startswith("Agora vamos falar da pessoa presa.\n\n")
    assert corpo["_links"]["self"] == {"href": f"/atendimentos/{chat}-assunto-2"}
    assert "assuntosPendentes" not in corpo
    # #442: o parentesco lido do trecho do relato entrou no fluxo da pessoa presa.
    estado = await fluxos_por_id[ID_PESSOA_PRESA].obter_grafo().aget_state({"configurable": {"thread_id": f"{chat}-assunto-2"}})
    assert estado.values["parentesco"] == "Irmão(a)"

    # As respostas seguintes usam o chatId novo, pela rota de sempre.
    r = await cliente.post(RESPOSTAS, json={"chatId": f"{chat}-assunto-2", "resposta": "false"}, headers=auth)
    assert r.status_code == 200


async def test_chamar_de_novo_nao_abre_outro_atendimento(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    await _primeiro_assunto_ate_o_fim(cliente, auth, chat)
    primeira = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    segunda = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert segunda["chatId"] == primeira["chatId"] == f"{chat}-assunto-2"
    # A 2ª chamada devolve o estado atual (a mesma pergunta), sem a frase de abertura de novo.
    assert primeira["resposta"].endswith(segunda["resposta"])
    assert not segunda["resposta"].startswith("Agora vamos falar")
    # Mandar o chatId do próprio assunto também acha a conversa de origem.
    terceira = (await cliente.post(PROXIMO, json={"chatId": f"{chat}-assunto-2"}, headers=auth)).json()
    assert terceira["chatId"] == f"{chat}-assunto-2"


async def test_assunto_da_tykhe_volta_como_redirecionado_uma_vez(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, NOVO_PROCESSO]))
    chat = _chat()
    fim = await _primeiro_assunto_ate_o_fim(cliente, auth, chat)
    assert fim["assuntosPendentes"] == [PENDENTE_NOVO]

    r = await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)
    corpo = r.json()
    assert (r.status_code, corpo["status"], corpo["tipoCaso"]) == (200, "redirecionado", "novo-processo")
    assert corpo["chatId"] == f"{chat}-assunto-2"
    assert "flowId" not in corpo

    r = await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)
    assert (r.status_code, r.json()) == (404, {"erro": "nenhum assunto pendente nesta conversa"})


async def test_tres_assuntos_seguem_em_ordem_e_cada_um_ve_os_que_faltam(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP, NOVO_PROCESSO]))
    chat = _chat()
    fim = await _primeiro_assunto_ate_o_fim(cliente, auth, chat)
    assert fim["assuntosPendentes"] == [PENDENTE_PP_FIM, PENDENTE_NOVO]

    corpo = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert (corpo["chatId"], corpo["flowId"]) == (f"{chat}-assunto-2", ID_PESSOA_PRESA)
    assert corpo["assuntosPendentes"] == [PENDENTE_NOVO]
    # No fim do 2º assunto, a resposta final lista só o que vem depois dele.
    assert await assuntos_pendentes_do_chat(f"{chat}-assunto-2") == [PENDENTE_NOVO]

    # Encerrado o 2º, a próxima chamada pula para o 3º.
    store = await obter_atendimentos_store()
    await store.concluir(f"{chat}-assunto-2", {"statusFinal": "concluido"})
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert (corpo["chatId"], corpo["status"], corpo["tipoCaso"]) == (f"{chat}-assunto-3", "redirecionado", "novo-processo")
    assert await assuntos_pendentes_do_chat(f"{chat}-assunto-3") is None


async def test_conversa_sem_pendentes_e_chat_id_ausente(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    r = await cliente.post(PROXIMO, json={"chatId": _chat()}, headers=auth)
    assert (r.status_code, r.json()) == (404, {"erro": "nenhum assunto pendente nesta conversa"})
    r = await cliente.post(PROXIMO, json={}, headers=auth)
    assert (r.status_code, r.json()) == (400, {"erro": "chatId obrigatório"})


async def test_na_producao_a_rota_responde_404(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARIA_AMBIENTE", raising=False)
    r = await cliente.post(PROXIMO, json={"chatId": _chat()}, headers=auth)
    assert (r.status_code, r.json()) == (404, {"erro": "rota disponível só no ambiente de teste (release)"})
