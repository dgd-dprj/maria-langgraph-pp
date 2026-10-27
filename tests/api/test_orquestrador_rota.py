"""Traduzido de `test/orquestrador.test.ts` (develop @ 1157a6d): a mecânica da rota
POST /atendimentos/orquestrador. A classificação fica no mock
(`MOCK_CLASSIFICACAO_FLOWID`/`FLOWIDS`), e `APP_ENV=test` nunca chama o Bedrock.

Os 23 testes de develop (os 7 tipos da Tykhe contam um por tipo): 22 no PR 1 do
api e, no PR 2, o de `viaOrquestrador` (#189/#191), que responde pelo
`POST /atendimentos/respostas`, e as conferências por `GET /atendimentos/:chatId`.
"""

import uuid
from collections.abc import AsyncIterator
from itertools import count

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA, catalogo_para_classificacao
from maria.fluxos.tipos_tykhe import TIPOS_TYKHE, TipoTykhe
from maria.shared.fluxos_planejados_db import FluxoPlanejado, adicionar_planejado_de_teste, remover_planejado_de_teste
from maria.shared.perguntas_db import PerguntaArvore, obter_perguntas_store

BASE = "/atendimentos/orquestrador"
_ids = count(1)


def novo_chat_id() -> str:
    return f"teste-orq-{next(_ids)}"


def _planejado(id_: str, nome: str, categoria: int) -> FluxoPlanejado:
    return {"id": id_, "nome": nome, "descricao": nome, "idCategoriaAssuntoVerde": categoria, "palavrasChave": []}


@pytest.fixture
async def planejado() -> AsyncIterator[FluxoPlanejado]:
    fluxo = _planejado("00000000-0000-0000-0000-000000000099", "fluxo-teste-planejado", 99999)
    await adicionar_planejado_de_teste(fluxo)
    yield fluxo
    await remover_planejado_de_teste(fluxo["id"])


