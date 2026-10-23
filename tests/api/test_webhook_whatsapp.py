"""Traduzido de `test/webhookWhatsapp.test.ts` (develop @ 1157a6d): o bridge do
WhatsApp para o orquestrador (#198, #203, #225, #227), separado da Tykhe.

A classificação usa `MOCK_CLASSIFICACAO_FLOWID`, sem Bedrock; o envio ao WhatsApp
fica em modo mock (sem `WHATSAPP_ACCESS_TOKEN`).
"""

import asyncio
import time
from typing import Any

import httpx
import pytest

from maria.api.webhook_whatsapp import chat_id_ativo_de_teste, limpar_conversas_ativas_de_teste
from maria.fluxos import ID_PESSOA_PRESA
from maria.integracoes.whatsapp import extrair_mensagem_whatsapp
from maria.shared.atendimentos_db import obter_atendimentos_store

URL = "/webhook/whatsapp"


def payload_texto(de: str, texto: str) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "x",
                "changes": [
                    {
                        "value": {"messages": [{"from": de, "id": "wamid.teste", "type": "text", "text": {"body": texto}}]},
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def payload_status() -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "x", "changes": [{"value": {"statuses": [{"id": "wamid.x", "status": "delivered"}]}, "field": "messages"}]}],
    }


def numero(prefixo: str) -> str:
    return f"{prefixo}-{time.time_ns()}"


@pytest.fixture(autouse=True)
def conversas_limpas() -> None:
    limpar_conversas_ativas_de_teste()


def test_extrair_mensagem_de_texto_valida() -> None:
    assert extrair_mensagem_whatsapp(payload_texto("5521999990000", "oi")) == {"de": "5521999990000", "texto": "oi"}


def test_extrair_payload_de_status_none() -> None:
    assert extrair_mensagem_whatsapp(payload_status()) is None


def test_extrair_payload_sem_entry_none() -> None:
    assert extrair_mensagem_whatsapp({}) is None
    assert extrair_mensagem_whatsapp(None) is None


async def test_get_verify_token_correto_devolve_o_challenge(cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "segredo-teste")
    r = await cliente.get(f"{URL}?hub.mode=subscribe&hub.verify_token=segredo-teste&hub.challenge=abc123")
    assert r.status_code == 200
    assert r.text == "abc123"


async def test_get_verify_token_errado_403(cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "segredo-teste")
    r = await cliente.get(f"{URL}?hub.mode=subscribe&hub.verify_token=errado&hub.challenge=abc123")
    assert r.status_code == 403


async def test_primeira_mensagem_cai_no_orquestrador_e_abre_atendimento(
    cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    n = numero("test-wpp")
    r = await cliente.post(URL, json=payload_texto(n, "quero saber de um parente preso"))
    assert r.status_code == 200
    chat_id = chat_id_ativo_de_teste(n)
    assert chat_id is not None and chat_id.startswith(f"whatsapp:{n}:"), f"chatId deveria ter sido registrado, veio: {chat_id}"


async def test_payload_de_status_200_sem_criar_conversa(cliente: httpx.AsyncClient) -> None:
    n = numero("test-wpp-status")
    r = await cliente.post(URL, json=payload_status())
    assert r.status_code == 200
    assert chat_id_ativo_de_teste(n) is None


async def test_segunda_mensagem_com_atendimento_em_andamento_reaproveita_o_chat_id(
    cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Achado #1 do code review da #198.
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    n = numero("test-wpp-continua")
    r1 = await cliente.post(URL, json=payload_texto(n, "quero saber de um parente preso"))
    assert r1.status_code == 200
    antes = chat_id_ativo_de_teste(n)
    r2 = await cliente.post(URL, json=payload_texto(n, "Amigo(a)"))
    assert r2.status_code == 200
    assert chat_id_ativo_de_teste(n) == antes, "deveria reaproveitar o chatId, sem reclassificar"


async def test_duas_mensagens_concorrentes_do_mesmo_numero_sao_serializadas(
    cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Achado #2 do code review da #198.
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    n = numero("test-wpp-concorrente")
    corpo = payload_texto(n, "quero saber de um parente preso")
    ra, rb = await asyncio.gather(cliente.post(URL, json=corpo), cliente.post(URL, json=corpo))
    assert ra.status_code == 200
    assert rb.status_code == 200
    assert chat_id_ativo_de_teste(n), "exatamente 1 chatId ativo, sem corrida criando 2"


async def test_sair_sem_conversa_ativa_nao_cria_atendimento(cliente: httpx.AsyncClient) -> None:
    n = numero("test-wpp-sair-vazio")
    r = await cliente.post(URL, json=payload_texto(n, "#sair"))
    assert r.status_code == 200
    assert chat_id_ativo_de_teste(n) is None


async def test_sair_no_meio_expira_com_saida_manual_e_libera_o_numero(cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    n = numero("test-wpp-sair")
    await cliente.post(URL, json=payload_texto(n, "quero saber de um parente preso"))
    aberto = chat_id_ativo_de_teste(n)
    assert aberto, "deveria ter aberto atendimento antes do #sair"

    r_sair = await cliente.post(URL, json=payload_texto(n, "#sair"))
    assert r_sair.status_code == 200
    assert chat_id_ativo_de_teste(n) is None, "conversa deveria ter sido invalidada"
    store = await obter_atendimentos_store()
    atividade = await store.buscar_atividade(aberto)
    assert atividade is not None and atividade.get("statusFinal") == "expirado"

    r3 = await cliente.post(URL, json=payload_texto(n, "oi, começando de novo"))
    assert r3.status_code == 200
    assert chat_id_ativo_de_teste(n) != aberto, "depois do #sair, atendimento NOVO"


async def test_sim_na_confirmacao_de_ttl_continua_o_atendimento_227(cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    n = numero("test-wpp-ttl-sim")
    await cliente.post(URL, json=payload_texto(n, "quero saber de um parente preso"))
    chat_id = chat_id_ativo_de_teste(n)
    assert chat_id, "deveria ter aberto atendimento"

    monkeypatch.setenv("TTL_INATIVIDADE_HORAS", "0")
    await cliente.post(URL, json=payload_texto(n, "Amigo(a)"))
    monkeypatch.delenv("TTL_INATIVIDADE_HORAS")
    store = await obter_atendimentos_store()
    pendente = await store.buscar_atividade(chat_id)
    assert pendente is not None and pendente["aguardandoConfirmacaoTtl"] is True, "deveria esperar a confirmação de TTL"

    r = await cliente.post(URL, json=payload_texto(n, "sim"))
    assert r.status_code == 200
    depois = await store.buscar_atividade(chat_id)
    assert depois is not None and depois.get("statusFinal") != "expirado"
    assert depois["aguardandoConfirmacaoTtl"] is False
    assert chat_id_ativo_de_teste(n) == chat_id, "a conversa continua no mesmo chatId"


async def test_caso_redirecionado_encerra_a_conversa_e_libera_o_numero_225(
    cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", "tykhe:saude")
    n = numero("test-wpp-redirecionado")
    r = await cliente.post(URL, json=payload_texto(n, "preciso de um remédio"))
    assert r.status_code == 200
    assert chat_id_ativo_de_teste(n) is None, "conversa encerrada: a próxima mensagem abre outra"
