"""O CPF no começo e os assuntos pendentes por assistido (#450, multi-fluxo, só no release), pela API.

No release, sem `dadosConhecidos.cpf` na 1ª chamada, a Maria pergunta o CPF logo depois da 1ª mensagem, antes de
abrir qualquer fluxo e antes da pergunta da ordem. Achou no Verde, confirma o nome mascarado uma vez; os fluxos
abertos depois recebem o CPF e não perguntam de novo. Com a pessoa identificada (idPessoa), os outros assuntos ficam
guardados por 30 dias, e numa conversa nova a Maria pergunta se ela quer falar de um deles.

A classificação é simulada (`MOCK_NECESSIDADES`); os fluxos e o Verde simulado são os de verdade. No Verde simulado,
"00000000000" não é encontrado, "66666666666" é falha de infra e qualquer outro CPF é a pessoa de teste
("Pessoa de Teste (mock)", idPessoa 999999).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, fluxos_por_id
from maria.orquestrador.graph import TEXTO_CPF, TEXTO_CPF_INVALIDO, TEXTO_CPF_NAO_ENCONTRADO, TEXTO_CPF_RECUSADO, obter_grafo
from maria.shared import pendentes_db
from maria.shared.pendentes_db import obter_pendentes_store
from maria.subgrafos.identificar_assistido.graph import TEXTO_CPF as TEXTO_CPF_DO_FLUXO

ORQ = "/atendimentos/orquestrador"
PROXIMO = "/atendimentos/proximo-assunto"
RESPOSTAS = "/atendimentos/respostas"
CPF = "11111111111"
ID_PESSOA = "999999"
CONFIRMA = "Confirma que seus dados são: Pessoa T.?"
DADOS_NO_RIO = {"endereco": {"cep": "20000000"}}
PLANO = {"id": ID_PROBLEMAS_PLANO_SAUDE, "evidencia": "o plano negou a cirurgia", "urgente": True}
PP = {"id": ID_PESSOA_PRESA, "evidencia": "meu irmão está preso"}
NOVO_PROCESSO = {"id": "tykhe:novo-processo", "evidencia": "quero entrar com um processo de pensão"}

_ids = count(1)


def _chat() -> str:
    return f"teste-cpf-pendentes-{next(_ids)}"


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


async def _identificar(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str, relato: str = "relato") -> dict[str, Any]:
    """1ª mensagem sem CPF, o CPF digitado e o "Sim" da confirmação. Devolve a resposta depois da confirmação."""
    corpo = await _orq(cliente, auth, {"chatId": chat, "mensagem": relato, "dadosConhecidos": DADOS_NO_RIO})
    assert corpo["resposta"] == TEXTO_CPF
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": CPF})
    assert corpo["resposta"] == CONFIRMA
    return await _orq(cliente, auth, {"chatId": chat, "resposta": "Sim"})


async def _estado_orquestrador(chat: str) -> dict[str, Any]:
    return dict((await obter_grafo().aget_state({"configurable": {"thread_id": f"orquestrador:{chat}"}})).values)


async def _estado_fluxo(fluxo: str, chat: str) -> dict[str, Any]:
    return dict((await fluxos_por_id[fluxo].obter_grafo().aget_state({"configurable": {"thread_id": chat}})).values)


async def _pessoa_presa_ate_o_fim(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str, primeira: dict[str, Any]) -> list[str]:
    """Responde o caminho da pessoa presa até o fim e devolve as perguntas que a Maria fez."""
    perguntas = [primeira["resposta"]]
    corpo = primeira
    for _ in range(14):
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
        perguntas.append(corpo["resposta"])
    assert corpo["status"] != "em_andamento"
    return perguntas


async def _plano_ate_o_fim(cliente: httpx.AsyncClient, auth: dict[str, str], chat: str) -> dict[str, Any]:
    """O fluxo do plano até o fim: "para você?" e 3 respostas sem a foto (atendimento humano)."""
    corpo: dict[str, Any] = {}
    for resposta in ("true", "mandei", "mandei", "mandei"):
        corpo = (await cliente.post(RESPOSTAS, json={"chatId": chat, "resposta": resposta}, headers=auth)).json()
    assert corpo["status"] == "handoff_humano"
    return corpo


async def _conversa_com_pendente(cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch, *necessidades: Any) -> str:
    """Uma conversa com dois assuntos e a pessoa identificada: o 2º fica guardado. Devolve o chatId dela."""
    release.setenv("MOCK_NECESSIDADES", json.dumps(list(necessidades)))
    chat = _chat()
    corpo = await _identificar(cliente, auth, chat)
    assert corpo["tipoResposta"] == "sim_nao"  # a ordem dos assuntos
    await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    return chat


# ---- 1. o CPF no começo ------------------------------------------------------------------


async def test_pergunta_o_cpf_antes_da_ordem_e_o_fluxo_nao_pergunta_de_novo(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    corpo = await _orq(cliente, auth, {"chatId": chat, "mensagem": "meu irmão está preso e o plano negou a cirurgia"})
    assert corpo == {
        "resposta": "Para eu te identificar e guardar os seus assuntos, qual é o seu CPF?",
        "tipoResposta": "texto",
        "status": "em_andamento",
        "_links": {"self": {"href": f"/atendimentos/{chat}"}, "responder": {"href": ORQ, "method": "POST"}},
    }
    # Com pontuação também vale. Achou no Verde: a confirmação com o nome mascarado (#393).
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "111.111.111-11"})
    assert (corpo["resposta"], corpo["tipoResposta"], corpo["opcoes"]) == (CONFIRMA, "sim_nao", ["Sim", "Não"])
    # Confirmado: a ordem dos assuntos, com o relato da 1ª mensagem (a classificação não roda de novo).
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "Sim"})
    assert corpo["resposta"].startswith("Entendi. Você falou de duas coisas: o plano de saúde e a pessoa presa.")
    estado = await _estado_orquestrador(chat)
    assert (estado["idPessoa"], estado["dadosConhecidos"]["cpf"]) == (999999, CPF)

    # O 1º assunto abre com o CPF; o 2º, pela rota do próximo assunto, também, e não pergunta o CPF de novo.
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    assert corpo["flowId"] == ID_PROBLEMAS_PLANO_SAUDE
    assert (await _estado_fluxo(ID_PROBLEMAS_PLANO_SAUDE, chat))["cpf"] == CPF
    await _plano_ate_o_fim(cliente, auth, chat)
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert corpo["flowId"] == ID_PESSOA_PRESA
    perguntas = await _pessoa_presa_ate_o_fim(cliente, auth, f"{chat}-assunto-2", corpo)
    assert TEXTO_CPF_DO_FLUXO not in perguntas
    assert not any(p.startswith("Confirma que seus dados são") for p in perguntas)
    assert (await _estado_fluxo(ID_PESSOA_PRESA, f"{chat}-assunto-2"))["cpf"] == CPF

    # LGPD: nem o CPF nem o nome vão para o log; a pergunta sai com a etapa.
    saida = capsys.readouterr().out
    assert CPF not in saida and "Pessoa T." not in saida and "Pessoa de Teste" not in saida
    assert "orquestrador: pergunta de identificação enviada" in saida


async def test_um_assunto_so_abre_o_fluxo_sem_pedir_o_cpf_de_novo(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    corpo = await _identificar(cliente, auth, chat, "meu irmão está preso")
    assert (corpo["flowId"], corpo["status"]) == (ID_PESSOA_PRESA, "em_andamento")
    perguntas = await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    assert TEXTO_CPF_DO_FLUXO not in perguntas
    assert not any(p.startswith("Confirma que seus dados são") for p in perguntas)


async def test_cpf_invalido_tres_vezes_segue_sem_identificar(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    assert (await _orq(cliente, auth, {"chatId": chat, "mensagem": "relato"}))["resposta"] == TEXTO_CPF
    assert (await _orq(cliente, auth, {"chatId": chat, "resposta": "não sei"}))["resposta"] == TEXTO_CPF_INVALIDO
    assert (await _orq(cliente, auth, {"chatId": chat, "resposta": "123"}))["resposta"] == TEXTO_CPF_INVALIDO
    # 3ª tentativa: a conversa segue normalmente, sem atendimento humano.
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "1234567890"})
    assert corpo["status"] == "em_andamento"
    assert corpo["resposta"].startswith("Entendi. Você falou de duas coisas")
    estado = await _estado_orquestrador(chat)
    assert estado.get("idPessoa") is None and "cpf" not in (estado.get("dadosConhecidos") or {})
    # Sem idPessoa, nada é guardado.
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    assert corpo["assuntosPendentes"]
    assert await (await obter_pendentes_store()).listar_ativos(ID_PESSOA) == []


async def test_cpf_nao_encontrado_pergunta_de_novo_e_depois_confirma(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    await _orq(cliente, auth, {"chatId": chat, "mensagem": "meu irmão está preso"})
    assert (await _orq(cliente, auth, {"chatId": chat, "resposta": "000.000.000-00"}))["resposta"] == TEXTO_CPF_NAO_ENCONTRADO
    assert (await _orq(cliente, auth, {"chatId": chat, "resposta": CPF}))["resposta"] == CONFIRMA
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "sim"})
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert (await _estado_fluxo(ID_PESSOA_PRESA, chat))["cpf"] == CPF


async def test_nao_na_confirmacao_pergunta_o_cpf_de_novo(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    await _orq(cliente, auth, {"chatId": chat, "mensagem": "meu irmão está preso"})
    await _orq(cliente, auth, {"chatId": chat, "resposta": "22222222222"})
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "Não"})
    assert (corpo["resposta"], corpo["tipoResposta"]) == (TEXTO_CPF_RECUSADO, "texto")
    assert (await _orq(cliente, auth, {"chatId": chat, "resposta": CPF}))["resposta"] == CONFIRMA
    await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    estado = await _estado_orquestrador(chat)
    assert (estado["dadosConhecidos"]["cpf"], estado["idPessoa"]) == (CPF, 999999)


async def test_tres_nao_na_confirmacao_seguem_sem_identificar(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    await _orq(cliente, auth, {"chatId": chat, "mensagem": "meu irmão está preso"})
    for _ in range(2):
        await _orq(cliente, auth, {"chatId": chat, "resposta": CPF})
        assert (await _orq(cliente, auth, {"chatId": chat, "resposta": "false"}))["resposta"] == TEXTO_CPF_RECUSADO
    await _orq(cliente, auth, {"chatId": chat, "resposta": CPF})
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "false"})
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert "cpf" not in await _estado_fluxo(ID_PESSOA_PRESA, chat)


async def test_verde_fora_do_ar_segue_sem_identificar(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    await _orq(cliente, auth, {"chatId": chat, "mensagem": "meu irmão está preso"})
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "66666666666"})
    assert (corpo["flowId"], corpo["status"]) == (ID_PESSOA_PRESA, "em_andamento")
    assert (await _estado_orquestrador(chat)).get("idPessoa") is None


async def test_cpf_da_tykhe_nao_pergunta_nem_confirma(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    corpo = await _orq(cliente, auth, {"chatId": chat, "mensagem": "meu irmão está preso", "dadosConhecidos": {"cpf": "111.111.111-11"}})
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert (await _estado_orquestrador(chat))["idPessoa"] == 999999


# ---- 2. os pendentes guardados pelo idPessoa ------------------------------------------------


async def test_pendentes_guardados_pelo_id_pessoa_sem_o_relato(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    chat = await _conversa_com_pendente(cliente, auth, release, PLANO, PP, NOVO_PROCESSO)
    ativos = await (await obter_pendentes_store()).listar_ativos(ID_PESSOA)
    assert [(p["chatIdOrigem"], p["posicao"], p["nome"], p.get("flowId"), p.get("tipoCaso")) for p in ativos] == [
        (chat, 2, "a pessoa presa", ID_PESSOA_PRESA, None),
        (chat, 3, "o caso novo", None, "novo-processo"),
    ]
    # Só o assunto, a situação e as datas: nunca o relato nem os dadosConhecidos.
    assert set(ativos[0]) == {"chatIdOrigem", "posicao", "nome", "urgente", "situacao", "criadoEm", "venceEm", "prorrogado", "flowId"}


async def test_rota_do_proximo_assunto_marca_a_situacao(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    chat = await _conversa_com_pendente(cliente, auth, release, PLANO, PP, NOVO_PROCESSO)
    store = await obter_pendentes_store()
    await _plano_ate_o_fim(cliente, auth, chat)

    corpo = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert corpo["chatId"] == f"{chat}-assunto-2"
    item = await store.buscar(chat, 2)
    assert item is not None and item["situacao"] == "em_andamento"
    # Fim do fluxo do assunto aberto pela rota: resolvido.
    await _pessoa_presa_ate_o_fim(cliente, auth, f"{chat}-assunto-2", corpo)
    item = await store.buscar(chat, 2)
    assert item is not None and item["situacao"] == "resolvido"

    # Assunto da Tykhe devolvido pela rota: resolvido.
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert corpo["tipoCaso"] == "novo-processo"
    item = await store.buscar(chat, 3)
    assert item is not None and item["situacao"] == "resolvido"
    assert await store.listar_ativos(ID_PESSOA) == []


# ---- 3. a pergunta dos pendentes quando a pessoa volta --------------------------------------


async def test_conversa_nova_escolhe_o_pendente_da_maria(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, PP)
    store = await obter_pendentes_store()

    release.setenv("MOCK_NECESSIDADES", json.dumps([NOVO_PROCESSO]))
    chat = _chat()
    corpo = await _identificar(cliente, auth, chat, "quero entrar com um processo de pensão")
    assert corpo == {
        "resposta": "Você tem um assunto guardado: a pessoa presa. Quer falar dele agora ou do que você acabou de contar?",
        "tipoResposta": "opcoes",
        "opcoes": ["O que acabei de contar", "A pessoa presa"],
        "status": "em_andamento",
        "_links": {"self": {"href": f"/atendimentos/{chat}"}, "responder": {"href": ORQ, "method": "POST"}},
    }
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "A pessoa presa"})
    # O assunto guardado abre nesta conversa, com o CPF; o que ela acabou de contar fica pendente.
    assert (corpo["flowId"], corpo["status"]) == (ID_PESSOA_PRESA, "em_andamento")
    assert corpo["resposta"].startswith("Agora vamos falar da pessoa presa.\n\n")
    assert corpo["assuntosPendentes"] == [{"nome": "o caso novo", "urgente": False, "tipoCaso": "novo-processo"}]
    assert (await _estado_fluxo(ID_PESSOA_PRESA, chat))["cpf"] == CPF
    item = await store.buscar(antiga, 2)
    assert item is not None and item["situacao"] == "em_andamento"
    # O assunto novo ficou guardado por esta conversa.
    assert [(p["chatIdOrigem"], p["nome"]) for p in await store.listar_ativos(ID_PESSOA)] == [(chat, "o caso novo")]

    # Fim do fluxo: o assunto guardado fica resolvido, e a resposta final lista o que ficou pendente.
    perguntas = await _pessoa_presa_ate_o_fim(cliente, auth, chat, corpo)
    assert TEXTO_CPF_DO_FLUXO not in perguntas
    item = await store.buscar(antiga, 2)
    assert item is not None and item["situacao"] == "resolvido"


async def test_conversa_nova_escolhe_o_pendente_da_tykhe_pelo_numero(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    corpo = await _identificar(cliente, auth, chat, "meu irmão está preso")
    assert corpo["opcoes"] == ["O que acabei de contar", "O caso novo"]
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "2"})
    assert (corpo["status"], corpo["tipoCaso"]) == ("redirecionado", "novo-processo")
    assert corpo["assuntosPendentes"] == [
        {"nome": "a pessoa presa", "urgente": False, "flowId": ID_PESSOA_PRESA, "dadosConhecidos": {"parentesco": "Irmão(a)"}}
    ]
    store = await obter_pendentes_store()
    item = await store.buscar(antiga, 2)
    assert item is not None and item["situacao"] == "resolvido"
    # A pessoa presa ficou guardada por esta conversa, e a rota do próximo assunto a abre com o CPF.
    corpo = (await cliente.post(PROXIMO, json={"chatId": chat}, headers=auth)).json()
    assert (corpo["chatId"], corpo["flowId"]) == (f"{chat}-assunto-2", ID_PESSOA_PRESA)
    assert (await _estado_fluxo(ID_PESSOA_PRESA, f"{chat}-assunto-2"))["cpf"] == CPF


async def test_conversa_nova_escolhe_o_que_acabou_de_contar(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PLANO, PP]))
    chat = _chat()
    await _identificar(cliente, auth, chat)
    # O caminho de sempre: a ordem dos assuntos do relato novo.
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "O que acabei de contar"})
    assert corpo["resposta"].startswith("Entendi. Você falou de duas coisas")
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "true"})
    assert corpo["flowId"] == ID_PROBLEMAS_PLANO_SAUDE
    # O pendente antigo continua guardado, e o da conversa nova também.
    ativos = await (await obter_pendentes_store()).listar_ativos(ID_PESSOA)
    assert [(p["chatIdOrigem"], p["nome"]) for p in ativos] == [(antiga, "o caso novo"), (chat, "a pessoa presa")]


async def test_resposta_nao_entendida_segue_com_o_que_acabou_de_contar(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    await _identificar(cliente, auth, chat, "meu irmão está preso")
    corpo = await _orq(cliente, auth, {"chatId": chat, "resposta": "hmm"})
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert "assuntosPendentes" not in corpo


async def test_pendente_vencido_e_apagado_e_nao_e_perguntado(
    cliente: httpx.AsyncClient, auth: dict[str, str], release: pytest.MonkeyPatch
) -> None:
    antiga = await _conversa_com_pendente(cliente, auth, release, PLANO, NOVO_PROCESSO)
    # 31 dias depois, sem contato.
    depois = datetime.now(UTC) + timedelta(days=31)
    release.setattr(pendentes_db, "agora", lambda: depois)
    release.setenv("MOCK_NECESSIDADES", json.dumps([PP]))
    chat = _chat()
    corpo = await _identificar(cliente, auth, chat, "meu irmão está preso")
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert await (await obter_pendentes_store()).buscar(antiga, 2) is None


# ---- produção ---------------------------------------------------------------------------


async def test_producao_nao_pergunta_o_cpf_nem_usa_os_pendentes(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MARIA_AMBIENTE", raising=False)
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    chat = _chat()
    corpo = await _orq(cliente, auth, {"chatId": chat, "mensagem": "meu irmão está preso"})
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert TEXTO_CPF not in corpo["resposta"]
    estado = await _estado_orquestrador(chat)
    assert not {"identificacaoFeita", "idPessoa", "pendentesGuardados"} & set(estado)
    # A store dos pendentes nem é criada.
    assert pendentes_db._tarefa is None
