"""Os assuntos guardados no grafo do orquestrador (#450), com a IA simulada, e os textos da urgência.

Só no release (`MARIA_AMBIENTE=release`). Decisão da Nicole (2026-11-10): a busca dos guardados usa o `idUsuario`
da Tykhe, e não mais o CPF pedido no começo. A leitura da resposta à pergunta dos pendentes não usa IA.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.types import Command

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA
from maria.orquestrador.fila import (
    URGENCIA_DO_ASSUNTO,
    AssuntoGuardado,
    AssuntoPendente,
    em_ordem_de_urgencia,
    opcoes_pendentes,
    pendente_escolhido,
    texto_fim_do_assunto,
    texto_pendentes,
    urgencia_de,
    urgencia_do_assunto,
)
from maria.orquestrador.graph import obter_grafo
from maria.shared import pendentes_db
from tests.fluxos.conftest import novo_config, pergunta
from tests.orquestrador.conftest import Modelo

TOKENS = {"tokensEntrada": 11, "tokensSaida": 7, "tokensTotal": 18}
PRESA: AssuntoGuardado = {
    "chatIdOrigem": "a",
    "posicao": 2,
    "nome": "a pessoa presa",
    "urgente": False,
    "urgencia": "urgente",
    "flowId": ID_PESSOA_PRESA,
}
NOVO: AssuntoGuardado = {
    "chatIdOrigem": "a",
    "posicao": 3,
    "nome": "o caso novo",
    "urgente": False,
    "urgencia": "menos_urgente",
    "tipoCaso": "novo-processo",
}
HORARIO: AssuntoGuardado = {
    "chatIdOrigem": "b",
    "posicao": 2,
    "nome": "o seu horário marcado",
    "urgente": False,
    "urgencia": "menos_urgente",
    "tipoCaso": "agendamentos",
}
PLANO: AssuntoGuardado = {
    "chatIdOrigem": "b",
    "posicao": 3,
    "nome": "o plano de saúde",
    "urgente": True,
    "urgencia": "urgente",
    "flowId": ID_PROBLEMAS_PLANO_SAUDE,
}


# ---- o parâmetro de urgência ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("assunto", "esperada"),
    [
        ("tykhe:saude", "urgente"),
        (ID_PROBLEMAS_PLANO_SAUDE, "urgente"),
        (ID_VIOLENCIA_DOMESTICA, "urgente"),
        (ID_PESSOA_PRESA, "urgente"),
        ("tykhe:novo-processo", "menos_urgente"),
        ("tykhe:andamento-processo", "menos_urgente"),
        ("tykhe:agendamentos", "menos_urgente"),
        ("tykhe:ajuda-app", "menos_urgente"),
        ("tykhe:outros", "menos_urgente"),
        # Fora da tabela: menos urgente.
        ("um-fluxo-novo", "menos_urgente"),
    ],
)
def test_tabela_de_urgencia(assunto: str, esperada: str) -> None:
    assert urgencia_do_assunto(assunto, False) == esperada
    # O sinal de risco do relato sobe qualquer assunto para urgente.
    assert urgencia_do_assunto(assunto, True) == "urgente"


def test_os_urgentes_da_tabela_sao_os_que_a_ordem_poe_na_frente() -> None:
    from maria.orquestrador.fila import PRIORIDADE

    assert {i for i, u in URGENCIA_DO_ASSUNTO.items() if u == "urgente"} == set(PRIORIDADE)


def test_guardado_sem_o_campo_usa_a_tabela() -> None:
    """Pendentes guardados no checkpoint antes de 2026-11-10 não têm `urgencia`."""
    antigo: dict[str, Any] = {"nome": "a pessoa presa", "urgente": False, "flowId": ID_PESSOA_PRESA}
    assert urgencia_de(antigo) == "urgente"
    assert urgencia_de({"nome": "o caso novo", "urgente": False, "tipoCaso": "novo-processo"}) == "menos_urgente"
    assert urgencia_de({"nome": "o caso novo", "urgente": True, "tipoCaso": "novo-processo"}) == "urgente"


def test_store_guarda_a_urgencia_mesmo_sem_o_campo() -> None:
    assert pendentes_db._urgencia({"urgente": True}) == "urgente"
    assert pendentes_db._urgencia({"urgente": False, "urgencia": "urgente"}) == "urgente"
    assert pendentes_db._urgencia({"urgente": False}) == "menos_urgente"


# ---- a pergunta dos guardados --------------------------------------------------------------------


def test_texto_com_um_pendente() -> None:
    assert texto_pendentes([NOVO]) == ("Você tem um assunto guardado: o caso novo. Quer falar dele agora ou do que você acabou de contar?")
    assert texto_pendentes([PRESA]) == (
        "Você tem um assunto urgente guardado: a pessoa presa. Quer falar dele agora ou do que você acabou de contar?"
    )
    assert opcoes_pendentes([PRESA]) == ["O que acabei de contar", "A pessoa presa"]


def test_texto_com_varios_da_mesma_urgencia() -> None:
    assert texto_pendentes([NOVO, HORARIO]) == (
        "Você tem assuntos guardados: o caso novo e o seu horário marcado. Quer falar de um deles agora ou do que você acabou de contar?"
    )
    assert texto_pendentes([PRESA, PLANO]).startswith("Você tem assuntos urgentes guardados: a pessoa presa e o plano de saúde.")


def test_texto_separa_os_urgentes_dos_menos_urgentes() -> None:
    guardados = em_ordem_de_urgencia([NOVO, PRESA, HORARIO, PLANO])
    assert [g["nome"] for g in guardados] == ["a pessoa presa", "o plano de saúde", "o caso novo", "o seu horário marcado"]
    assert texto_pendentes(guardados) == (
        "Você tem assuntos guardados.\n\n"
        "Urgente:\n• a pessoa presa\n• o plano de saúde\n\n"
        "Menos urgente:\n• o caso novo\n• o seu horário marcado\n\n"
        "Quer falar de um deles agora ou do que você acabou de contar?"
    )
    assert opcoes_pendentes(guardados) == [
        "O que acabei de contar",
        "A pessoa presa",
        "O plano de saúde",
        "O caso novo",
        "O seu horário marcado",
    ]


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("O que acabei de contar", None),
        ("1", None),
        ("A pessoa presa", 0),
        ("o caso novo", 1),
        ("caso novo", 1),
        ("2", 0),
        (" 3 ", 1),
        ("4", None),
        ("quero falar do caso novo", 1),
        ("a da cadeia", 0),
        ("o que eu acabei de contar", None),
        ("o de hoje", None),
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


# ---- o fim de cada assunto -----------------------------------------------------------------------


def _pendente(nome: str, urgencia: str) -> AssuntoPendente:
    return {"nome": nome, "urgente": False, "urgencia": urgencia, "tipoCaso": "outros"}  # type: ignore[typeddict-item]


@pytest.mark.parametrize(
    ("pendentes", "guardados", "esperado"),
    [
        ([("a pessoa presa", "urgente")], True, "Ainda falta um assunto urgente: a pessoa presa. Vamos falar dele agora."),
        (
            [("a pessoa presa", "urgente"), ("o plano de saúde", "urgente")],
            False,
            "Ainda faltam assuntos urgentes: a pessoa presa e o plano de saúde. Vamos falar deles agora.",
        ),
        (
            [("o caso novo", "menos_urgente")],
            True,
            "Ficou para depois: o caso novo. Vou guardar esse assunto por até 30 dias para a gente continuar depois.",
        ),
        (
            [("o caso novo", "menos_urgente"), ("o seu horário marcado", "menos_urgente")],
            True,
            "Ficou para depois: o caso novo e o seu horário marcado. Vou guardar esses assuntos por até 30 dias para a gente"
            " continuar depois.",
        ),
        ([("o caso novo", "menos_urgente")], False, "Ficou para depois: o caso novo."),
        (
            [("a pessoa presa", "urgente"), ("o caso novo", "menos_urgente")],
            False,
            "Ainda falta um assunto urgente: a pessoa presa. Vamos falar dele agora.\n\nTambém ficou para depois: o caso novo.",
        ),
    ],
)
def test_texto_fim_do_assunto(pendentes: list[tuple[str, str]], guardados: bool, esperado: str) -> None:
    assert texto_fim_do_assunto([_pendente(n, u) for n, u in pendentes], guardados) == esperado


# ---- o grafo -------------------------------------------------------------------------------------


class Conversa:
    def __init__(self) -> None:
        self.grafo = obter_grafo()
        self.config = novo_config("teste-orq-usuario")

    async def iniciar(self, mensagem: str = "relato", id_usuario: str | None = None) -> dict[str, Any]:
        entrada: dict[str, Any] = {"mensagem": mensagem}
        if id_usuario is not None:
            entrada["idUsuario"] = id_usuario
        r: dict[str, Any] = await self.grafo.ainvoke(entrada, self.config)
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
async def test_sem_cpf_no_comeco_o_fluxo_abre_direto(modelo: Modelo) -> None:
    modelo.classificacoes = [{"necessidades": [_nec(ID_PESSOA_PRESA)], **TOKENS}]
    r = await Conversa().iniciar(id_usuario="u-1")
    assert pergunta(r) is None
    assert (r["flowIdEscolhido"], r["pendentesBuscados"]) == (ID_PESSOA_PRESA, True)


@pytest.mark.usefixtures("release")
async def test_sem_id_usuario_nem_busca_os_guardados(modelo: Modelo) -> None:
    modelo.classificacoes = [{"necessidades": [_nec(ID_PESSOA_PRESA)], **TOKENS}]
    r = await Conversa().iniciar()
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
    assert "pendentesBuscados" not in r


@pytest.mark.usefixtures("release")
async def test_quem_so_quer_sair_nao_recebe_a_pergunta_dos_guardados(modelo: Modelo) -> None:
    modelo.classificacoes = [{"necessidades": [_nec("tykhe:sair")], **TOKENS}]
    r = await Conversa().iniciar("tchau", id_usuario="u-1")
    assert pergunta(r) is None
    assert r["flowIdEscolhido"] == "tykhe:sair"


async def test_producao_nao_busca_os_guardados(modelo: Modelo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARIA_AMBIENTE", raising=False)
    modelo.classificacoes = [{"ids": [ID_PESSOA_PRESA], "viaIA": True, **TOKENS}]
    r = await Conversa().iniciar(id_usuario="u-1")
    assert pergunta(r) is None
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
    assert "pendentesBuscados" not in r
