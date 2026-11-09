"""O multi-fluxo pela API (#435, fase 1a da #279): a ordem, o fluxo do primeiro assunto e o campo
`assuntosPendentes`. A classificação é simulada (`MOCK_NECESSIDADES`); o fluxo do plano de saúde e o
Verde simulado são os de verdade.

Na produção, nada muda: sem `MARIA_AMBIENTE=release`, a resposta não tem o campo novo.
"""

from __future__ import annotations

import json
from itertools import count

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, fluxos_por_id

BASE = "/atendimentos/orquestrador"
# O CEP faz o fluxo do plano seguir para a 1ª pergunta (o Verde simulado devolve o Rio).
DADOS_NO_RIO = {"endereco": {"cep": "20000000"}}
# Sem dizer de quem é a cirurgia: o fluxo do plano pergunta "para você?" (#438 leria "da minha mãe").
TRECHO_PLANO = "o plano negou a cirurgia"
NECESSIDADES = [
    {"id": ID_PESSOA_PRESA, "evidencia": "meu irmão está preso"},
    {"id": ID_PROBLEMAS_PLANO_SAUDE, "evidencia": TRECHO_PLANO, "urgente": True},
]
RELATO = "meu irmão está preso e o plano negou a cirurgia"
PENDENTE_PP = {"nome": "a pessoa presa", "urgente": False, "flowId": ID_PESSOA_PRESA, "dadosConhecidos": {"parentesco": "Irmão(a)"}}

_ids = count(1)


def _chat() -> str:
    return f"teste-orq-multi-{next(_ids)}"


@pytest.fixture
def multi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", raising=False)
    monkeypatch.setenv("MOCK_NECESSIDADES", json.dumps(NECESSIDADES))


