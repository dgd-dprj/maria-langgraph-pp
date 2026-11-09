"""O que o relato já diz chega aos fluxos pelo orquestrador, sem a Maria perguntar de novo (#438).

Verde simulado: o processo 0000088-95.2026.8.19.0010 e o RG 11111111111 são encontrados; o CEP é do Rio.
"""

from __future__ import annotations

from itertools import count
from typing import Any

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA, fluxos_por_id
from maria.fluxos.pessoa_presa.graph import TEXTO_PARENTESCO
from maria.fluxos.plano_saude.graph import TEXTO_CPF_OUTRA, TEXTO_PARA_QUEM
from maria.fluxos.violencia_domestica.graph import TEXTO_EH_VITIMA

BASE = "/atendimentos/orquestrador"
# #450: no release, sem CPF na 1ª chamada a Maria pergunta o CPF antes de abrir o fluxo. Com o CPF da Tykhe (CPF de
# teste do Verde simulado), o fluxo abre direto, como estes testes esperam.
CPF = "11111111111"
_ids = count(1)


def _chat() -> str:
    return f"teste-orq-parentesco-{next(_ids)}"


def _simular(monkeypatch: pytest.MonkeyPatch, fluxo: str = ID_PESSOA_PRESA) -> None:
    """Depois do fixture `cliente`, que apaga as variáveis do simulado."""
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", fluxo)
    monkeypatch.delenv("MOCK_NECESSIDADES", raising=False)
    monkeypatch.delenv("EXTRACAO_LIVRE_IA", raising=False)


async def _estado(fluxo: str, chat: str) -> dict[str, Any]:
    estado = await fluxos_por_id[fluxo].obter_grafo().aget_state({"configurable": {"thread_id": chat}})
    return dict(estado.values)


async def _conversar(
    cliente: httpx.AsyncClient, auth: dict[str, str], chat: str, primeira: dict[str, Any], parentesco: str = "não sei"
) -> list[str]:
    """Responde o caminho feliz da pessoa presa e devolve todas as perguntas que a Maria fez."""
    perguntas = [primeira["resposta"]]
    corpo = primeira
    for _ in range(14):
        if corpo["status"] != "em_andamento":
            break
        pergunta = corpo["resposta"]
        if "qual o número" in pergunta.lower():
            resposta = "0000088-95.2026.8.19.0010"
        elif "RG" in pergunta:
            resposta = "11111111111"
        elif pergunta == TEXTO_PARENTESCO or "mãe ou o pai" in pergunta or "qual deles" in pergunta:
            resposta = parentesco
        elif corpo["tipoResposta"] == "sim_nao":
            resposta = "true"
        else:
            resposta = "não sei"
        corpo = (await cliente.post("/atendimentos/respostas", json={"chatId": chat, "resposta": resposta}, headers=auth)).json()
        perguntas.append(corpo["resposta"])
    return perguntas


