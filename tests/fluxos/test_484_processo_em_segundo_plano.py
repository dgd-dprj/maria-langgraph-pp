"""#484: a consulta de processo no Verde roda em segundo plano enquanto a Maria já pergunta o RG.

A consulta leva uns 10 s e a Tykhe desiste de uma resposta em cerca de 11 s. O resultado entra no estado no `concluir`.
Verde falso; checkpointer em memória.
"""

import asyncio
import re
from typing import Any

import httpx
import pytest

from maria.fluxos.pessoa_presa import graph as grafo_pp
from maria.fluxos.pessoa_presa.api import MENSAGEM_HANDOFF_PROCESSO_NAO_LOCALIZADO
from maria.fluxos.pessoa_presa.graph import obter_grafo as obter_pp
from tests.fluxos.conftest import Fluxo, texto
from tests.fluxos.test_spec_fluxos import _rotas_pp, _verde
from tests.integracoes.conftest import TransporteFalso

NUMERO = "0000088-95.2026.8.19.0010"
DEPOIS_DO_NUMERO = ["11111111111", "Sim", "amigo"]  # RG, confirmação do nome e parentesco


def _consultas_de_processo(verde: TransporteFalso) -> int:
    return sum("/processo/consultar/" in r.url.raw_path.decode() for r in verde.requisicoes)


def _verde_com_processo_lento(verde: TransporteFalso, liberar: asyncio.Event, status: int = 200) -> None:
    """O Verde falso só responde o processo quando o teste libera; o resto responde na hora."""
    rotas = _rotas_pp()

    async def responder(requisicao: httpx.Request) -> httpx.Response:
        caminho = requisicao.url.raw_path.decode().removeprefix("/api/integra")
        if caminho.startswith("/processo/consultar/"):
            await liberar.wait()
            return httpx.Response(status, json={"dados": {"id": 31, "origem": "SEEU"}} if status == 200 else {"mensagem": "erro"})
        for (metodo, prefixo), (st, corpo) in rotas.items():
            if requisicao.method == metodo and caminho.startswith(prefixo):
                return httpx.Response(st, json=corpo)
        return httpx.Response(404, json={"dados": None})

    verde.tratador = responder


@pytest.fixture(autouse=True)
def _sem_consultas_de_outros_testes() -> None:
    grafo_pp._consultas_processo.clear()


async def test_o_numero_nao_espera_o_verde_e_o_rg_e_perguntado_logo(verde_real: TransporteFalso) -> None:
    liberar = asyncio.Event()  # o Verde nunca responde o processo durante a pergunta do número
    _verde_com_processo_lento(verde_real, liberar)
    f = Fluxo(obter_pp(), "teste-484-lento")
    await f.iniciar()
    r = await asyncio.wait_for(f.responder("true", NUMERO), timeout=5)  # com a consulta síncrona, isto não voltaria
    assert re.search("RG da pessoa presa", texto(r))
    assert "dadosProcesso" not in r, "o resultado só entra no estado no concluir"
    liberar.set()
    r = await f.responder(*DEPOIS_DO_NUMERO)
    assert r["statusFinal"] == "concluido"
    assert r["dadosProcesso"]["origem"] == "SEEU"
    assert _consultas_de_processo(verde_real) == 1


async def test_numero_seguido_de_rg_normal_conclui_como_antes(verde_real: TransporteFalso) -> None:
    _verde(verde_real, _rotas_pp())
    f = Fluxo(obter_pp(), "teste-484-normal")
    await f.iniciar()
    await f.responder("true", NUMERO)
    r = await f.responder(*DEPOIS_DO_NUMERO)
    assert (r["statusFinal"], r["dadosProcesso"]["id"], r["statusConsultaProcesso"]) == ("concluido", 31, None)
    assert _consultas_de_processo(verde_real) == 1


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_verde_que_nao_acha_o_processo_continua_indo_ao_humano_com_a_mesma_mensagem(verde_real: TransporteFalso, status: int) -> None:
    rotas = _rotas_pp()
    rotas[("GET", "/processo/consultar/")] = (status, {"mensagem": "erro do Verde"})
    _verde(verde_real, rotas)
    f = Fluxo(obter_pp(), "teste-484-nao-acha")
    await f.iniciar()
    await f.responder("true", NUMERO)
    r = await f.responder(*DEPOIS_DO_NUMERO)
    assert r["motivoHandoff"] == "origem_processo_nao_suportada"
    assert r["mensagemFinal"] == MENSAGEM_HANDOFF_PROCESSO_NAO_LOCALIZADO
    assert r["statusConsultaProcesso"] == status


