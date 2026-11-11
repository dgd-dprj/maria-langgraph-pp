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
    TEXTO_ASSUNTO_NOVO,
    TEXTO_SEM_ABERTOS,
    URGENCIA_DO_ASSUNTO,
    AssuntoGuardado,
    AssuntoPendente,
    em_ordem_de_urgencia,
    escolha_nos_abertos,
    opcoes_abertos,
    pediu_para_ver_assuntos,
    texto_abertos,
    texto_fim_do_assunto,
    texto_oferta_abertos,
    texto_retomada,
    urgencia_de,
    urgencia_do_assunto,
)
from maria.orquestrador.graph import obter_grafo
from maria.shared import pendentes_db
from maria.shared.pendentes_db import obter_pendentes_store
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


# ---- os assuntos em aberto -----------------------------------------------------------------------


def test_lista_dos_abertos_com_um_tipo_so() -> None:
    assert texto_abertos([NOVO, HORARIO]) == "Qual você quer resolver agora?\n\n• o caso novo\n• o seu horário marcado"
    assert texto_abertos([PRESA]) == "Qual você quer resolver agora?\n\nUrgente:\n• a pessoa presa"
    assert opcoes_abertos([PRESA]) == ["A pessoa presa", "Nenhum, quero um assunto novo"]


def test_lista_separa_os_urgentes_dos_menos_urgentes() -> None:
    abertos = em_ordem_de_urgencia([NOVO, PRESA, HORARIO, PLANO])
    assert [g["nome"] for g in abertos] == ["a pessoa presa", "o plano de saúde", "o caso novo", "o seu horário marcado"]
    assert texto_abertos(abertos) == (
        "Qual você quer resolver agora?\n\n"
        "Urgente:\n• a pessoa presa\n• o plano de saúde\n\n"
        "Menos urgente:\n• o caso novo\n• o seu horário marcado"
    )
    assert opcoes_abertos(abertos) == [
        "A pessoa presa",
        "O plano de saúde",
        "O caso novo",
        "O seu horário marcado",
        "Nenhum, quero um assunto novo",
    ]


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("A pessoa presa", 0),
        ("o caso novo", 1),
        ("caso novo", 1),
        ("1", 0),
        (" 2 ", 1),
        ("3", "nenhum"),
        ("4", None),
        ("Nenhum, quero um assunto novo", "nenhum"),
        ("nenhum", "nenhum"),
        ("quero falar de um assunto novo", "nenhum"),
        ("quero falar do caso novo", 1),
        ("a da cadeia", 0),
        ("hmm", None),
        ("", None),
    ],
)
def test_escolha_nos_abertos(resposta: str, esperado: int | str | None) -> None:
    assert escolha_nos_abertos(resposta, [PRESA, NOVO]) == esperado


@pytest.mark.parametrize(
    ("mensagem", "pediu"),
    [
        ("quero ver meus assuntos", True),
        ("Oi, o que ficou pendente?", True),
        ("queria continuar de onde parei", True),
        ("tenho assuntos em aberto?", True),
        ("quero saber o andamento do meu processo", False),
        ("meu irmão foi preso", False),
    ],
)
def test_pedido_de_ver_os_assuntos(mensagem: str, pediu: bool) -> None:
    assert pediu_para_ver_assuntos(mensagem) is pediu


def test_textos_da_oferta_e_da_retomada() -> None:
    assert texto_oferta_abertos(1) == "Você tem um assunto em aberto. Quer ver o assunto em aberto ou falar de um assunto novo?"
    assert texto_oferta_abertos(2) == "Você tem dois assuntos em aberto. Quer ver os assuntos em aberto ou falar de um assunto novo?"
    assert texto_retomada(PRESA) == "Você já tinha esse assunto com a gente: a pessoa presa. Vamos continuar."


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


async def _guardar(id_usuario: str, *itens: dict[str, Any]) -> None:
    await (await obter_pendentes_store()).guardar(id_usuario, f"antiga-{id_usuario}", list(itens))