async def _abrir(
    cliente: httpx.AsyncClient, auth: dict[str, str], mensagem: str, dados: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    chat = _chat()
    corpo = {"chatId": chat, "mensagem": mensagem, **({"dadosConhecidos": dados} if dados else {})}
    r = await cliente.post(BASE, json=corpo, headers=auth)
    return chat, r.json()


# ---- pessoa presa --------------------------------------------------------------------


@pytest.mark.parametrize("ambiente", [None, "release"])
async def test_meu_primo_foi_preso_nao_pergunta_o_parentesco(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, ambiente: str | None
) -> None:
    _simular(monkeypatch)
    if ambiente:
        monkeypatch.setenv("MARIA_AMBIENTE", ambiente)
    chat, primeira = await _abrir(cliente, auth, "Meu primo foi preso e quero saber quando sai", {"cpf": CPF} if ambiente else None)
    assert primeira["flowId"] == ID_PESSOA_PRESA
    assert (await _estado(ID_PESSOA_PRESA, chat))["parentesco"] == "Primo(a)"
    perguntas = await _conversar(cliente, auth, chat, primeira)
    assert TEXTO_PARENTESCO not in perguntas
    assert not any("mãe ou o pai" in x or "qual deles" in x for x in perguntas)


async def test_meu_avo_foi_preso_vira_neto(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _simular(monkeypatch)
    chat, _ = await _abrir(cliente, auth, "meu avô foi preso")
    assert (await _estado(ID_PESSOA_PRESA, chat))["parentesco"] == "Neto(a)"


async def test_meu_filho_pergunta_so_se_e_mae_ou_pai(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _simular(monkeypatch)
    chat, primeira = await _abrir(cliente, auth, "meu filho foi preso e quero saber do processo")
    perguntas = await _conversar(cliente, auth, chat, primeira, parentesco="sou a mãe")
    assert "Você é a mãe ou o pai dele?" in perguntas
    assert TEXTO_PARENTESCO not in perguntas
    assert (await _estado(ID_PESSOA_PRESA, chat))["parentesco"] == "Mãe"


async def test_dois_presos_pergunta_qual_deles(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _simular(monkeypatch)
    chat, primeira = await _abrir(cliente, auth, "meu primo e meu irmão foram presos ontem")
    perguntas = await _conversar(cliente, auth, chat, primeira, parentesco="o irmão")
    assert "Você falou do seu primo e do seu irmão. Sobre qual deles é este atendimento?" in perguntas
    assert (await _estado(ID_PESSOA_PRESA, chat))["parentesco"] == "Irmão(a)"


async def test_escolheu_o_filho_pergunta_mae_ou_pai_depois(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _simular(monkeypatch)
    chat, _ = await _abrir(cliente, auth, "minha filha e meu sobrinho foram presos")
    corpo: dict[str, Any] = {}
    for resposta in ("true", "0000088-95.2026.8.19.0010", "11111111111", "true"):
        corpo = (await cliente.post("/atendimentos/respostas", json={"chatId": chat, "resposta": resposta}, headers=auth)).json()
    assert corpo["resposta"] == "Você falou da sua filha e do seu sobrinho. Sobre qual deles é este atendimento?"
    corpo = (await cliente.post("/atendimentos/respostas", json={"chatId": chat, "resposta": "a minha filha"}, headers=auth)).json()
    assert corpo["resposta"] == "Você é a mãe ou o pai dela?"
    await cliente.post("/atendimentos/respostas", json={"chatId": chat, "resposta": "pai"}, headers=auth)
    assert (await _estado(ID_PESSOA_PRESA, chat))["parentesco"] == "Pai"


async def test_parentesco_da_tykhe_nao_e_trocado(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _simular(monkeypatch)
    chat, _ = await _abrir(cliente, auth, "Meu primo foi preso", {"parentesco": "Amigo(a)"})
    assert (await _estado(ID_PESSOA_PRESA, chat))["parentesco"] == "Amigo(a)"


# ---- plano de saúde (só no release) e violência doméstica ------------------------------


async def test_plano_da_minha_mae_pula_o_para_voce(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _simular(monkeypatch, ID_PROBLEMAS_PLANO_SAUDE)
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    chat, primeira = await _abrir(
        cliente, auth, "o plano da minha mãe negou a cirurgia dela", {"endereco": {"cep": "20000000"}, "cpf": CPF}
    )
    assert primeira["resposta"] == TEXTO_CPF_OUTRA
    assert (await _estado(ID_PROBLEMAS_PLANO_SAUDE, chat))["paraSi"] is False


async def test_meu_plano_pula_o_para_voce(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _simular(monkeypatch, ID_PROBLEMAS_PLANO_SAUDE)
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    _, primeira = await _abrir(cliente, auth, "meu plano negou minha cirurgia", {"endereco": {"cep": "20000000"}, "cpf": CPF})
    assert primeira["resposta"] != TEXTO_PARA_QUEM
    assert primeira["tipoResposta"] == "link_imagem"


async def test_plano_sem_dizer_de_quem_pergunta(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _simular(monkeypatch, ID_PROBLEMAS_PLANO_SAUDE)
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    _, primeira = await _abrir(cliente, auth, "o plano negou a cirurgia", {"endereco": {"cep": "20000000"}, "cpf": CPF})
    assert primeira["resposta"] == TEXTO_PARA_QUEM


async def test_violencia_me_bate_pula_o_eh_vitima(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _simular(monkeypatch, ID_VIOLENCIA_DOMESTICA)
    chat, primeira = await _abrir(cliente, auth, "meu marido me bate quando bebe")
    assert primeira["resposta"] != TEXTO_EH_VITIMA
    assert (await _estado(ID_VIOLENCIA_DOMESTICA, chat))["ehVitima"] is True


async def test_violencia_contra_outra_pessoa_continua_perguntando(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _simular(monkeypatch, ID_VIOLENCIA_DOMESTICA)
    _, primeira = await _abrir(cliente, auth, "o ex da minha filha ta ameaçando ela")
    assert primeira["resposta"] == TEXTO_EH_VITIMA
