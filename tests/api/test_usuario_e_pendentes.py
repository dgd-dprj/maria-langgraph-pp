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

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA, fluxos_por_id
from maria.orquestrador.fila import codigo_do_assunto
from maria.orquestrador.graph import obter_grafo
from maria.shared import pendentes_db
from maria.shared.pendentes_db import obter_pendentes_store

ORQ = "/atendimentos/orquestrador"
PROXIMO = "/atendimentos/proximo-assunto"
ABERTOS = "/atendimentos/assuntos-em-aberto"
RESPOSTAS = "/atendimentos/respostas"
CPF = "11111111111"
ID_USUARIO = "tykhe-usuario-77"
DADOS_NO_RIO = {"endereco": {"cep": "20000000"}}
PLANO = {"id": ID_PROBLEMAS_PLANO_SAUDE, "evidencia": "o plano negou a cirurgia", "urgente": True}
PP = {"id": ID_PESSOA_PRESA, "evidencia": "meu irmão está preso"}
# A ordem (decisão da Nicole, 2026-11-13): violência doméstica, pessoa presa, saúde. Para a pessoa presa ficar pendente,
# o 1º assunto é a violência.
VD = {"id": ID_VIOLENCIA_DOMESTICA, "evidencia": "meu ex me ameaçou", "urgente": True}
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
    assert corpo["resposta"].startswith("Entendi. Você falou de duas coisas: a pessoa presa e o plano de saúde.")
    estado = await _estado_orquestrador(chat)
    assert estado["idUsuario"] == ID_USUARIO
    assert not {"idPessoa", "identificacaoFeita", "cpfDigitado"} & set(estado)

    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    assert corpo["flowId"] == ID_PESSOA_PRESA
    # A Tykhe recebe a urgência de cada pendente, logo depois do sinal de risco.
    assert corpo["assuntosPendentes"] == [
        {"nome": "o plano de saúde", "urgente": True, "urgencia": "urgente", "flowId": ID_PROBLEMAS_PLANO_SAUDE}
    ]
    assert list(corpo["assuntosPendentes"][0]) == ["nome", "urgente", "urgencia", "flowId"]
    # O fluxo pede o CPF ele mesmo, como antes da #450.
    assert "cpf" not in await _estado_fluxo(ID_PESSOA_PRESA, chat)

    ativos = await (await obter_pendentes_store()).listar_ativos(ID_USUARIO)
    assert [(p["chatIdAssunto"], p["chatIdOrigem"], p["nome"], p["urgencia"]) for p in ativos] == [
        (f"{chat}-assunto-2", chat, "o plano de saúde", "urgente")
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
    chat = await _conversa_com_pendente(cliente, auth, release, VD, PP)
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
    chat = await _conversa_com_pendente(cliente, auth, release, VD, PP, NOVO_PROCESSO)
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
    # A ordem: a pessoa presa, o plano (assunto 2) e o caso novo (assunto 3).
    chat = await _conversa_com_pendente(cliente, auth, release, PLANO, PP, NOVO_PROCESSO)
    store = await obter_pendentes_store()
    atual = (await cliente.get(f"/atendimentos/{chat}", headers=auth)).json()
    await _pessoa_presa_ate_o_fim(cliente, auth, chat, atual)

    corpo = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert (corpo["chatId"], corpo["flowId"]) == (f"{chat}-assunto-2", ID_PROBLEMAS_PLANO_SAUDE)
    item = await store.buscar(f"{chat}-assunto-2")
    assert item is not None and item["situacao"] == "em_andamento"
    await _plano_ate_o_fim(cliente, auth, f"{chat}-assunto-2")
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
    # Com um urgente na vez, a oferta dos assuntos em aberto fica para o fim dele.
    assert "assuntosEmAberto" not in fim and "opcoesDoFim" not in fim
    assert fim["resposta"].endswith(
        "\n\nAinda falta um assunto urgente: o caso novo. Vamos falar dele agora."
        "\n\nTambém ficou para depois: o seu horário marcado. Vou guardar esse assunto por até 30 dias para a gente continuar"
        " depois."
    )


async def test_fim_do_assunto_sem_id_usuario_nao_promete_guardar_e_oferece_os_abertos(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP, HORARIO]))
    chat = _chat()
    await _comecar(cliente, auth, chat, id_usuario=None)
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    fim = await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    assert fim["status"] == "concluido"
    # Sem idUsuario: sem a data e sem o aviso dos 30 dias.
    assert fim["resposta"].endswith(
        "\n\nResumo da nossa conversa:"
        f"\n• A pessoa presa: dados confirmados e encaminhados (código {codigo_do_assunto(chat)})"
        "\n\nQuer continuar com o assunto em aberto ou encerrar a conversa?"
        "\n\nAinda em aberto:\n\nMenos urgente:\n1. O seu horário marcado (ainda não começou)"
        "\n\nOutras opções:\n2. Falar de um assunto novo\n3. Encerrar a conversa"
        "\n\nResponda com o número da opção."
    )
    assert fim["resumoDaConversa"] == [
        {"nome": "a pessoa presa", "desfecho": "dados confirmados e encaminhados", "codigo": codigo_do_assunto(chat)}
    ]
    assert fim["opcoesDoFim"] == ["1. O seu horário marcado", "2. Falar de um assunto novo", "3. Encerrar a conversa"]
    assert fim["assuntosEmAberto"] == [
        {
            "nome": "o seu horário marcado",
            "urgente": False,
            "urgencia": "menos_urgente",
            # 2026-11-13: sem o chatIdAssunto; o assunto é o tipoCaso (ou o flowId, nos da Maria).
            "codigo": codigo_do_assunto(f"{chat}-assunto-2"),
            "fase": "nao_iniciado",
            "tipoCaso": "agendamentos",
        }
    ]