ITEM_PRESA = {"nome": "a pessoa presa", "urgente": False, "urgencia": "urgente", "flowId": ID_PESSOA_PRESA}
ITEM_NOVO = {"nome": "o caso novo", "urgente": False, "urgencia": "menos_urgente", "tipoCaso": "novo-processo"}


@pytest.mark.usefixtures("release")
async def test_com_assunto_guardado_a_conversa_nao_comeca_com_pergunta(modelo: Modelo) -> None:
    await _guardar("u-sem-pergunta", ITEM_PRESA)
    modelo.classificacoes = [{"necessidades": [_nec("tykhe:novo-processo")], **TOKENS}]
    r = await Conversa().iniciar("quero entrar com um processo de pensão", id_usuario="u-sem-pergunta")
    assert pergunta(r) is None
    assert r["flowIdEscolhido"] == "tykhe:novo-processo"
    # Os guardados ficam no estado para a API retomar um do mesmo assunto.
    assert [g["nome"] for g in r["pendentesGuardados"]] == ["a pessoa presa"]


@pytest.mark.usefixtures("release")
async def test_pedido_de_ver_mostra_a_lista_e_abre_o_escolhido(modelo: Modelo) -> None:
    await _guardar("u-ver", ITEM_NOVO, ITEM_PRESA)
    modelo.classificacoes = [{"necessidades": [_nec("tykhe:outros")], **TOKENS}]
    c = Conversa()
    r = await c.iniciar("quero ver meus assuntos", id_usuario="u-ver")
    assert pergunta(r) == {
        "pergunta": "Qual você quer resolver agora?\n\nUrgente:\n• a pessoa presa\n\nMenos urgente:\n• o caso novo",
        "tipo": "opcoes",
        "opcoes": ["A pessoa presa", "O caso novo", "Nenhum, quero um assunto novo"],
        "etapa": "pendentes",
    }
    r = await c.responder("A pessoa presa")
    assert r["pendenteEscolhido"]["nome"] == "a pessoa presa"


@pytest.mark.usefixtures("release")
async def test_nenhum_pede_o_assunto_novo_e_classifica_de_novo(modelo: Modelo) -> None:
    await _guardar("u-nenhum", ITEM_NOVO)
    modelo.classificacoes = [{"necessidades": [_nec("tykhe:outros")], **TOKENS}, {"necessidades": [_nec(ID_PESSOA_PRESA)], **TOKENS}]
    c = Conversa()
    await c.iniciar("o que ficou pendente?", id_usuario="u-nenhum")
    r = await c.responder("Nenhum, quero um assunto novo")
    assert pergunta(r) == {"pergunta": TEXTO_ASSUNTO_NOVO, "tipo": "texto", "etapa": "assuntoNovo"}
    r = await c.responder("meu irmão foi preso")
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
    assert modelo.textos_classificados[-1] == "meu irmão foi preso"


@pytest.mark.usefixtures("release")
async def test_resposta_livre_na_lista_vira_o_relato_novo(modelo: Modelo) -> None:
    await _guardar("u-livre", ITEM_NOVO)
    modelo.classificacoes = [{"necessidades": [_nec("tykhe:outros")], **TOKENS}, {"necessidades": [_nec(ID_PESSOA_PRESA)], **TOKENS}]
    c = Conversa()
    await c.iniciar("quero ver meus assuntos", id_usuario="u-livre")
    r = await c.responder("na verdade meu irmão foi preso ontem")
    assert pergunta(r) is None
    assert r["flowIdEscolhido"] == ID_PESSOA_PRESA
    assert modelo.textos_classificados[-1] == "na verdade meu irmão foi preso ontem"


@pytest.mark.usefixtures("release")
async def test_pedido_de_ver_sem_assunto_em_aberto(modelo: Modelo) -> None:
    modelo.classificacoes = [{"necessidades": [_nec("tykhe:outros")], **TOKENS}]
    r = await Conversa().iniciar("quero ver meus assuntos", id_usuario="u-sem-nada")
    assert pergunta(r) == {"pergunta": TEXTO_SEM_ABERTOS, "tipo": "texto", "etapa": "assuntoNovo"}