async def test_verde_fora_do_ar_no_processo_vai_ao_humano(verde_real: TransporteFalso) -> None:
    rotas = _rotas_pp()
    rotas[("GET", "/processo/consultar/")] = (503, {"mensagem": "fora do ar"})
    _verde(verde_real, rotas)
    f = Fluxo(obter_pp(), "teste-484-503")
    await f.iniciar()
    await f.responder("true", NUMERO)
    r = await f.responder(*DEPOIS_DO_NUMERO)
    assert (r["statusFinal"], r["motivoHandoff"]) == ("handoff_humano", "origem_processo_nao_suportada")


async def test_erro_inesperado_na_consulta_em_segundo_plano_vai_ao_humano(
    verde_real: TransporteFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def quebra(numero: str) -> Any:
        raise RuntimeError("falha inesperada")

    monkeypatch.setattr(grafo_pp, "consultar_processo_verde", quebra)
    _verde(verde_real, _rotas_pp())
    f = Fluxo(obter_pp(), "teste-484-erro")
    await f.iniciar()
    r = await f.responder("true", NUMERO)
    assert re.search("RG da pessoa presa", texto(r)), "o erro não derruba a conversa"
    r = await f.responder(*DEPOIS_DO_NUMERO)
    assert (r["statusFinal"], r["motivoHandoff"]) == ("handoff_humano", "origem_processo_nao_suportada")


async def test_verde_que_nao_responde_no_prazo_vai_ao_humano_sem_travar(
    verde_real: TransporteFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(grafo_pp, "PRAZO_ESPERA_PROCESSO_S", 0.05)
    _verde_com_processo_lento(verde_real, asyncio.Event())  # nunca libera
    f = Fluxo(obter_pp(), "teste-484-prazo")
    await f.iniciar()
    await f.responder("true", NUMERO)
    r = await asyncio.wait_for(f.responder(*DEPOIS_DO_NUMERO), timeout=5)
    assert (r["statusFinal"], r["motivoHandoff"]) == ("handoff_humano", "origem_processo_nao_suportada")
    assert r["dadosProcesso"] == {"encontrado": False}


async def test_tarefa_perdida_consulta_na_hora_no_concluir(verde_real: TransporteFalso) -> None:
    # A conversa continuou em outro processo (ou houve reinício): a tarefa em memória não existe mais.
    _verde(verde_real, _rotas_pp())
    f = Fluxo(obter_pp(), "teste-484-perdida")
    await f.iniciar()
    await f.responder("true", NUMERO)
    grafo_pp._consultas_processo.clear()
    r = await f.responder(*DEPOIS_DO_NUMERO)
    assert (r["statusFinal"], r["dadosProcesso"]["origem"]) == ("concluido", "SEEU")
    assert _consultas_de_processo(verde_real) == 2, "a consulta em segundo plano e a refeita no concluir"


async def test_sem_numero_de_processo_nao_consulta(verde_real: TransporteFalso) -> None:
    _verde(verde_real, _rotas_pp())
    f = Fluxo(obter_pp(), "teste-484-sem-numero")
    await f.iniciar()
    r = await f.responder("false", *DEPOIS_DO_NUMERO)
    assert r["motivoHandoff"] == "sem_numero_processo"
    assert _consultas_de_processo(verde_real) == 0
    assert grafo_pp._consultas_processo == {}


async def test_duas_conversas_ao_mesmo_tempo_nao_trocam_o_resultado(verde_real: TransporteFalso) -> None:
    # Cada conversa tem a sua consulta: o resultado de uma não vai para a outra.
    rotas = _rotas_pp()

    async def responder(requisicao: httpx.Request) -> httpx.Response:
        caminho = requisicao.url.raw_path.decode().removeprefix("/api/integra")
        if caminho.startswith("/processo/consultar/"):
            origem = "SEEU" if caminho.endswith("0010") else "PJe"
            return httpx.Response(200, json={"dados": {"id": 31, "origem": origem}})
        for (metodo, prefixo), (st, corpo) in rotas.items():
            if requisicao.method == metodo and caminho.startswith(prefixo):
                return httpx.Response(st, json=corpo)
        return httpx.Response(404, json={"dados": None})

    verde_real.tratador = responder
    a, b = Fluxo(obter_pp(), "teste-484-a"), Fluxo(obter_pp(), "teste-484-b")
    await a.iniciar()
    await b.iniciar()
    await a.responder("true", NUMERO)
    await b.responder("true", "0000088-95.2026.8.19.0099")
    ra, rb = await asyncio.gather(a.responder(*DEPOIS_DO_NUMERO), b.responder(*DEPOIS_DO_NUMERO))
    assert ra["dadosProcesso"]["origem"] == "SEEU"
    assert rb["dadosProcesso"]["origem"] == "PJe"
