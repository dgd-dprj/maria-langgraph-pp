"""Os assuntos pendentes por assistido (#450, multi-fluxo, só no release), pela API.

Decisão da Nicole (2026-11-10): a pessoa é identificada pelo `idUsuario` que a Tykhe manda na 1ª chamada, e cada
assunto guardado pelo `chatId` da conversa e pelo `chatId` do assunto (`<chatId>-assunto-N`). A Maria não pergunta
mais o CPF no começo; os fluxos pedem o CPF quando precisam. Cada assunto tem uma urgência (`urgente` ou
`menos_urgente`): uma tabela por assunto, com o sinal de risco do relato por cima. A urgência vai para a Tykhe em
`assuntosPendentes[].urgencia` e separa as mensagens ao assistido.

A classificação é simulada (`MOCK_NECESSIDADES`); os fluxos e o Verde simulado são os de verdade.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, fluxos_por_id
from maria.orquestrador.graph import obter_grafo
from maria.shared import pendentes_db
from maria.shared.pendentes_db import obter_pendentes_store

ORQ = "/atendimentos/orquestrador"
PROXIMO = "/atendimentos/proximo-assunto"
RESPOSTAS = "/atendimentos/respostas"
CPF = "11111111111"
ID_USUARIO = "tykhe-usuario-77"
DADOS_NO_RIO = {"endereco": {"cep": "20000000"}}
PLANO = {"id": ID_PROBLEMAS_PLANO_SAUDE, "evidencia": "o plano negou a cirurgia", "urgente": True}
PP = {"id": ID_PESSOA_PRESA, "evidencia": "meu irmão está preso"}
NOVO_PROCESSO = {"id": "tykhe:novo-processo", "evidencia": "quero entrar com um processo de pensão"}
HORARIO = {"id": "tykhe:agendamentos", "evidencia": "quero remarcar o meu horário"}

_ids = count(1)


def _chat() -> str:
    return f"teste-usuario-pendentes-{next(_ids)}"


@pytest.fixture
def release(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.delenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", raising=False)
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    return monkeypatch


async def _orq(cliente: httpx.AsyncClient, auth: dict[str, str], corpo: dict[str, Any]) -> dict[str, Any]:
    r = await cliente.post(ORQ, json=corpo, headers=auth)
    assert r.status_code == 200
    resposta: dict[str, Any] = r.json()
    return resposta


async def _comecar(
    cliente: httpx.AsyncClient, auth: dict[str, str], chat: str, relato: str = "relato", id_usuario: Any = ID_USUARIO
) -> dict[str, Any]:
    corpo: dict[str, Any] = {"chatId": chat, "mensagem": relato, "dadosConhecidos": DADOS_NO_RIO}
    if id_usuario is not None:
        corpo["idUsuario"] = id_usuario
    return await _orq(cliente, auth, corpo)


async def _estado_orquestrador(chat: str) -> dict[str, Any]:
    return dict((await obter_grafo().aget_state({"configurable": {"thread_id": f"orquestrador:{chat}"}})).values)


async def _estado_fluxo(fluxo: str, chat: str) -> dict[str, Any]:
    return dict((await fluxos_por_id[fluxo].obter_grafo().aget_state({"configurable": {"thread_id": chat}})).values)


async def _pessoa_presa_ate_o_fim(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str, primeira: dict[str, Any]) -> dict[str, Any]:
    """Responde o caminho da pessoa presa até o fim e devolve a última resposta."""
    corpo = primeira
    for _ in range(16):
        if corpo["status"] != "em_andamento":
            break
        pergunta = corpo["resposta"]
        if "qual o número" in pergunta.lower():
            resposta = "0000088-95.2026.8.19.0010"
        elif "RG" in pergunta or "CPF" in pergunta:
            resposta = CPF
        elif corpo["tipoResposta"] == "sim_nao":
            resposta = "true"
        else:
            resposta = "não sei"
        corpo = (await cliente.post(RESPOSTAS, json={"chatId": chat, "resposta": resposta}, headers=auth)).json()
    assert corpo["status"] != "em_andamento"
    return corpo


async def _plano_ate_o_fim(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str) -> dict[str, Any]:
    """O fluxo do plano até o fim: "para você?", o CPF que o fluxo pede, a confirmação e 3 respostas sem a foto."""
    corpo: dict[str, Any] = {"status": "em_andamento", "resposta": ""}
    for _ in range(10):
        pergunta = corpo["resposta"]
        resposta = CPF if "CPF" in pergunta else "true" if corpo.get("tipoResposta") in (None, "sim_nao") else "mandei"
        corpo = (await cliente.post(RESPOSTAS, json={"chatId": chat, "resposta": resposta}, headers=auth)).json()
        if corpo["status"] != "em_andamento":
            break
    assert corpo["status"] == "handoff_humano"
    return corpo


async def _conversa_com_pendente(cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch, *necessidades: Any) -> str:
    """Uma conversa com dois assuntos ou mais e o idUsuario da Tykhe: os outros ficam guardados. Devolve o chatId."""
    release.setenv("MOCK_NECESSIDADES", json.dumps(list(necessidades)))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat)
    assert corpo["tipoResposta"] == "sim_nao"  # a ordem dos assuntos
    await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    return chat


# ---- 1. a identificação pelo idUsuario, sem o CPF no começo ----------------------------------------


async def test_nao_pergunta_o_cpf_no_comeco_e_guarda_pelo_id_usuario(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    # A 1ª resposta já é a ordem dos assuntos: nada de CPF antes.
    corpo = await _comecar(cliente, auth, chat, "meu irmão está preso e o plano negou a cirurgia")
    assert corpo["resposta"].startswith("Entendi. Você falou de duas coisas: o plano de saúde e a pessoa presa.")
    estado = await _estado_orquestrador(chat)
    assert estado["idUsuario"] == ID_USUARIO
    assert not {"idPessoa", "identificacaoFeita", "cpfDigitado"} & set(estado)

    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    assert corpo["flowId"] == ID_PROBLEMAS_PLANO_SAUDE
    # A Tykhe recebe a urgência de cada pendente, logo depois do sinal de risco.
    assert corpo["assuntosPendentes"] == [
        {
            "nome": "a pessoa presa",
            "urgente": False,
            "urgencia": "urgente",
            "flowId": ID_PESSOA_PRESA,
            "dadosConhecidos": {"parentesco": "Irmão(a)"},
        }
    ]
    assert list(corpo["assuntosPendentes"][0]) == ["nome", "urgente", "urgencia", "flowId", "dadosConhecidos"]
    # O fluxo do plano pede o CPF ele mesmo, como antes da #450.
    assert "cpf" not in await _estado_fluxo(ID_PROBLEMAS_PLANO_SAUDE, chat)

    ativos = await (await obter_pendentes_store()).listar_ativos(ID_USUARIO)
    assert [(p["chatIdAssunto"], p["chatIdOrigem"], p["nome"], p["urgencia"]) for p in ativos] == [
        (f"{chat}-assunto-2", chat, "a pessoa presa", "urgente")
    ]
    # LGPD: o idUsuario não vai para o log.
    assert ID_USUARIO not in capsys.readouterr().out


async def test_id_usuario_numerico_vale_como_texto(cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    await _comecar(cliente, auth, chat, id_usuario=12345)
    assert (await _estado_orquestrador(chat))["idUsuario"] == "12345"


@pytest.mark.parametrize("id_usuario", [None, "", "   ", "x" * 201])
async def test_sem_id_usuario_nao_guarda_nem_pergunta(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch, id_usuario: Any
) -> None:
    chat = await _conversa_com_pendente(cliente, auth, release, PLANO, PP)
    assert await (await obter_pendentes_store()).listar_ativos(ID_USUARIO)
    # Outra conversa, sem um idUsuario que valha: segue direto, sem a pergunta dos guardados.
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP, NOVO_PROCESSO]))
    nova = _chat()
    corpo = await _comecar(cliente, auth, nova, id_usuario=id_usuario)
    assert corpo["resposta"].startswith("Entendi. Você falou de duas coisas")
    assert (await _estado_orquestrador(nova)).get("idUsuario") is None
    await _orq(cliente, auth, {"chatId": nova, "resposta": "true"})
    assert [p["chatIdOrigem"] for p in await (await obter_pendentes_store()).listar_ativos(ID_USUARIO)] == [chat]


async def test_id_usuario_da_resposta_nao_troca_o_da_conversa(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    await _comecar(cliente, auth, chat)
    await _orq(cliente, auth, {"chatId": chat, "resposta": "true", "idUsuario": "outra-pessoa"})
    assert (await _estado_orquestrador(chat))["idUsuario"] == ID_USUARIO
    assert await (await obter_pendentes_store()).listar_ativos("outra-pessoa") == []


# ---- 2. os pendentes guardados ---------------------------------------------------------------------


async def test_pendentes_guardados_pelo_id_do_assunto_sem_o_relato(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    chat = await _conversa_com_pendente(cliente, auth, release, PLANO, PP, NOVO_PROCESSO)
    ativos = await (await obter_pendentes_store()).listar_ativos(ID_USUARIO)
    assert [(p["chatIdAssunto"], p["posicao"], p["nome"], p["urgencia"], p.get("flowId"), p.get("tipoCaso")) for p in ativos] == [
        (f"{chat}-assunto-2", 2, "a pessoa presa", "urgente", ID_PESSOA_PRESA, None),
        (f"{chat}-assunto-3", 3, "o caso novo", "menos_urgente", None, "novo-processo"),
    ]
    # Só o assunto, a urgência, a situação e as datas: nunca o relato nem os dadosConhecidos.
    assert set(ativos[0]) == {
        "chatIdAssunto",
        "chatIdOrigem",
        "posicao",
        "nome",
        "urgente",
        "urgencia",
        "situacao",
        "criadoEm",
        "venceEm",
        "prorrogado",
        "flowId",
    }


async def test_rota_do_proximo_assunto_marca_a_situacao_pelo_id_do_assunto(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    chat = await _conversa_com_pendente(cliente, auth, release, PLANO, PP, NOVO_PROCESSO)
    store = await obter_pendentes_store()
    await _plano_ate_o_fim(cliente, auth, chat)

    corpo = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert corpo["chatId"] == f"{chat}-assunto-2"
    item = await store.buscar(f"{chat}-assunto-2")
    assert item is not None and item["situacao"] == "em_andamento"
    await _pessoa_presa_ate_o_fim(cliente, auth, f"{chat}-assunto-2", corpo)
    item = await store.buscar(f"{chat}-assunto-2")
    assert item is not None and item["situacao"] == "resolvido"

    corpo = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert (corpo["chatId"], corpo["tipoCaso"]) == (f"{chat}-assunto-3", "novo-processo")
    item = await store.buscar(f"{chat}-assunto-3")
    assert item is not None and item["situacao"] == "resolvido"
    assert await store.listar_ativos(ID_USUARIO) == []


# ---- 3. a urgência no fim de cada assunto ----------------------------------------------------------


async def test_fim_do_assunto_oferece_o_urgente_e_guarda_o_menos_urgente(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    # O caso novo é menos urgente pela tabela, mas o relato tem sinal de risco: sobe para urgente.
    novo_com_risco = {**NOVO_PROCESSO, "urgente": True}
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP, novo_com_risco, HORARIO]))
    chat = _chat()
    await _comecar(cliente, auth, chat)
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert [(p["nome"], p["urgente"], p["urgencia"]) for p in corpo["assuntosPendentes"]] == [
        ("o caso novo", True, "urgente"),
        ("o seu horário marcado", False, "menos_urgente"),
    ]
    fim = await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    assert fim["status"] == "concluido"
    assert fim["resposta"].endswith(
        "\n\nAinda falta um assunto urgente: o caso novo. Vamos falar dele agora."
        "\n\nTambém ficou para depois: o seu horário marcado. Vou guardar esse assunto por até 30 dias para a gente continuar"
        " depois."
    )


async def test_fim_do_assunto_sem_id_usuario_nao_promete_guardar(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP, HORARIO]))
    chat = _chat()
    await _comecar(cliente, auth, chat, id_usuario=None)
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    fim = await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    assert fim["status"] == "concluido"
    assert fim["resposta"].endswith("\n\nFicou para depois: o seu horário marcado.")


# ---- 4. a pergunta dos pendentes quando a pessoa volta ---------------------------------------------


async def test_conversa_nova_escolhe_o_pendente_urgente_da_maria(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, PP)
    store = await obter_pendentes_store()

    release.setenv("MOCK_NECESSIDADES", json.dumps([NOVO_PROCESSO]))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat, "quero entrar com um processo de pensão")
    assert corpo == {
        "resposta": "Você tem um assunto urgente guardado: a pessoa presa. Quer falar dele agora ou do que você acabou de contar?",
        "tipoResposta": "opcoes",
        "opcoes": ["O que acabei de contar", "A pessoa presa"],
        "status": "em_andamento",
        "_links": {"self": {"href": f"/atendimentos/{chat}"}, "responder": {"href": ORQ, "method": "POST"}},
    }
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "A pessoa presa"})
    # O assunto guardado abre nesta conversa; o que ela acabou de contar fica pendente.
    assert (corpo["flowId"], corpo["status"]) == (ID_PESSOA_PRESA, "em_andamento")
    assert corpo["resposta"].startswith("Agora vamos falar da pessoa presa.\n\n")
    assert corpo["assuntosPendentes"] == [
        {"nome": "o caso novo", "urgente": False, "urgencia": "menos_urgente", "tipoCaso": "novo-processo"}
    ]
    item = await store.buscar(f"{antiga}-assunto-2")
    assert item is not None and item["situacao"] == "em_andamento"
    assert [(p["chatIdAssunto"], p["nome"]) for p in await store.listar_ativos(ID_USUARIO)] == [(f"{chat}-assunto-2", "o caso novo")]

    # Fim do fluxo: o assunto guardado fica resolvido.
    await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    item = await store.buscar(f"{antiga}-assunto-2")
    assert item is not None and item["situacao"] == "resolvido"


async def test_pergunta_separa_os_urgentes_dos_menos_urgentes(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    # Guardados: a pessoa presa (urgente) e o caso novo (menos urgente).
    await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO, PP)
    release.setenv("MOCK_NECESSIDADES", json.dumps([HORARIO]))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat, "quero remarcar o meu horário")
    assert corpo["resposta"] == (
        "Você tem assuntos guardados.\n\nUrgente:\n• a pessoa presa\n\nMenos urgente:\n• o caso novo\n\n"
        "Quer falar de um deles agora ou do que você acabou de contar?"
    )
    # Nas opções, os urgentes vêm primeiro; o número segue a ordem das opções.
    assert corpo["opcoes"] == ["O que acabei de contar", "A pessoa presa", "O caso novo"]
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "3"})
    assert (corpo["status"], corpo["tipoCaso"]) == ("redirecionado", "novo-processo")


async def test_conversa_nova_escolhe_o_que_acabou_de_contar(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat)
    assert corpo["resposta"].startswith("Você tem um assunto guardado: o caso novo.")
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "O que acabei de contar"})
    assert corpo["resposta"].startswith("Entendi. Você falou de duas coisas")
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    assert corpo["flowId"] == ID_PROBLEMAS_PLANO_SAUDE
    ativos = await (await obter_pendentes_store()).listar_ativos(ID_USUARIO)
    assert [(p["chatIdOrigem"], p["nome"]) for p in ativos] == [(antiga, "o caso novo"), (chat, "a pessoa presa")]


async def test_resposta_nao_entendida_segue_com_o_que_acabou_de_contar(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    await _comecar(cliente, auth, chat, "meu irmão está preso")
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "hmm"})
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert "assuntosPendentes" not in corpo


async def test_pendente_vencido_e_apagado_e_nao_e_perguntado(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    depois = datetime.now(UTC) + timedelta(days=31)
    release.setattr(pendentes_db, "agora", lambda: depois)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    corpo = await _comecar(cliente, auth, _chat(), "meu irmão está preso")
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert await (await obter_pendentes_store()).buscar(f"{antiga}-assunto-2") is None


# ---- produção --------------------------------------------------------------------------------------


async def test_producao_ignora_o_id_usuario_e_nao_usa_os_pendentes(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MARIA_AMBIENTE", raising=False)
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    chat = _chat()
    corpo = await _orq(cliente, auth, {"chatId": chat, "mensagem": "meu irmão está preso", "idUsuario": ID_USUARIO})
    assert corpo["flowId"] == ID_PESSOA_PRESA
    estado = await _estado_orquestrador(chat)
    assert not {"idUsuario", "pendentesBuscados", "pendentesGuardados"} & set(estado)
    # A store dos pendentes nem é criada.
    assert pendentes_db._tarefa is None
