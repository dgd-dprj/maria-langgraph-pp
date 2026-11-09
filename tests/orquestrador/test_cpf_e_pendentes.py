"""O CPF no começo e a pergunta dos assuntos guardados no grafo do orquestrador (#450), com a IA simulada.

Só no release (`MARIA_AMBIENTE=release`). A leitura da resposta à pergunta dos pendentes não usa IA.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.types import Command

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE
from maria.orquestrador.fila import AssuntoGuardado, opcoes_pendentes, pendente_escolhido, texto_pendentes
from maria.orquestrador.graph import TEXTO_CPF, obter_grafo
from tests.fluxos.conftest import novo_config, pergunta
from tests.orquestrador.conftest import Modelo

TOKENS = {"tokensEntrada": 11, "tokensSaida": 7, "tokensTotal": 18}
PRESA: AssuntoGuardado = {"chatIdOrigem": "a", "posicao": 2, "nome": "a pessoa presa", "urgente": False, "flowId": ID_PESSOA_PRESA}
NOVO: AssuntoGuardado = {"chatIdOrigem": "a", "posicao": 3, "nome": "o caso novo", "urgente": False, "tipoCaso": "novo-processo"}
PLANO: AssuntoGuardado = {
    "chatIdOrigem": "b",
    "posicao": 2,
    "nome": "o plano de saúde",
    "urgente": True,
    "flowId": ID_PROBLEMAS_PLANO_SAUDE,
}


def test_texto_e_opcoes_com_um_pendente() -> None:
    assert texto_pendentes([PRESA]) == (
        "Você tem um assunto guardado: a pessoa presa. Quer falar dele agora ou do que você acabou de contar?"
    )
    assert opcoes_pendentes([PRESA]) == ["O que acabei de contar", "A pessoa presa"]


def test_texto_e_opcoes_com_varios_pendentes() -> None:
    assert texto_pendentes([PRESA, NOVO]) == (
        "Você tem assuntos guardados: a pessoa presa e o caso novo. Quer falar de um deles agora ou do que você acabou de contar?"
    )
    assert texto_pendentes([PRESA, NOVO, PLANO]).startswith("Você tem assuntos guardados: a pessoa presa, o caso novo e o plano de saúde.")
    assert opcoes_pendentes([PRESA, NOVO, PLANO]) == ["O que acabei de contar", "A pessoa presa", "O caso novo", "O plano de saúde"]


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        # O texto da opção e o número dela.
        ("O que acabei de contar", None),
        ("1", None),
        ("A pessoa presa", 0),
        ("o caso novo", 1),
        ("caso novo", 1),
        ("2", 0),
        (" 3 ", 1),
        ("4", None),
        # Respostas livres.
        ("quero falar do caso novo", 1),
        ("a da cadeia", 0),
        ("o que eu acabei de contar", None),
        ("o de hoje", None),
        # Não entendeu: segue com o que acabou de contar.
        ("hmm", None),
        ("", None),
    ],
)
def test_pendente_escolhido(resposta: str, esperado: int | None) -> None:
    assert pendente_escolhido(resposta, [PRESA, NOVO]) == esperado


def test_com_um_pendente_so_dele_escolhe_o_guardado() -> None:
    assert pendente_escolhido("dele", [PRESA]) == 0
    assert pendente_escolhido("do guardado", [PRESA]) == 0
    assert pendente_escolhido("dele", [PRESA, NOVO]) is None


class Conversa:
    def __init__(self) -> None:
        self.grafo = obter_grafo()
        self.config = novo_config("teste-orq-cpf")

    async def iniciar(self, mensagem: str = "relato") -> dict[str, Any]:
        r: dict[str, Any] = await self.grafo.ainvoke({"mensagem": mensagem}, self.config)
        return r

    async def responder(self, resposta: str) -> dict[str, Any]:
        r: dict[str, Any] = await self.grafo.ainvoke(Command(resume=resposta), self.config)
        return r


@pytest.fixture
def release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARIA_AMBIENTE", "release")


def _nec(i: str) -> dict[str, Any]:
    return {"id": i, "evidencia": "", "evidenciaClara": True, "urgente": False}


@pytest.mark.usefixtures("release")
async def test_pergunta_do_cpf_tem_a_etapa_e_os_tokens_da_classificacao(modelo: Modelo) -> None:
    modelo.classificacoes = [{"necessidades": [_nec(ID_PESSOA_PRESA)], **TOKENS}]
    c = Conversa()
    r = await c.iniciar()
    assert pergunta(r) == {"pergunta": TEXTO_CPF, "tipo": "texto", "etapa": "cpf"}
    # Os tokens da classificação saem com a pergunta do CPF; a rodada seguinte não gastou nada.
    assert r["tokensGastosRodada"] == 18
    r = await c.responder("66666666666")
    assert (r["flowIdEscolhido"], r["tokensGastosRodada"]) == (ID_PESSOA_PRESA, None)
    # A classificação rodou uma vez só: o CPF não reclassifica o relato.
    assert len(modelo.textos_classificados) == 1


@pytest.mark.usefixtures("release")
async def test_quem_so_quer_sair_nao_recebe_a_pergunta_do_cpf(modelo: Modelo) -> None:
    modelo.classificacoes = [{"necessidades": [_nec("tykhe:sair")], **TOKENS}]
    r = await Conversa().iniciar("tchau")
    assert pergunta(r) is None
    assert r["flowIdEscolhido"] == "tykhe:sair"


async def test_producao_nao_pergunta_o_cpf(modelo: Modelo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARIA_AMBIENTE", raising=False)
    modelo.classificacoes = [{"ids": [ID_PESSOA_PRESA], "viaIA": True, **TOKENS}]
    r = await Conversa().iniciar()
    assert pergunta(r) is None
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
