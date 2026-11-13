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
    TEXTO_ENCERRAR,
    TEXTO_FALAR_DE_NOVO,
    TEXTO_SEM_ABERTOS,
    URGENCIA_DO_ASSUNTO,
    AssuntoGuardado,
    AssuntoPendente,
    codigo_do_assunto,
    desfecho_do_assunto,
    em_ordem_de_urgencia,
    escolha_nos_abertos,
    opcoes_abertos,
    opcoes_do_fim,
    pediu_para_ver_assuntos,
    texto_abertos,
    texto_fim_da_conversa,
    texto_fim_do_assunto,
    texto_pendentes_no_atendimento_humano,
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


# Decisão da Nicole (2026-11-13): listas numeradas, com a legenda do número, e os botões com o mesmo número.


def test_lista_dos_abertos_com_um_tipo_so() -> None:
    assert texto_abertos([NOVO, HORARIO]) == (
        "Qual você quer resolver agora?\n\n"
        "Menos urgente:\n1. O caso novo\n2. O seu horário marcado\n\n"
        "Outras opções:\n3. Nenhum, quero um assunto novo\n\n"
        "Responda com o número da opção."
    )
    assert texto_abertos([PRESA]) == (
        "Qual você quer resolver agora?\n\n"
        "Urgente:\n1. A pessoa presa\n\n"
        "Outras opções:\n2. Nenhum, quero um assunto novo\n\n"
        "Responda com o número da opção."
    )
    assert opcoes_abertos([PRESA]) == ["1. A pessoa presa", "2. Nenhum, quero um assunto novo"]


def test_lista_separa_os_urgentes_dos_menos_urgentes() -> None:
    abertos = em_ordem_de_urgencia([NOVO, PRESA, HORARIO, PLANO])
    assert [g["nome"] for g in abertos] == ["a pessoa presa", "o plano de saúde", "o caso novo", "o seu horário marcado"]
    assert texto_abertos(abertos) == (
        "Qual você quer resolver agora?\n\n"
        "Urgente:\n1. A pessoa presa\n2. O plano de saúde\n\n"
        "Menos urgente:\n3. O caso novo\n4. O seu horário marcado\n\n"
        "Outras opções:\n5. Nenhum, quero um assunto novo\n\n"
        "Responda com o número da opção."
    )
    assert opcoes_abertos(abertos) == [
        "1. A pessoa presa",
        "2. O plano de saúde",
        "3. O caso novo",
        "4. O seu horário marcado",
        "5. Nenhum, quero um assunto novo",
    ]


def test_lista_do_fim_da_conversa_tem_o_encerrar() -> None:
    """Quem não quer continuar com os assuntos em aberto pode encerrar (decisão da Nicole, 2026-11-13)."""
    assert texto_abertos([PRESA, NOVO], com_encerrar=True).endswith(
        "Outras opções:\n3. Nenhum, quero um assunto novo\n4. Encerrar a conversa\n\nResponda com o número da opção."
    )
    assert opcoes_abertos([PRESA, NOVO], com_encerrar=True)[-2:] == ["3. Nenhum, quero um assunto novo", "4. Encerrar a conversa"]


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        ("A pessoa presa", 0),
        ("o caso novo", 1),
        ("caso novo", 1),
        ("1", 0),
        (" 2 ", 1),
        ("3", "nenhum"),
        ("4", "encerrar"),
        ("5", None),
        # O texto do botão numerado.
        ("1. A pessoa presa", 0),
        ("2) o caso novo", 1),
        ("3. Nenhum, quero um assunto novo", "nenhum"),
        ("4. Encerrar a conversa", "encerrar"),
        ("Encerrar a conversa", "encerrar"),
        ("quero encerrar", "encerrar"),
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


def test_texto_da_retomada() -> None:
    assert texto_retomada(PRESA) == "Você já tinha esse assunto com a gente: a pessoa presa. Vamos continuar."


# ---- o fim da conversa: resumo, o que está em aberto e os botões ---------------------------------


def test_codigo_do_assunto_e_curto_e_fixo() -> None:
    codigo = codigo_do_assunto("chat-1-assunto-2")
    assert len(codigo) == 6
    assert codigo.isalnum()
    assert codigo.isupper() or any(c.isdigit() for c in codigo)
    assert codigo == codigo_do_assunto("chat-1-assunto-2")
    assert codigo != codigo_do_assunto("chat-1-assunto-3")
    # O código não mostra o id do assunto.
    assert "chat" not in codigo.lower()