async def test_sem_mensagem_400(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(BASE, json={}, headers=auth)
    assert r.status_code == 400


async def test_resposta_vazia_400_e_nao_500(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    # #185: viraria Command(resume="").
    r = await cliente.post(BASE, json={"chatId": novo_chat_id(), "resposta": ""}, headers=auth)
    assert r.status_code == 400


async def test_sem_authorization_401(cliente: httpx.AsyncClient) -> None:
    r = await cliente.post(BASE, json={"mensagem": "qualquer coisa"})
    assert r.status_code == 401


async def test_nao_identifica_nenhum_fluxo_redireciona_para_outros(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(BASE, json={"chatId": novo_chat_id(), "mensagem": "quero saber sobre meu carnê do IPTU"}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "redirecionado"
    assert corpo["tipoCaso"] == "outros"
    assert "flowId" not in corpo
    assert corpo["tokensGastos"] == {"input": 0, "output": 0, "total": 0}


async def test_identifica_fluxo_planejado_grafo_padrao_conclui(
    cliente: httpx.AsyncClient, auth: dict[str, str], planejado: FluxoPlanejado, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", planejado["id"])
    monkeypatch.setenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", "true")  # #225: planejados só com a chave ligada
    r = await cliente.post(BASE, json={"chatId": novo_chat_id(), "mensagem": "preciso de um fluxo que ainda não existe"}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "concluido"
    assert corpo["flowId"] == planejado["id"], "flowId do planejado deve aparecer: o grafo padrão rodou de verdade"
    assert "sendo construíd" in corpo["resposta"].lower()


async def test_duas_categorias_planejadas_nao_misturam_estado(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _planejado("00000000-0000-0000-0000-0000000000a1", "planejado-a", 88881)
    b = _planejado("00000000-0000-0000-0000-0000000000b2", "planejado-b", 88882)
    await adicionar_planejado_de_teste(a)
    await adicionar_planejado_de_teste(b)
    monkeypatch.setenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", "true")
    try:
        monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", a["id"])
        res_a = await cliente.post(BASE, json={"chatId": novo_chat_id(), "mensagem": "relato A"}, headers=auth)
        monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", b["id"])
        res_b = await cliente.post(BASE, json={"chatId": novo_chat_id(), "mensagem": "relato B"}, headers=auth)
        assert res_a.json()["flowId"] == a["id"]
        assert res_b.json()["flowId"] == b["id"]
        assert res_a.json()["status"] == "concluido"
        assert res_b.json()["status"] == "concluido"
        get_a = await cliente.get(f"/atendimentos/{res_a.json()['_links']['self']['href'].rsplit('/', 1)[1]}", headers=auth)
        get_b = await cliente.get(f"/atendimentos/{res_b.json()['_links']['self']['href'].rsplit('/', 1)[1]}", headers=auth)
        assert get_a.json()["flowId"] == a["id"], "o GET do chatId A não vaza o flowId de B"
        assert get_b.json()["flowId"] == b["id"], "o GET do chatId B não vaza o flowId de A"
    finally:
        await remover_planejado_de_teste(a["id"])
        await remover_planejado_de_teste(b["id"])


async def test_identifica_pessoa_presa_cria_atendimento_com_flow_id(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PESSOA_PRESA)
    chat_id = novo_chat_id()
    r = await cliente.post(BASE, json={"chatId": chat_id, "mensagem": "meu marido foi preso, queria saber do processo dele"}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "em_andamento"
    assert corpo["flowId"] == ID_PESSOA_PRESA
    assert "número do processo" in corpo["resposta"]
    # Dali em diante é o mesmo atendimento: o GET resolve pela tabela chatId→flowId.
    get = await cliente.get(f"/atendimentos/{chat_id}", headers=auth)
    assert get.status_code == 200
    assert get.json()["resposta"] == corpo["resposta"]


async def test_chat_id_de_outro_flow_id_409(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    chat_id = novo_chat_id()
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_PESSOA_PRESA}, headers=auth)
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_VIOLENCIA_DOMESTICA)
    r = await cliente.post(BASE, json={"chatId": chat_id, "mensagem": "sou vítima de violência doméstica"}, headers=auth)
    assert r.status_code == 409


async def test_relato_ambiguo_pergunta_e_resposta_resolve(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", f"{ID_PESSOA_PRESA},{ID_VIOLENCIA_DOMESTICA}")
    chat_id = novo_chat_id()
    r1 = await cliente.post(BASE, json={"chatId": chat_id, "mensagem": "relato que bate com 2 fluxos"}, headers=auth)
    c1 = r1.json()
    assert r1.status_code == 200
    assert c1["status"] == "em_andamento"
    assert "flowId" not in c1, "não deveria ter flowId enquanto ainda está desambiguando"
    assert c1["tipoResposta"] == "texto", "pergunta de desambiguação é texto livre (decisão 2026-09-11)"

    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", ID_PESSOA_PRESA)
    r2 = await cliente.post(BASE, json={"chatId": chat_id, "resposta": "pessoa-presa"}, headers=auth)
    c2 = r2.json()
    assert r2.status_code == 200
    assert c2["flowId"] == ID_PESSOA_PRESA
    assert c2["status"] == "em_andamento", "agora é o fluxo real perguntando"


def _pergunta_raiz(flow_id: str, texto: str) -> PerguntaArvore:
    return {
        "id": str(uuid.uuid4()),
        "flowId": flow_id,
        "idItemCategoria": None,
        "veioDaRespostaId": None,
        "textoPergunta": texto,
        "tipo": "sim_nao",
        "opcoes": [{"id": 1, "resposta": "SIM"}, {"id": 2, "resposta": "NÃO"}],
        "ordem": 0,
    }


@pytest.mark.parametrize(
    ("texto_pp", "texto_vd", "esperado"),
    [
        ("JÁ TEM PROCESSO JUDICIAL?", "JÁ TEM PROCESSO JUDICIAL?", "JÁ TEM PROCESSO JUDICIAL?"),  # idêntica: usa o banco
        ("pergunta A", "pergunta B", "qual dessas opções descreve"),  # diferente: IA (fallback)
        ("só pessoa presa tem essa pergunta", None, "qual dessas opções descreve"),  # só 1 tem: IA
    ],
    ids=["identica_usa_o_banco", "diferente_cai_na_ia", "so_um_tem_cai_na_ia"],
)
async def test_desambiguacao_com_pergunta_raiz(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, texto_pp: str, texto_vd: str | None, esperado: str
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", f"{ID_PESSOA_PRESA},{ID_VIOLENCIA_DOMESTICA}")
    store = await obter_perguntas_store()
    await store.inserir_pergunta(_pergunta_raiz(ID_PESSOA_PRESA, texto_pp))
    if texto_vd is not None:
        await store.inserir_pergunta(_pergunta_raiz(ID_VIOLENCIA_DOMESTICA, texto_vd))
    try:
        r = await cliente.post(BASE, json={"chatId": novo_chat_id(), "mensagem": "relato ambíguo"}, headers=auth)
        assert esperado.lower() in r.json()["resposta"].lower()
    finally:
        await store.limpar_flow(ID_PESSOA_PRESA)
        await store.limpar_flow(ID_VIOLENCIA_DOMESTICA)


async def test_ambiguidade_que_nunca_resolve_vira_outros(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", f"{ID_PESSOA_PRESA},{ID_VIOLENCIA_DOMESTICA}")
    chat_id = novo_chat_id()
    r = await cliente.post(BASE, json={"chatId": chat_id, "mensagem": "relato sempre ambíguo"}, headers=auth)
    assert r.json()["status"] == "em_andamento", "pergunta 1"
    for numero in range(2, 6):
        r = await cliente.post(BASE, json={"chatId": chat_id, "resposta": "não esclarece"}, headers=auth)
        assert r.json()["status"] == "em_andamento", f"pergunta {numero}"
    r = await cliente.post(BASE, json={"chatId": chat_id, "resposta": "não esclarece"}, headers=auth)
    corpo = r.json()
    assert corpo["status"] == "redirecionado", "esgotou as 5 rodadas, ainda ambíguo: desiste"
    assert corpo["tipoCaso"] == "outros"


@pytest.mark.parametrize("tipo", TIPOS_TYKHE, ids=[t.tipo_caso for t in TIPOS_TYKHE])
async def test_tipo_da_tykhe_redireciona_sem_criar_atendimento(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, tipo: TipoTykhe
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", tipo.id)
    chat_id = novo_chat_id()
    r = await cliente.post(BASE, json={"chatId": chat_id, "mensagem": "relato qualquer"}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "redirecionado"
    assert corpo["tipoCaso"] == tipo.tipo_caso
    assert corpo["resposta"] == tipo.mensagem
    assert "flowId" not in corpo
    assert "metadados" not in corpo
    assert "responder" not in corpo["_links"], "nada a responder na Maria depois de redirecionar"
    assert corpo["tokensGastos"], "tokensGastos sempre presente"
    get = await cliente.get(f"/atendimentos/{chat_id}", headers=auth)
    assert get.status_code == 404, "nenhum atendimento é criado na Maria"


async def test_catalogo_com_2_implementados_e_7_tipos_da_tykhe() -> None:
    ids = [c["id"] for c in await catalogo_para_classificacao()]
    assert len(ids) == 9
    assert ID_PESSOA_PRESA in ids and ID_VIOLENCIA_DOMESTICA in ids
    assert all(t.id in ids for t in TIPOS_TYKHE)


async def test_variavel_true_devolve_os_planejados(monkeypatch: pytest.MonkeyPatch) -> None:
    fluxo = _planejado("00000000-0000-0000-0000-0000000000c3", "planejado-c", 88883)
    await adicionar_planejado_de_teste(fluxo)
    monkeypatch.setenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", "true")
    try:
        assert fluxo["id"] in [c["id"] for c in await catalogo_para_classificacao()]
    finally:
        await remover_planejado_de_teste(fluxo["id"])


async def test_via_orquestrador_cpf_encontrado_pergunta_confirmacao_189_191(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Quem entra pelo orquestrador ganha a confirmação de dados (#189); quem chama
    # POST /atendimentos direto (a Tykhe) não. Mesmo CPF, mesmo mock.
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_VIOLENCIA_DOMESTICA)
    monkeypatch.delenv("MOCK_CLASSIFICACAO_FLOWIDS", raising=False)
    chat_id = novo_chat_id()
    await cliente.post(BASE, json={"chatId": chat_id, "mensagem": "sou vítima de violência doméstica"}, headers=auth)

    async def responder(resposta: str) -> httpx.Response:
        return await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": resposta}, headers=auth)

    await responder("true")  # é vítima
    await responder("false")  # sem processo
    r_cpf = await responder("true")  # tem RO; sem CPF pré-preenchido: pergunta
    assert "Qual o seu CPF" in r_cpf.json()["resposta"]
    r_confirma = await responder("11111111111")
    assert "Confirma que seus dados são" in r_confirma.json()["resposta"], "via orquestrador pergunta a confirmação"
    r = await responder("sim")
    assert r.json()["status"] == "concluido"


async def test_fluxo_nao_oferecido_nao_entra_no_catalogo_do_orquestrador() -> None:
    # #329: o fluxo do NUDECON já está registrado (GET /fluxos), mas só é oferecido com a #266.
    assert ID_PROBLEMAS_PLANO_SAUDE not in [c["id"] for c in await catalogo_para_classificacao()]
