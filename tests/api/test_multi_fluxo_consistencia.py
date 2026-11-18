"""Consistência do multi-fluxo (#450, só no release): o mesmo cenário, várias vezes, dá a mesma conversa.

Três verificações, sem IA de verdade (`MOCK_NECESSIDADES`; os fluxos e o Verde simulado são os de verdade):
- o cenário completo de três assuntos, repetido, dá a mesma sequência de respostas (só o `chatId` muda);
- duas chamadas ao mesmo tempo à rota do próximo assunto abrem um atendimento só;
- duas conversas intercaladas não misturam a ordem, os `chatId` nem os assuntos pendentes.
"""

from __future__ import annotations

import asyncio
import json
from itertools import count
from typing import Any

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE
from maria.shared import pendentes_db
from maria.shared.atendimentos_db import obter_atendimentos_store

ORQ = "/atendimentos/orquestrador"
PROXIMO = "/atendimentos/proximo-assunto"
RESPOSTAS = "/atendimentos/respostas"
# O CPF da Tykhe (CPF de teste do Verde simulado) vai para o fluxo em `dadosConhecidos`, e o fluxo não o pergunta.
DADOS = {"endereco": {"cep": "20000000"}, "cpf": "11111111111"}
NECESSIDADES = [
    {"id": ID_PROBLEMAS_PLANO_SAUDE, "evidencia": "o plano negou a cirurgia", "urgente": True},
    {"id": ID_PESSOA_PRESA, "evidencia": "meu irmão está preso"},
    {"id": "tykhe:novo-processo", "evidencia": "quero entrar com um processo de pensão"},
]
REPETICOES = 5

_ids = count(1)


def _chat() -> str:
    return f"teste-consistencia-{next(_ids)}"


@pytest.fixture
def release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", raising=False)
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    monkeypatch.setenv("MOCK_NECESSIDADES", json.dumps(NECESSIDADES))


def _sem_chat(corpo: Any, chat: str) -> Any:
    """A resposta com o `chatId` da conversa trocado por um marcador, para comparar conversas diferentes."""
    return json.loads(json.dumps(corpo, ensure_ascii=False).replace(chat, "<chat>"))


async def _passo(cliente: httpx.AsyncClient, auth: dict[str, str], rota: str, corpo: dict[str, Any]) -> tuple[int, Any]:
    r = await cliente.post(rota, json=corpo, headers=auth)
    return r.status_code, r.json()


async def _ate_o_fim_do_primeiro(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str) -> list[Any]:
    """Relato com três assuntos, o plano escolhido primeiro (pela ordem de 2026-11-13, a pessoa presa viria antes) e o
    fluxo do plano até o fim (3 respostas sem a foto)."""
    passos = [
        await _passo(cliente, auth, ORQ, {"chatId": chat, "mensagem": "relato com três assuntos", "dadosConhecidos": DADOS}),
        await _passo(cliente, auth, ORQ, {"chatId": chat, "resposta": "o plano primeiro"}),
        await _passo(cliente, auth, RESPOSTAS, {"chatId": chat, "resposta": "true"}),
    ]
    for _ in range(3):
        passos.append(await _passo(cliente, auth, RESPOSTAS, {"chatId": chat, "resposta": "mandei"}))
    return passos


async def _cenario_completo(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str) -> list[Any]:
    passos = await _ate_o_fim_do_primeiro(cliente, auth, chat)
    passos.append(await _passo(cliente, auth, PROXIMO, {"chatId": chat}))  # 2º: pessoa presa
    await (await obter_atendimentos_store()).concluir(f"{chat}-assunto-2", {"statusFinal": "concluido"})
    passos.append(await _passo(cliente, auth, PROXIMO, {"chatId": chat}))  # 3º: da Tykhe
    passos.append(await _passo(cliente, auth, PROXIMO, {"chatId": chat}))  # nada mais
    return [_sem_chat(p, chat) for p in passos]


