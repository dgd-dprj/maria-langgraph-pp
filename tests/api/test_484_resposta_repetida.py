"""#484: a Tykhe desiste de uma resposta lenta em cerca de 11 s e repete a mesma mensagem.

Uma repetição idêntica de uma resposta que foi lenta devolve a resposta já calculada, sem avançar o fluxo de novo. O
mesmo vale para duas respostas iguais ao mesmo tempo. Quem repete a mesma resposta de propósito, a uma pergunta que
respondeu rápido, é lido normalmente. Em memória, pela API, sem Verde (mock).
"""

import asyncio
import re
from itertools import count

import httpx
import pytest

from maria.api import atendimentos
from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA

BASE = "/atendimentos"
_ids = count(1)


@pytest.fixture(autouse=True)
def _sem_respostas_de_outros_testes() -> None:
    atendimentos._ultimas_respostas.clear()


@pytest.fixture
def resposta_lenta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Toda resposta conta como lenta (o limite real é de 5 s)."""
    monkeypatch.setattr(atendimentos, "DURACAO_LENTA_S", 0.0)


async def _criar(cliente: httpx.AsyncClient, auth: dict[str, str], fluxo: str = ID_PESSOA_PRESA) -> str:
    chat_id = f"teste-484-{next(_ids)}"
    r = await cliente.post(BASE, json={"chatId": chat_id, "flowId": fluxo}, headers=auth)
    assert r.status_code == 200
    return chat_id


async def _responder(cliente: httpx.AsyncClient, auth: dict[str, str], chat_id: str, resposta: str) -> httpx.Response:
    return await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": resposta}, headers=auth)


async def _pergunta_atual(cliente: httpx.AsyncClient, auth: dict[str, str], chat_id: str) -> str:
    return str((await cliente.get(f"{BASE}/{chat_id}", headers=auth)).json()["resposta"])


async def test_repeticao_de_resposta_lenta_devolve_a_anterior_sem_avancar(
    cliente: httpx.AsyncClient, auth: dict[str, str], resposta_lenta: None, capsys: pytest.CaptureFixture[str]
) -> None:
    chat_id = await _criar(cliente, auth)
    primeira = await _responder(cliente, auth, chat_id, "true")  # tem o número? Sim
    assert re.search("Qual o número do processo", primeira.json()["resposta"])
    capsys.readouterr()
    repetida = await _responder(cliente, auth, chat_id, "true")  # a Tykhe repete a mesma mensagem
    assert repetida.status_code == 200
    assert repetida.json() == primeira.json(), "a repetição devolve a resposta já calculada"
    # Sem a conferência, o "true" seria lido como o número do processo e a conversa estaria na pergunta do RG.
    assert re.search("Qual o número do processo", await _pergunta_atual(cliente, auth, chat_id))
    assert '"evento":"resposta_repetida"' in capsys.readouterr().out


async def test_o_numero_repetido_nao_vira_rg(cliente: httpx.AsyncClient, auth: dict[str, str], resposta_lenta: None) -> None:
    # O caso do teste na homologação (2026-11-27): o número chegou duas vezes e a segunda foi lida como RG.
    chat_id = await _criar(cliente, auth)
    await _responder(cliente, auth, chat_id, "true")
    primeira = await _responder(cliente, auth, chat_id, "0000088-95.2026.8.19.0010")
    assert re.search("RG da pessoa presa", primeira.json()["resposta"])
    repetida = await _responder(cliente, auth, chat_id, "0000088-95.2026.8.19.0010")
    assert repetida.json() == primeira.json()
    assert re.search("RG da pessoa presa", await _pergunta_atual(cliente, auth, chat_id))
    # E a conversa segue normalmente com o RG de verdade.
    rg = await _responder(cliente, auth, chat_id, "11111111111")
    assert re.search("Confirma que a pessoa presa é", rg.json()["resposta"])


async def test_duas_respostas_iguais_ao_mesmo_tempo_avancam_uma_vez_so(
    cliente: httpx.AsyncClient, auth: dict[str, str], resposta_lenta: None
) -> None:
    chat_id = await _criar(cliente, auth)
    a, b = await asyncio.gather(_responder(cliente, auth, chat_id, "true"), _responder(cliente, auth, chat_id, "true"))
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert re.search("Qual o número do processo", await _pergunta_atual(cliente, auth, chat_id))


async def test_resposta_rapida_repetida_de_proposito_e_lida_normalmente(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    # Sem o `resposta_lenta`: a primeira respondeu em milissegundos, e o "true" de novo é a resposta à próxima pergunta.
    chat_id = await _criar(cliente, auth)
    primeira = await _responder(cliente, auth, chat_id, "true")
    segunda = await _responder(cliente, auth, chat_id, "true")
    assert segunda.json() != primeira.json()
    assert re.search("RG da pessoa presa", segunda.json()["resposta"])


async def test_mesma_resposta_depois_da_janela_e_lida_normalmente(
    cliente: httpx.AsyncClient, auth: dict[str, str], resposta_lenta: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(atendimentos, "JANELA_REENVIO_S", -1.0)  # nenhuma repetição cabe na janela
    chat_id = await _criar(cliente, auth)
    primeira = await _responder(cliente, auth, chat_id, "true")
    segunda = await _responder(cliente, auth, chat_id, "true")
    assert segunda.json() != primeira.json()


async def test_resposta_diferente_depois_de_resposta_lenta_avanca(
    cliente: httpx.AsyncClient, auth: dict[str, str], resposta_lenta: None
) -> None:
    chat_id = await _criar(cliente, auth)
    await _responder(cliente, auth, chat_id, "true")
    segunda = await _responder(cliente, auth, chat_id, "0000088-95.2026.8.19.0010")
    assert re.search("RG da pessoa presa", segunda.json()["resposta"])


async def test_conversas_diferentes_nao_se_misturam(cliente: httpx.AsyncClient, auth: dict[str, str], resposta_lenta: None) -> None:
    a, b = await _criar(cliente, auth), await _criar(cliente, auth)
    await _responder(cliente, auth, a, "true")
    r = await _responder(cliente, auth, b, "true")
    assert re.search("Qual o número do processo", r.json()["resposta"])


async def test_erro_nao_fica_guardado_para_repeticao(cliente: httpx.AsyncClient, auth: dict[str, str], resposta_lenta: None) -> None:
    r = await _responder(cliente, auth, "nunca-criado", "true")
    assert r.status_code == 404
    assert atendimentos._ultimas_respostas == {}


async def test_validacoes_de_sempre_continuam(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    assert (await cliente.post(f"{BASE}/respostas", json={"resposta": "x"}, headers=auth)).status_code == 400
    assert (await cliente.post(f"{BASE}/respostas", json={"chatId": "x"}, headers=auth)).status_code == 400
    assert (await cliente.post(f"{BASE}/respostas", json={"chatId": "x", "resposta": ""}, headers=auth)).status_code == 400


async def test_violencia_domestica_continua_igual(cliente: httpx.AsyncClient, auth: dict[str, str], resposta_lenta: None) -> None:
    # O fluxo de violência doméstica passa pela mesma rota: a repetição de uma resposta lenta devolve a anterior, e uma
    # resposta nova avança como antes.
    chat_id = await _criar(cliente, auth, ID_VIOLENCIA_DOMESTICA)
    primeira = await _responder(cliente, auth, chat_id, "true")  # é a vítima? Sim
    assert primeira.status_code == 200
    assert (await _responder(cliente, auth, chat_id, "true")).json() == primeira.json()
    seguinte = await _responder(cliente, auth, chat_id, "false")
    assert seguinte.status_code == 200
    assert seguinte.json()["resposta"] != primeira.json()["resposta"]