@pytest.mark.usefixtures("multi")
async def test_release_dois_assuntos_ordem_fluxo_e_pendentes_ate_o_fim(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    chat = _chat()

    # 1. Relato com dois assuntos: a Maria propõe a ordem, no formato da desambiguação.
    r = await cliente.post(BASE, json={"chatId": chat, "mensagem": RELATO, "dadosConhecidos": DADOS_NO_RIO}, headers=auth)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo == {
        "resposta": (
            "Entendi. Você falou de duas coisas: o plano de saúde e a pessoa presa.\n"
            "Vou começar pelo plano de saúde, porque parece mais urgente.\n"
            "Depois, falamos da pessoa presa.\n"
            "Pode ser assim?"
        ),
        "tipoResposta": "sim_nao",
        "opcoes": ["Sim", "Não"],
        "status": "em_andamento",
        "_links": {"self": {"href": f"/atendimentos/{chat}"}, "responder": {"href": BASE, "method": "POST"}},
    }

    # 2. "true" (o botão Sim da Tykhe): abre o fluxo do plano, com o resto pendente.
    r = await cliente.post(BASE, json={"chatId": chat, "resposta": "true", "dadosConhecidos": DADOS_NO_RIO}, headers=auth)
    corpo = r.json()
    assert corpo["status"] == "em_andamento"
    assert corpo["flowId"] == ID_PROBLEMAS_PLANO_SAUDE
    assert corpo["resposta"].startswith("Combinado. Vamos começar pelo plano de saúde.\n\n")
    assert corpo["resposta"].endswith("O atendimento é para você? Responda não se for para outra pessoa.")
    assert corpo["assuntosPendentes"] == [PENDENTE_PP]

    # 3. O fluxo recebeu só o trecho do plano, e não o relato inteiro (achado do teste de 06/11).
    estado = await fluxos_por_id[ID_PROBLEMAS_PLANO_SAUDE].obter_grafo().aget_state({"configurable": {"thread_id": chat}})
    assert estado.values["relato"] == TRECHO_PLANO

    # 4. No meio do fluxo, o campo não aparece.
    r = await cliente.post("/atendimentos/respostas", json={"chatId": chat, "resposta": "true"}, headers=auth)
    corpo = r.json()
    assert (corpo["status"], corpo["tipoResposta"]) == ("em_andamento", "link_imagem")
    assert "assuntosPendentes" not in corpo

    # 5. Fim do fluxo (3 respostas sem a foto): a resposta final ainda lista a pessoa presa.
    for _ in range(3):
        r = await cliente.post("/atendimentos/respostas", json={"chatId": chat, "resposta": "mandei"}, headers=auth)
    corpo = r.json()
    assert (corpo["status"], corpo["metadados"]["motivoHandoff"]) == ("handoff_humano", "imagens_pendentes")
    assert corpo["assuntosPendentes"] == [PENDENTE_PP]


@pytest.mark.usefixtures("multi")
async def test_release_primeiro_assunto_da_tykhe_redireciona_com_pendentes(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    monkeypatch.setenv(
        "MOCK_NECESSIDADES", json.dumps([{"id": ID_PESSOA_PRESA, "evidencia": "x"}, {"id": "tykhe:saude", "evidencia": "y"}])
    )
    chat = _chat()
    await cliente.post(BASE, json={"chatId": chat, "mensagem": RELATO}, headers=auth)
    r = await cliente.post(BASE, json={"chatId": chat, "resposta": "Sim"}, headers=auth)
    corpo = r.json()
    assert (corpo["status"], corpo["tipoCaso"]) == ("redirecionado", "saude")
    assert corpo["assuntosPendentes"] == [{"nome": "a pessoa presa", "urgente": False, "flowId": ID_PESSOA_PRESA}]


@pytest.mark.usefixtures("multi")
async def test_release_um_assunto_so_responde_como_hoje(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    monkeypatch.setenv("MOCK_NECESSIDADES", json.dumps([ID_PROBLEMAS_PLANO_SAUDE]))
    r = await cliente.post(
        BASE, json={"chatId": _chat(), "mensagem": "o plano negou a cirurgia", "dadosConhecidos": DADOS_NO_RIO}, headers=auth
    )
    corpo = r.json()
    assert corpo["flowId"] == ID_PROBLEMAS_PLANO_SAUDE
    assert "assuntosPendentes" not in corpo
    assert not corpo["resposta"].startswith("Combinado")


@pytest.mark.usefixtures("multi")
async def test_producao_nao_tem_multi_fluxo(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Mesmo com MOCK_NECESSIDADES, a produção usa a classificação de sempre e não lista pendentes."""
    monkeypatch.delenv("MARIA_AMBIENTE", raising=False)
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    r = await cliente.post(BASE, json={"chatId": _chat(), "mensagem": RELATO}, headers=auth)
    corpo = r.json()
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert "assuntosPendentes" not in corpo
    assert corpo["tipoResposta"] != "sim_nao" or "Pode ser assim?" not in corpo["resposta"]


async def test_release_o_que_a_pessoa_ja_disse_segue_para_o_proximo_assunto(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#442: "meu sobrinho foi preso" no 1º relato; quando a Tykhe abre a pessoa presa depois, com o
    `dadosConhecidos` do item pendente, a Maria não pergunta o parentesco nem o CPF de novo."""
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    necessidades = [
        {"id": ID_PROBLEMAS_PLANO_SAUDE, "evidencia": "o plano negou minha cirurgia", "urgente": True},
        {"id": ID_PESSOA_PRESA, "evidencia": "meu sobrinho foi preso"},
    ]
    monkeypatch.setenv("MOCK_NECESSIDADES", json.dumps(necessidades))
    chat = _chat()
    dados = {**DADOS_NO_RIO, "cpf": "11111111111"}
    relato = "o plano negou minha cirurgia e meu sobrinho foi preso"
    await cliente.post(BASE, json={"chatId": chat, "mensagem": relato, "dadosConhecidos": dados}, headers=auth)
    corpo = (await cliente.post(BASE, json={"chatId": chat, "resposta": "true"}, headers=auth)).json()
    # O plano já sabe que é para a própria pessoa ("minha cirurgia") e vai direto para a foto.
    assert corpo["tipoResposta"] == "link_imagem"
    pendente = corpo["assuntosPendentes"][0]
    assert pendente["flowId"] == ID_PESSOA_PRESA
    assert pendente["dadosConhecidos"] == {"parentesco": "Tio(a)"}

    for _ in range(3):
        corpo = (await cliente.post("/atendimentos/respostas", json={"chatId": chat, "resposta": "mandei"}, headers=auth)).json()
    assert corpo["status"] == "handoff_humano"
    proximo = corpo["assuntosPendentes"][0]
    assert proximo["dadosConhecidos"] == {"cpf": "11111111111", "parentesco": "Tio(a)"}

    # A Tykhe abre o próximo assunto com o que a Maria guardou.
    outro = _chat()
    corpo = (
        await cliente.post(
            "/atendimentos",
            json={"chatId": outro, "flowId": proximo["flowId"], "dadosConhecidos": proximo["dadosConhecidos"]},
            headers=auth,
        )
    ).json()
    perguntas = [corpo["resposta"]]
    for resposta in ("true", "0000088-95.2026.8.19.0010", "11111111111", "true", "true", "true"):
        if corpo["status"] != "em_andamento":
            break
        corpo = (await cliente.post("/atendimentos/respostas", json={"chatId": outro, "resposta": resposta}, headers=auth)).json()
        perguntas.append(corpo["resposta"])
    assert "Qual seu parentesco com a pessoa presa?" not in perguntas
    estado = await fluxos_por_id[ID_PESSOA_PRESA].obter_grafo().aget_state({"configurable": {"thread_id": outro}})
    assert estado.values["parentesco"] == "Tio(a)"
