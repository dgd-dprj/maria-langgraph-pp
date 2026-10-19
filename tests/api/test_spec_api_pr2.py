"""Testes novos da spec 07 (seção 6) para o PR 2 do módulo api (#246): o que a
conferência diferencial não cobre direto.

- D-2: `resume=""` dá o 500 de develop (EmptyInputError), e não um "não" silencioso;
- o bridge: os textos enviados ao WhatsApp (o log de develop não traz o texto);
- o roteador e a query do Fastify, em casos unitários.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from maria.api import atendimentos, webhook_whatsapp
from maria.api.pipeline import UrlInvalida, _consulta, _decodificar_parametro, _sanitizar
from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA
from maria.shared.atendimentos_db import obter_atendimentos_store

# ---- D-2: Command(resume="") -----------------------------------------------------------


async def test_d2_resposta_original_vazia_na_retomada_do_ttl_da_500_como_develop(
    cliente: httpx.AsyncClient, auth: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    # O único caminho até resume="" é a retomada depois da confirmação de TTL com a
    # resposta guardada vazia (concorrência na flag). Develop: EmptyInputError, 500.
    # O Python aceitaria "" e contaria como "não", sem nenhum sinal (spec 07, D-2).
    chat_id = "teste-d2"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    store = await obter_atendimentos_store()
    await store.marcar_aguardando_confirmacao_ttl(chat_id, "")
    capsys.readouterr()
    r = await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": "sim"}, headers=auth)
    assert r.status_code == 500
    assert r.json() == {"statusCode": 500, "error": "Internal Server Error", "message": "Received empty Command input"}
    erros = [json.loads(x) for x in capsys.readouterr().out.splitlines() if '"level":50' in x]
    assert erros and erros[0]["err"]["type"] == "EmptyInputError"
    assert erros[0]["err"]["name"] == "EmptyInputError"
    # E o grafo não avançou: continua na 1ª pergunta.
    get = await cliente.get(f"/atendimentos/{chat_id}", headers=auth)
    assert get.json()["resposta"] == "Você é a vítima de violência doméstica?"


# ---- bridge: textos enviados ao WhatsApp ---------------------------------------------


@pytest.fixture
def enviados(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    lista: list[tuple[str, str, str]] = []

    async def enviar(para: str, texto: str, chat_id: str) -> None:
        lista.append((para, texto, chat_id))

    monkeypatch.setattr(webhook_whatsapp, "enviar_mensagem_whatsapp", enviar)
    webhook_whatsapp.limpar_conversas_ativas_de_teste()
    return lista


def _mensagem(de: str, texto: Any) -> dict[str, Any]:
    return {"entry": [{"changes": [{"value": {"messages": [{"from": de, "type": "text", "text": {"body": texto}}]}}]}]}


async def test_bridge_sim_nao_lista_as_opcoes_e_conclusao_libera_o_numero(
    cliente: httpx.AsyncClient, enviados: list[tuple[str, str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_VIOLENCIA_DOMESTICA)
    await cliente.post("/webhook/whatsapp", json=_mensagem("551", "apanho do meu marido"))
    assert enviados[-1][1] == "Você é a vítima de violência doméstica?\n\n- Sim\n- Não"
    assert enviados[-1][2].startswith("whatsapp:551:")
    await cliente.post("/webhook/whatsapp", json=_mensagem("551", "não"))
    assert enviados[-1][1].startswith("Esse atendimento é destinado apenas para quem é vítima")
    assert webhook_whatsapp.chat_id_ativo_de_teste("551") is None, "atendimento concluído libera o número"


@pytest.mark.parametrize(
    ("tipo", "esperado"),
    [("tykhe:saude", webhook_whatsapp.MENSAGEM_REDIRECIONADO), ("tykhe:sair", webhook_whatsapp.MENSAGEM_SAIU)],
)
async def test_bridge_redirecionado_encerra_com_a_orientacao_fixa_225(
    cliente: httpx.AsyncClient, enviados: list[tuple[str, str, str]], monkeypatch: pytest.MonkeyPatch, tipo: str, esperado: str
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", tipo)
    await cliente.post("/webhook/whatsapp", json=_mensagem("552", "relato"))
    assert enviados == [("552", esperado, enviados[0][2])]


@pytest.mark.parametrize(
    ("texto", "eh_sair"),
    [
        ("#sair", True),
        ("  #SAIR  ", True),
        ("﻿#sair", True),  # o trim do JS remove o BOM
        ("#sair\x1c", False),  # e não remove \x1c, que o strip() do Python removeria
        ("# sair", False),
    ],
)
async def test_bridge_sair_com_o_trim_do_js(
    cliente: httpx.AsyncClient, enviados: list[tuple[str, str, str]], monkeypatch: pytest.MonkeyPatch, texto: str, eh_sair: bool
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    await cliente.post("/webhook/whatsapp", json=_mensagem("553", "meu irmão está preso"))
    aberto = webhook_whatsapp.chat_id_ativo_de_teste("553")
    await cliente.post("/webhook/whatsapp", json=_mensagem("553", texto))
    if eh_sair:
        assert enviados[-1][1] == webhook_whatsapp.MENSAGEM_SAIU
        assert webhook_whatsapp.chat_id_ativo_de_teste("553") is None
    else:
        assert enviados[-1][1] != webhook_whatsapp.MENSAGEM_SAIU
        assert webhook_whatsapp.chat_id_ativo_de_teste("553") == aberto


async def test_bridge_sair_sem_conversa_usa_o_chat_id_de_sem_conversa(
    cliente: httpx.AsyncClient, enviados: list[tuple[str, str, str]]
) -> None:
    await cliente.post("/webhook/whatsapp", json=_mensagem("554", "#sair"))
    assert enviados == [("554", webhook_whatsapp.MENSAGEM_NADA_PARA_SAIR, "whatsapp:sem-conversa-ativa")]


async def test_bridge_chamada_interna_passa_pelo_pipeline_com_a_chave_do_app(
    cliente: httpx.AsyncClient, enviados: list[tuple[str, str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Como o app.inject: a chamada interna tem o próprio log de requisição e usa a
    # API_KEY com que o app subiu, mesmo que o ambiente mude depois.
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    monkeypatch.setenv("API_KEY", "outra-chave-depois-da-subida")
    capsys.readouterr()
    r = await cliente.post("/webhook/whatsapp", json=_mensagem("555", "meu irmão está preso"))
    assert r.status_code == 200
    linhas = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    urls = [x["req"]["url"] for x in linhas if x.get("msg") == "incoming request"]
    assert urls == ["/webhook/whatsapp", "/atendimentos/orquestrador"]
    assert not any(x.get("evento") == "whatsapp_bridge_erro" for x in linhas), "a chamada interna autenticou"
    assert enviados[-1][1].startswith("Você tem o número do processo")


# ---- roteador e query (find-my-way e fast-querystring) --------------------------------


@pytest.mark.parametrize(
    ("url", "caminho", "consulta", "decodificar"),
    [
        ("/atendimentos/a%20b", "/atendimentos/a b", "", False),
        ("/atendimentos/a%2Fb", "/atendimentos/a%2Fb", "", True),
        ("/atendimentos/a%25b", "/atendimentos/a%25b", "", True),
        ("/atendimentos/x?y=%zz", "/atendimentos/x", "y=%zz", False),
        ("/flu%78os", "/fluxos", "", False),
        # Reservado e comum juntos: o decodeURI decodifica só o comum (conferido em develop).
        ("/atendimentos/a%2Fb%20c", "/atendimentos/a%2Fb c", "", True),
    ],
)
def test_sanitizar_como_o_find_my_way(url: str, caminho: str, consulta: str, decodificar: bool) -> None:
    assert _sanitizar(url) == (caminho, consulta, decodificar)


@pytest.mark.parametrize("url", ["/atendimentos/%zz", "/atendimentos/%E0%A4%A", "/x/%C0%AF", "/x/%ED%A0%80"])
def test_sanitizar_url_malformada(url: str) -> None:
    with pytest.raises(UrlInvalida):
        _sanitizar(url)


def test_parametro_decodifica_so_os_reservados() -> None:
    assert _decodificar_parametro("a%2Fb%25c%3Fd") == "a/b%c?d"


def test_consulta_como_o_fast_querystring() -> None:
    assert _consulta("a=1&a=2&b=x+y&c=%C3%A7&d=%zz&e&=v&f=a=b") == {
        "a": ["1", "2"],
        "b": "x y",
        "c": "ç",
        "d": "%zz",
        "e": "",
        "": "v",
        "f": "a=b",
    }


# ---- TTL: arredondamento e a fronteira exata (lacunas achadas pela mutação) -----------


@pytest.mark.parametrize(("horas", "esperado"), [(0.5, 1), (1.5, 2), (2.5, 3), (2.4999, 2), (0.0, 0)])
def test_horas_inativo_no_log_arredondam_como_math_round(horas: float, esperado: int) -> None:
    # Math.round: meio arredonda para cima. O round() do Python vai para o par (2.5 -> 2).
    assert atendimentos._arredondar_js(horas) == esperado


async def test_ttl_na_fronteira_exata_processa_a_resposta(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Develop compara `horasInativo > ttl`: com TTL 0 e a resposta no mesmo
    # milissegundo da última atividade, 0 > 0 é falso e a resposta é processada.
    chat_id = "teste-ttl-fronteira"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    store = await obter_atendimentos_store()
    atividade = await store.buscar_atividade(chat_id)
    assert atividade is not None
    instante = atividade["atualizadoEm"]

    class RelogioParado:
        @staticmethod
        def now(tz: Any = None) -> Any:
            return instante

    monkeypatch.setattr(atendimentos, "datetime", RelogioParado)
    monkeypatch.setenv("TTL_INATIVIDADE_HORAS", "0")
    r = await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": "true"}, headers=auth)
    assert r.json()["resposta"] == "Existe algum processo relacionado ao seu caso?", "0 > 0 é falso: processa, sem confirmação"