async def test_o_mesmo_cenario_repetido_da_sempre_a_mesma_conversa(cliente: httpx.AsyncClient, auth: dict[str, str], release: None) -> None:
    conversas = []
    for _ in range(REPETICOES):
        await pendentes_db.fechar_pendentes_store()  # cada rodada é uma pessoa sem assuntos guardados
        conversas.append(await _cenario_completo(cliente, auth, _chat()))
    assert all(c == conversas[0] for c in conversas[1:])
    # E a conversa é a esperada, passo a passo.
    codigos = [codigo for codigo, _ in conversas[0]]
    assert codigos == [200] * 8 + [404]
    corpos = [corpo for _, corpo in conversas[0]]
    assert corpos[0]["tipoResposta"] == "sim_nao"  # "Pode ser assim?"
    assert corpos[1]["flowId"] == ID_PROBLEMAS_PLANO_SAUDE
    assert corpos[5]["status"] == "handoff_humano"
    assert (corpos[6]["chatId"], corpos[6]["flowId"]) == ("<chat>-assunto-2", ID_PESSOA_PRESA)
    assert (corpos[7]["chatId"], corpos[7]["status"], corpos[7]["tipoCaso"]) == ("<chat>-assunto-3", "redirecionado", "novo-processo")


async def test_duas_chamadas_ao_mesmo_tempo_abrem_um_assunto_so(cliente: httpx.AsyncClient, auth: dict[str, str], release: None) -> None:
    await pendentes_db.fechar_pendentes_store()
    chat = _chat()
    await _ate_o_fim_do_primeiro(cliente, auth, chat)
    (c1, a), (c2, b) = await asyncio.gather(
        _passo(cliente, auth, PROXIMO, {"chatId": chat}),
        _passo(cliente, auth, PROXIMO, {"chatId": chat}),
    )
    assert (c1, c2) == (200, 200)
    assert a["chatId"] == b["chatId"] == f"{chat}-assunto-2"
    # Só uma das duas abriu o assunto (e leva a frase de abertura); a outra devolveu o estado atual.
    abriram = [c for c in (a, b) if c["resposta"].startswith("Agora vamos falar")]
    assert len(abriram) == 1
    assert a["resposta"].endswith(b["resposta"]) or b["resposta"].endswith(a["resposta"])


async def test_duas_conversas_intercaladas_nao_se_misturam(cliente: httpx.AsyncClient, auth: dict[str, str], release: None) -> None:
    await pendentes_db.fechar_pendentes_store()
    a, b = _chat(), _chat()
    passos_a, passos_b = [], []
    corpos = (
        (ORQ, lambda c: {"chatId": c, "mensagem": "relato com três assuntos", "dadosConhecidos": DADOS}),
        (ORQ, lambda c: {"chatId": c, "resposta": "o plano primeiro"}),
        (RESPOSTAS, lambda c: {"chatId": c, "resposta": "true"}),
        (RESPOSTAS, lambda c: {"chatId": c, "resposta": "mandei"}),
        (RESPOSTAS, lambda c: {"chatId": c, "resposta": "mandei"}),
        (RESPOSTAS, lambda c: {"chatId": c, "resposta": "mandei"}),
        (PROXIMO, lambda c: {"chatId": c}),
    )
    for rota, corpo in corpos:  # A e B alternando a cada passo
        passos_a.append(_sem_chat(await _passo(cliente, auth, rota, corpo(a)), a))
        passos_b.append(_sem_chat(await _passo(cliente, auth, rota, corpo(b)), b))
    assert passos_a == passos_b
    # Cada uma abriu o próprio 2º assunto, com o próprio chatId.
    assert passos_a[-1][1]["chatId"] == "<chat>-assunto-2"
    store = await obter_atendimentos_store()
    assert await store.buscar_flow_id(f"{a}-assunto-2") == ID_PESSOA_PRESA
    assert await store.buscar_flow_id(f"{b}-assunto-2") == ID_PESSOA_PRESA