@pytest.mark.parametrize(
    ("assunto", "status", "esperado"),
    [
        (ID_PESSOA_PRESA, "concluido", "dados confirmados e encaminhados"),
        (ID_PROBLEMAS_PLANO_SAUDE, "concluido", "pedido enviado à Defensoria"),
        ("outro-fluxo", "concluido", "resolvido aqui"),
        (ID_PESSOA_PRESA, "handoff_humano", "encaminhado para a equipe da Defensoria"),
        (ID_PESSOA_PRESA, "expirado", "encerrado por falta de resposta"),
        (ID_PESSOA_PRESA, None, "em andamento"),
        ("tykhe:agendamentos", None, "encaminhado para o atendimento certo"),
        (ID_PESSOA_PRESA, "redirecionado", "encaminhado para o atendimento certo"),
        # Violência doméstica: desfecho neutro, que não conta o que foi feito a quem pegar o celular.
        (ID_VIOLENCIA_DOMESTICA, "concluido", "encaminhada"),
        (ID_VIOLENCIA_DOMESTICA, "handoff_humano", "encaminhada"),
        (ID_VIOLENCIA_DOMESTICA, "expirado", "encerrada"),
        (ID_VIOLENCIA_DOMESTICA, None, "em andamento"),
    ],
)
def test_desfecho_do_assunto(assunto: str, status: str | None, esperado: str) -> None:
    assert desfecho_do_assunto(assunto, status) == esperado


def test_fim_da_conversa_com_assuntos_em_aberto() -> None:
    resumo = [
        {"nome": "a pessoa presa", "desfecho": "dados confirmados e encaminhados", "codigo": "K7M2QX"},
        {"nome": "a situação que você contou", "desfecho": "encaminhada", "codigo": "P3R8TZ"},
    ]
    abertos = [
        {**PLANO, "fase": "nao_iniciado", "venceEm": "2026-12-11"},
        {**NOVO, "fase": "nao_iniciado"},
    ]
    assert texto_fim_da_conversa(resumo, abertos, guardados=True) == (  # type: ignore[arg-type]
        "Resumo da nossa conversa:\n"
        "• A pessoa presa: dados confirmados e encaminhados (código K7M2QX)\n"
        "• A situação que você contou: encaminhada (código P3R8TZ)\n\n"
        "Quer continuar com algum dos assuntos em aberto ou encerrar a conversa?\n\n"
        "Ainda em aberto:\n\n"
        "Urgente:\n1. O plano de saúde (guardado até 11/12, ainda não começou)\n\n"
        "Menos urgente:\n2. O caso novo (ainda não começou)\n\n"
        "Outras opções:\n3. Falar de um assunto novo\n4. Encerrar a conversa\n\n"
        "Responda com o número da opção. Os assuntos em aberto ficam guardados por até 30 dias."
    )
    assert opcoes_do_fim(abertos) == ["1. O plano de saúde", "2. O caso novo", f"3. {TEXTO_FALAR_DE_NOVO}", f"4. {TEXTO_ENCERRAR}"]


def test_fim_da_conversa_com_um_assunto_em_aberto() -> None:
    resumo = [{"nome": "a pessoa presa", "desfecho": "dados confirmados e encaminhados", "codigo": "K7M2QX"}]
    texto = texto_fim_da_conversa(resumo, [{**NOVO, "fase": "nao_iniciado"}], guardados=False)  # type: ignore[arg-type]
    assert "Quer continuar com o assunto em aberto ou encerrar a conversa?" in texto
    assert texto.endswith("Outras opções:\n2. Falar de um assunto novo\n3. Encerrar a conversa\n\nResponda com o número da opção.")


def test_fim_da_conversa_sem_nada_em_aberto() -> None:
    resumo = [{"nome": "o plano de saúde", "desfecho": "pedido enviado à Defensoria", "codigo": "A1B2C3"}]
    assert texto_fim_da_conversa(resumo, [], guardados=False) == (  # type: ignore[arg-type]
        "Resumo da nossa conversa:\n"
        "• O plano de saúde: pedido enviado à Defensoria (código A1B2C3)\n\n"
        "Quer falar de um assunto novo ou encerrar a conversa?\n"
        "1. Falar de um assunto novo\n2. Encerrar a conversa\n\n"
        "Responda com o número da opção."
    )
    assert opcoes_do_fim([]) == [f"1. {TEXTO_FALAR_DE_NOVO}", f"2. {TEXTO_ENCERRAR}"]


def test_aviso_curto_no_atendimento_humano() -> None:
    """Decisão da Nicole (2026-11-13): no atendimento humano, só o aviso do que ficou para depois."""
    um = [_pendente("a pessoa presa", "urgente")]
    assert texto_pendentes_no_atendimento_humano(um) == "Também ficou para depois: a pessoa presa."
    dois = [_pendente("a pessoa presa", "urgente"), _pendente("o caso novo", "menos_urgente")]
    assert texto_pendentes_no_atendimento_humano(dois) == "Também ficou para depois: a pessoa presa e o caso novo."


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
        "pergunta": (
            "Qual você quer resolver agora?\n\n"
            "Urgente:\n1. A pessoa presa\n\n"
            "Menos urgente:\n2. O caso novo\n\n"
            "Outras opções:\n3. Nenhum, quero um assunto novo\n\n"
            "Responda com o número da opção."
        ),
        "tipo": "opcoes",
        "opcoes": ["1. A pessoa presa", "2. O caso novo", "3. Nenhum, quero um assunto novo"],
        "etapa": "pendentes",
    }
    r = await c.responder("1. A pessoa presa")
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