# ---- 4. a conversa nova: sem pergunta, com a retomada e o pedido de ver -----------------------------


async def test_conversa_nova_do_mesmo_assunto_retoma_o_guardado(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, VD, PP)
    store = await obter_pendentes_store()
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat, "meu irmão está preso")
    # Sem pergunta: a Maria entende que é o assunto guardado e continua dele.
    assert (corpo["flowId"], corpo["status"]) == (ID_PESSOA_PRESA, "em_andamento")
    assert corpo["resposta"].startswith("Você já tinha esse assunto com a gente: a pessoa presa. Vamos continuar.\n\n")
    item = await store.buscar(f"{antiga}-assunto-2")
    assert item is not None and item["situacao"] == "em_andamento"
    await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    item = await store.buscar(f"{antiga}-assunto-2")
    assert item is not None and item["situacao"] == "resolvido"


async def test_conversa_nova_de_outro_assunto_segue_sem_pergunta(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, VD, PP)
    release.setenv("MOCK_NECESSIDADES", json.dumps([NOVO_PROCESSO]))
    corpo = await _comecar(cliente, auth, _chat(), "quero entrar com um processo de pensão")
    assert (corpo["status"], corpo["tipoCaso"]) == ("redirecionado", "novo-processo")
    item = await (await obter_pendentes_store()).buscar(f"{antiga}-assunto-2")
    assert item is not None and item["situacao"] == "pendente"


async def test_pedido_de_ver_os_assuntos_mostra_a_lista(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    await _conversa_com_pendente(cliente, auth, release, VD, NOVO_PROCESSO, PP)
    release.setenv("MOCK_NECESSIDADES", json.dumps(["tykhe:outros"]))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat, "quero ver meus assuntos")
    assert corpo == {
        "resposta": (
            "Qual você quer resolver agora?\n\n"
            "Urgente:\n1. A pessoa presa\n\n"
            "Menos urgente:\n2. O caso novo\n\n"
            "Outras opções:\n3. Nenhum, quero um assunto novo\n\n"
            "Responda com o número da opção."
        ),
        "tipoResposta": "opcoes",
        "opcoes": ["1. A pessoa presa", "2. O caso novo", "3. Nenhum, quero um assunto novo"],
        "status": "em_andamento",
        "_links": {"self": {"href": f"/atendimentos/{chat}"}, "responder": {"href": ORQ, "method": "POST"}},
    }
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "1"})
    assert (corpo["flowId"], corpo["status"]) == (ID_PESSOA_PRESA, "em_andamento")
    assert corpo["resposta"].startswith("Agora vamos falar da pessoa presa.\n\n")
    assert "assuntosPendentes" not in corpo


# ---- 5. a oferta no fim do assunto e a lista dos assuntos em aberto ---------------------------------


