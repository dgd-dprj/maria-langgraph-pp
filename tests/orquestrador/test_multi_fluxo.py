"""O multi-fluxo no grafo do orquestrador (#435, fase 1a da #279), com a IA simulada.

Só no release (`MARIA_AMBIENTE=release`). Na produção, a classificação por necessidades nem é chamada.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.types import Command

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA
from maria.orquestrador import graph
from maria.orquestrador.graph import obter_grafo
from tests.fluxos.conftest import novo_config, pergunta
from tests.orquestrador.conftest import Modelo

TOKENS = {"tokensEntrada": 11, "tokensSaida": 7, "tokensTotal": 18}
# O CPF da Tykhe (CPF de teste do Verde simulado) vai para o fluxo em `dadosConhecidos`, e o fluxo não o pergunta.
CONHECIDOS = {"cpf": "11111111111"}


def nec(i: str, evidencia: str = "", urgente: bool = False) -> dict[str, Any]:
    return {"id": i, "evidencia": evidencia, "evidenciaClara": True, "urgente": urgente}


PP = nec(ID_PESSOA_PRESA, "meu irmao ta peso faz 2 anos")
PLANO = nec(ID_PROBLEMAS_PLANO_SAUDE, "a unimed n quer libera a cirurgia dela", urgente=True)
VD = nec(ID_VIOLENCIA_DOMESTICA, "meu companheiro me ameaça")
SAUDE = nec("tykhe:saude", "o posto n marca o exame")


class Conversa:
    def __init__(self) -> None:
        self.grafo = obter_grafo()
        self.config = novo_config("teste-orq-multi")

    async def iniciar(self, mensagem: str = "relato") -> dict[str, Any]:
        r: dict[str, Any] = await self.grafo.ainvoke({"mensagem": mensagem, "dadosConhecidos": CONHECIDOS}, self.config)
        return r

    async def responder(self, resposta: str) -> dict[str, Any]:
        r: dict[str, Any] = await self.grafo.ainvoke(Command(resume=resposta), self.config)
        return r


@pytest.fixture
def release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARIA_AMBIENTE", "release")


def _roteiro(modelo: Modelo, *necessidades: dict[str, Any]) -> None:
    modelo.classificacoes = [{"necessidades": list(necessidades), **TOKENS}]


@pytest.mark.usefixtures("release")
async def test_dois_assuntos_perguntam_a_ordem_com_botoes(modelo: Modelo) -> None:
    _roteiro(modelo, PP, PLANO)
    r = await Conversa().iniciar()
    assert pergunta(r) == {
        "pergunta": (
            "Entendi. Você falou de duas coisas: o plano de saúde e a pessoa presa.\n"
            "Vou começar pelo plano de saúde, porque parece mais urgente.\n"
            "Depois, falamos da pessoa presa.\n"
            "Pode ser assim?"
        ),
        "tipo": "sim_nao",
        "opcoes": ["Sim", "Não"],
        "etapa": "ordem",
    }
    assert r["tokensGastosRodada"] == 18


@pytest.mark.usefixtures("release")
@pytest.mark.parametrize("resposta", ["true", "Sim", "pode"])
async def test_sim_segue_a_ordem_e_o_resto_fica_pendente(modelo: Modelo, resposta: str) -> None:
    _roteiro(modelo, PP, PLANO)
    c = Conversa()
    await c.iniciar()
    r = await c.responder(resposta)
    assert pergunta(r) is None
    assert (r["statusFinal"], r["flowIdEscolhido"]) == ("identificado", ID_PROBLEMAS_PLANO_SAUDE)
    assert r["assuntosPendentes"] == [
        {
            "nome": "a pessoa presa",
            "urgente": False,
            "urgencia": "urgente",
            "flowId": ID_PESSOA_PRESA,
            "dadosConhecidos": {"parentesco": "Irmão(a)"},
        }
    ]
    assert r["ordemPerguntada"] is True


@pytest.mark.usefixtures("release")
@pytest.mark.parametrize("resposta", ["false", "Não", "nao quero"])
async def test_nao_com_dois_assuntos_troca_a_ordem(modelo: Modelo, resposta: str) -> None:
    _roteiro(modelo, PP, PLANO)
    c = Conversa()
    await c.iniciar()
    r = await c.responder(resposta)
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
    assert r["assuntosPendentes"] == [
        {"nome": "o plano de saúde", "urgente": True, "urgencia": "urgente", "flowId": ID_PROBLEMAS_PLANO_SAUDE}
    ]


@pytest.mark.usefixtures("release")
async def test_nao_com_tres_assuntos_pergunta_qual_primeiro(modelo: Modelo) -> None:
    _roteiro(modelo, nec(ID_PESSOA_PRESA, "meu filho foi preso"), VD, SAUDE)
    c = Conversa()
    await c.iniciar()
    r = await c.responder("Não")
    assert pergunta(r) == {
        "pergunta": "Tudo bem. Qual você quer resolver primeiro?\n• a saúde\n• a situação que você contou\n• a pessoa presa",
        "tipo": "texto",
        "etapa": "primeiro",
    }
    r = await c.responder("a do meu filho")
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
    assert [p["nome"] for p in r["assuntosPendentes"]] == ["a saúde", "a situação que você contou"]


@pytest.mark.usefixtures("release")
async def test_qual_primeiro_sem_entender_segue_a_ordem_proposta(modelo: Modelo) -> None:
    _roteiro(modelo, PP, VD, SAUDE)
    c = Conversa()
    await c.iniciar()
    await c.responder("Não")
    r = await c.responder("tanto faz")
    assert r["flowIdEscolhido"] == "tykhe:saude"


@pytest.mark.usefixtures("release")
async def test_nome_do_assunto_na_resposta_da_ordem_passa_para_a_frente(modelo: Modelo) -> None:
    _roteiro(modelo, PP, PLANO)
    c = Conversa()
    await c.iniciar()
    r = await c.responder("o do meu irmão primeiro")
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA


@pytest.mark.usefixtures("release")
async def test_resposta_que_a_maria_nao_entende_segue_a_ordem(modelo: Modelo) -> None:
    _roteiro(modelo, PP, PLANO)
    c = Conversa()
    await c.iniciar()
    r = await c.responder("hmm")
    assert r["flowIdEscolhido"] == ID_PROBLEMAS_PLANO_SAUDE


@pytest.mark.usefixtures("release")
async def test_primeiro_assunto_da_tykhe_e_o_fluxo_da_maria_fica_pendente(modelo: Modelo) -> None:
    _roteiro(modelo, PP, SAUDE)
    c = Conversa()
    await c.iniciar()
    r = await c.responder("true")
    assert r["flowIdEscolhido"] == "tykhe:saude"
    assert r["assuntosPendentes"] == [
        {
            "nome": "a pessoa presa",
            "urgente": False,
            "urgencia": "urgente",
            "flowId": ID_PESSOA_PRESA,
            "dadosConhecidos": {"parentesco": "Irmão(a)"},
        }
    ]


@pytest.mark.usefixtures("release")
async def test_um_assunto_segue_direto_sem_perguntar_a_ordem(modelo: Modelo) -> None:
    _roteiro(modelo, PP)
    r = await Conversa().iniciar()
    assert pergunta(r) is None
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
    assert not r.get("assuntosPendentes")
    assert not r.get("ordemPerguntada")


@pytest.mark.usefixtures("release")
async def test_duvida_entre_opcoes_continua_com_a_desambiguacao_de_hoje(modelo: Modelo) -> None:
    modelo.classificacoes = [{"necessidades": [], "idsEmAmbiguidade": [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA], **TOKENS}]
    modelo.perguntas = [{"pergunta": "P?", "viaIA": True, **TOKENS}]
    r = await Conversa().iniciar()
    assert pergunta(r) == {"pergunta": "P?", "tipo": "texto"}


@pytest.mark.usefixtures("release")
async def test_os_dois_na_desambiguacao_vira_fila(modelo: Modelo) -> None:
    """ "Os dois" na resposta à pergunta de esclarecimento vira duas necessidades (regra da fase 0)."""
    modelo.classificacoes = [
        {"necessidades": [], "idsEmAmbiguidade": [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA], **TOKENS},
        {"necessidades": [PP, VD], **TOKENS},
    ]
    modelo.perguntas = [{"pergunta": "P?", "viaIA": True, **TOKENS}]
    c = Conversa()
    await c.iniciar()
    r = await c.responder("os dois")
    p = pergunta(r)
    assert p is not None
    assert p["etapa"] == "ordem"


async def test_producao_nao_chama_a_classificacao_por_necessidades(modelo: Modelo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARIA_AMBIENTE", raising=False)
    chamadas: list[Any] = []

    async def nao_devia(*args: Any) -> Any:
        chamadas.append(args)
        raise AssertionError("classificação por necessidades na produção")

    monkeypatch.setattr(graph, "classificar_necessidades", nao_devia)
    modelo.classificacoes = [{"ids": [ID_PESSOA_PRESA], "viaIA": True, **TOKENS}]
    r = await Conversa().iniciar()
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
    assert chamadas == []
    assert "fila" not in r and "assuntosPendentes" not in r