async def test_fim_do_assunto_oferece_os_abertos_e_a_lista_abre_o_escolhido(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat, "meu irmão está preso")
    fim = await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    assert fim["status"] == "concluido"
    [aberto] = fim["assuntosEmAberto"]
    assert (aberto["nome"], aberto["tipoCaso"], aberto["fase"]) == ("o caso novo", "novo-processo", "nao_iniciado")
    assert "chatIdAssunto" not in aberto, "2026-11-13: o assunto vai para a Tykhe pelo flowId ou pelo tipoCaso"
    vence = aberto["venceEm"]
    assert fim["resposta"].endswith(
        "\n\nQuer continuar com o assunto em aberto ou encerrar a conversa?"
        f"\n\nAinda em aberto:\n\nMenos urgente:\n1. O caso novo (guardado até {vence[8:10]}/{vence[5:7]}, ainda não começou)"
        "\n\nOutras opções:\n2. Falar de um assunto novo\n3. Encerrar a conversa"
        "\n\nResponda com o número da opção. Os assuntos em aberto ficam guardados por até 30 dias."
    )
    assert fim["opcoesDoFim"] == ["1. O caso novo", "2. Falar de um assunto novo", "3. Encerrar a conversa"]

    # A lista também vem pela rota dos assuntos em aberto, com o encerrar, e a resposta volta para a rota do próximo.
    r = await cliente.post(ABERTOS, json={"chatId": chat}, headers=auth)
    assert r.status_code == 200
    assert r.json() == {
        "resposta": (
            "Qual você quer resolver agora?\n\n"
            "Menos urgente:\n1. O caso novo\n\n"
            "Outras opções:\n2. Nenhum, quero um assunto novo\n3. Encerrar a conversa\n\n"
            "Responda com o número da opção."
        ),
        "tipoResposta": "opcoes",
        "opcoes": ["1. O caso novo", "2. Nenhum, quero um assunto novo", "3. Encerrar a conversa"],
        "status": "em_andamento",
        "assuntosEmAberto": fim["assuntosEmAberto"],
        "_links": {"self": {"href": f"/atendimentos/{chat}"}, "responder": {"href": PROXIMO, "method": "POST"}},
    }
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat, "resposta": "1. O caso novo"}, headers=auth)).json()
    assert (corpo["status"], corpo["tipoCaso"], corpo["chatId"]) == ("redirecionado", "novo-processo", f"{antiga}-assunto-2")
    item = await (await obter_pendentes_store()).buscar(f"{antiga}-assunto-2")
    assert item is not None and item["situacao"] == "resolvido"


async def test_botao_encerrar_fecha_a_conversa_e_guarda_os_abertos(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat, "meu irmão está preso")
    fim = await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    assert fim["opcoesDoFim"][-1] == "3. Encerrar a conversa"
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat, "resposta": "3"}, headers=auth)).json()
    assert corpo == {
        "resposta": "Combinado. Seus assuntos em aberto ficam guardados por até 30 dias. Quando quiser, é só voltar a falar com a gente.",
        "tipoResposta": "texto",
        "status": "concluido",
        "_links": {"self": {"href": f"/atendimentos/{chat}"}},
    }
    # Encerrar não resolve nada: o caso novo continua guardado.
    item = await (await obter_pendentes_store()).buscar(f"{antiga}-assunto-2")
    assert item is not None and item["situacao"] == "pendente"


async def test_botao_do_assunto_no_fim_abre_direto(cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat, "meu irmão está preso")
    await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat, "resposta": "O caso novo"}, headers=auth)).json()
    assert (corpo["status"], corpo["tipoCaso"], corpo["chatId"]) == ("redirecionado", "novo-processo", f"{antiga}-assunto-2")


async def test_assunto_unico_pelo_orquestrador_tem_resumo_e_atendimento_direto_nao(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    corpo = await _comecar(cliente, auth, chat, "meu irmão está preso")
    fim = await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    assert fim["resposta"].endswith(
        f"\n\nResumo da nossa conversa:\n• A pessoa presa: dados confirmados e encaminhados (código {codigo_do_assunto(chat)})"
        "\n\nQuer falar de um assunto novo ou encerrar a conversa?\n1. Falar de um assunto novo\n2. Encerrar a conversa"
        "\n\nResponda com o número da opção."
    )
    assert fim["opcoesDoFim"] == ["1. Falar de um assunto novo", "2. Encerrar a conversa"]
    assert "assuntosEmAberto" not in fim

    # Atendimento aberto direto, sem o orquestrador: o fim fica como era.
    direto = _chat()
    r = await cliente.post("/atendimentos", json={"chatId": direto, "flowId": ID_PESSOA_PRESA}, headers=auth)
    assert r.status_code in (200, 201)
    fim = await _pessoa_presa_ate_o_fim(cliente, auth, direto, r.json())
    assert fim["status"] == "concluido"
    assert "resumoDaConversa" not in fim and "opcoesDoFim" not in fim
    assert "Resumo da nossa conversa" not in fim["resposta"]


async def test_lista_nenhum_pede_o_assunto_novo(cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch) -> None:
    await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    # Outro assunto: o caso novo guardado continua em aberto.
    release.setenv("MOCK_NECESSIDADES", json.dumps([HORARIO]))
    chat = _chat()
    await _comecar(cliente, auth, chat, "quero remarcar o meu horário")
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat, "resposta": "Nenhum, quero um assunto novo"}, headers=auth)).json()
    assert corpo == {
        "resposta": "Pode me contar o que você precisa?",
        "tipoResposta": "texto",
        "status": "em_andamento",
        "_links": {"self": {"href": f"/atendimentos/{chat}"}, "responder": {"href": ORQ, "method": "POST"}},
    }
    # Resposta que a Maria não entende: a lista de novo.
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat, "resposta": "hmm"}, headers=auth)).json()
    assert corpo["opcoes"] == ["1. O caso novo", "2. Nenhum, quero um assunto novo", "3. Encerrar a conversa"]


async def test_atendimento_humano_avisa_o_que_ficou_para_depois(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    """Decisão da Nicole (2026-11-13): o assunto que termina no atendimento humano também avisa o pendente."""
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    await _comecar(cliente, auth, chat)
    await _orq(cliente, auth, {"chatId": chat, "resposta": "o plano primeiro"})
    fim = await _plano_ate_o_fim(cliente, auth, chat)
    assert fim["resposta"].endswith("\n\nTambém ficou para depois: a pessoa presa.")
    assert "opcoesDoFim" not in fim


async def test_sem_assunto_em_aberto_pede_o_que_a_pessoa_precisa(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    await _comecar(cliente, auth, chat, "meu irmão está preso")
    corpo = (await cliente.post(ABERTOS, json={"chatId": chat}, headers=auth)).json()
    assert (corpo["resposta"], corpo["tipoResposta"]) == ("Você não tem assuntos em aberto. Pode me contar o que você precisa?", "texto")


async def test_guardado_de_outra_conversa_abre_pelo_id_e_e_idempotente(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, VD, PP)
    release.setenv("MOCK_NECESSIDADES", json.dumps([NOVO_PROCESSO]))
    chat = _chat()
    await _comecar(cliente, auth, chat, "quero entrar com um processo de pensão")
    assunto = f"{antiga}-assunto-2"
    primeira = (await cliente.post(PROXIMO, json={"chatId": chat, "assunto": assunto}, headers=auth)).json()
    assert (primeira["flowId"], primeira["chatId"]) == (ID_PESSOA_PRESA, assunto)
    assert primeira["resposta"].startswith("Agora vamos falar da pessoa presa.\n\n")
    item = await (await obter_pendentes_store()).buscar(assunto)
    assert item is not None and item["situacao"] == "em_andamento"
    segunda = (await cliente.post(PROXIMO, json={"chatId": chat, "assunto": assunto}, headers=auth)).json()
    assert segunda["chatId"] == assunto
    assert primeira["resposta"].endswith(segunda["resposta"])


async def test_guardado_abre_pelo_flow_id(cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch) -> None:
    """Decisão da Nicole (2026-11-13): a Tykhe manda o flowId do item de assuntosEmAberto, e não o id interno."""
    antiga = await _conversa_com_pendente(cliente, auth, release, VD, PP)
    release.setenv("MOCK_NECESSIDADES", json.dumps([NOVO_PROCESSO]))
    chat = _chat()
    await _comecar(cliente, auth, chat, "quero entrar com um processo de pensão")
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat, "assunto": ID_PESSOA_PRESA}, headers=auth)).json()
    assert (corpo["flowId"], corpo["chatId"]) == (ID_PESSOA_PRESA, f"{antiga}-assunto-2")
    assert corpo["resposta"].startswith("Agora vamos falar da pessoa presa.\n\n")


async def test_guardado_da_tykhe_abre_pelo_tipo_caso(cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    await _comecar(cliente, auth, chat, "meu irmão está preso")
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat, "assunto": "novo-processo"}, headers=auth)).json()
    assert (corpo["status"], corpo["tipoCaso"], corpo["chatId"]) == ("redirecionado", "novo-processo", f"{antiga}-assunto-2")


async def test_flow_id_que_nao_esta_em_aberto_nao_abre(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    await _conversa_com_pendente(cliente, auth, release, VD, PP)
    release.setenv("MOCK_NECESSIDADES", json.dumps([NOVO_PROCESSO]))
    chat = _chat()
    await _comecar(cliente, auth, chat, "quero entrar com um processo", id_usuario="outra-pessoa")
    r = await cliente.post(PROXIMO, json={"chatId": chat, "assunto": ID_PESSOA_PRESA}, headers=auth)
    assert (r.status_code, r.json()) == (404, {"erro": "assunto não encontrado para esta pessoa"})


async def test_assunto_de_outra_pessoa_nao_abre(cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, VD, PP)
    release.setenv("MOCK_NECESSIDADES", json.dumps([NOVO_PROCESSO]))
    chat = _chat()
    await _comecar(cliente, auth, chat, "quero entrar com um processo", id_usuario="outra-pessoa")
    r = await cliente.post(PROXIMO, json={"chatId": chat, "assunto": f"{antiga}-assunto-2"}, headers=auth)
    assert (r.status_code, r.json()) == (404, {"erro": "assunto não encontrado para esta pessoa"})


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
