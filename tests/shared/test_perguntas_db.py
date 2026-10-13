"""Tradução de `src/shared/perguntasDb.test.ts` (6 testes), mais os novos 11 e 12 da spec.

Os traduzidos rodam na store em memória (sem DATABASE_URL, como em develop) e
usam flowId próprio por teste.
"""

import uuid

import psycopg
import pytest
from psycopg.rows import TupleRow

from maria.shared.perguntas_db import AssuntoVerde, FlowAssunto, PerguntaArvore, obter_perguntas_store

pytestmark = pytest.mark.usefixtures("stores_limpas")


def pergunta(flow_id: str, **sobrescritas: object) -> PerguntaArvore:
    base: dict[str, object] = {
        "id": f"{flow_id}-pergunta-{sobrescritas.get('ordem', 0)}",
        "flowId": flow_id,
        "idItemCategoria": None,
        "veioDaRespostaId": None,
        "textoPergunta": "pergunta de teste",
        "tipo": "sim_nao",
        "opcoes": [{"id": 1, "resposta": "SIM"}, {"id": 2, "resposta": "NÃO"}],
        "ordem": 0,
    }
    base.update(sobrescritas)
    return base  # type: ignore[return-value]


def assunto(id_assunto: int, **sobrescritas: object) -> AssuntoVerde:
    base: dict[str, object] = {
        "idAssunto": id_assunto,
        "nome": "assunto de teste",
        "documentosNecessarios": [],
        "urgente": False,
        "plantao": False,
    }
    base.update(sobrescritas)
    return base  # type: ignore[return-value]


def flow_assunto(flow_id: str, id_assunto: int, **sobrescritas: object) -> FlowAssunto:
    base: dict[str, object] = {"id": str(uuid.uuid4()), "flowId": flow_id, "idAssunto": id_assunto, "veioDaRespostaId": None}
    base.update(sobrescritas)
    return base  # type: ignore[return-value]


async def test_inserir_pergunta_e_listar_devolve_so_as_do_flow_id_pedido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = await obter_perguntas_store()
    flow_id = "flow-teste-1"
    await store.inserir_pergunta(pergunta(flow_id, ordem=1, id="p1"))
    await store.inserir_pergunta(pergunta(flow_id, ordem=0, id="p0"))
    await store.inserir_pergunta(pergunta("outro-flow", id="p-outro"))

    lista = await store.listar_perguntas_por_flow(flow_id)
    assert len(lista) == 2
    assert all(p["flowId"] == flow_id for p in lista)


async def test_buscar_pergunta_raiz_devolve_so_a_de_ordem_0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = await obter_perguntas_store()
    flow_id = "flow-teste-raiz"
    await store.inserir_pergunta(pergunta(flow_id, ordem=0, id="raiz", textoPergunta="pergunta raiz"))
    await store.inserir_pergunta(pergunta(flow_id, ordem=1, id="filha", textoPergunta="pergunta filha"))

    raiz = await store.buscar_pergunta_raiz(flow_id)
    assert raiz is not None
    assert raiz["textoPergunta"] == "pergunta raiz"


async def test_buscar_pergunta_raiz_none_quando_o_flow_nao_tem_pergunta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = await obter_perguntas_store()
    assert await store.buscar_pergunta_raiz("flow-sem-pergunta-nenhuma") is None


async def test_assuntos_por_flow_devolve_so_os_do_flow_id_pedido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = await obter_perguntas_store()
    flow_id = "flow-teste-2"
    await store.inserir_assunto(assunto(111))
    await store.inserir_assunto(assunto(222, urgente=True, plantao=True))
    await store.inserir_assunto(assunto(333))
    await store.inserir_flow_assunto(flow_assunto(flow_id, 111))
    await store.inserir_flow_assunto(flow_assunto(flow_id, 222))
    await store.inserir_flow_assunto(flow_assunto("outro-flow", 333))

    lista = await store.listar_assuntos_por_flow(flow_id)
    assert len(lista) == 2
    urgente = next(a for a in lista if a["idAssunto"] == 222)
    assert urgente["urgente"] is True
    assert urgente["plantao"] is True


async def test_mesmo_id_assunto_em_dois_flows_preserva_as_duas_ligacoes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regressão do bug real do crawl completo (issue #20, 2026-09-11): o mesmo
    # idAssunto alcançado por várias categorias. A ligação flow→assunto é tabela
    # própria para que a segunda categoria não sobrescreva a primeira.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = await obter_perguntas_store()
    flow_a, flow_b, compartilhado = "flow-teste-compartilhado-a", "flow-teste-compartilhado-b", 999

    await store.inserir_assunto(assunto(compartilhado, nome="LIGAR 129"))
    await store.inserir_flow_assunto(flow_assunto(flow_a, compartilhado, veioDaRespostaId=1))
    await store.inserir_flow_assunto(flow_assunto(flow_b, compartilhado, veioDaRespostaId=2))

    lista_a = await store.listar_assuntos_por_flow(flow_a)
    lista_b = await store.listar_assuntos_por_flow(flow_b)
    assert len(lista_a) == 1, "flowA deveria continuar enxergando o assunto compartilhado"
    assert len(lista_b) == 1, "flowB deveria continuar enxergando o assunto compartilhado, sem apagar o de A"
    assert lista_a[0]["veioDaRespostaId"] == 1
    assert lista_b[0]["veioDaRespostaId"] == 2


async def test_limpar_flow_remove_so_o_flow_id_pedido_e_recrawl_nao_duplica(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = await obter_perguntas_store()
    flow_id, outro = "flow-teste-3", "flow-teste-3-intacto"

    await store.inserir_pergunta(pergunta(flow_id, id="p-antiga"))
    await store.inserir_assunto(assunto(444))
    await store.inserir_flow_assunto(flow_assunto(flow_id, 444))
    await store.inserir_pergunta(pergunta(outro, id="p-intacta"))

    await store.limpar_flow(flow_id)

    assert len(await store.listar_perguntas_por_flow(flow_id)) == 0
    assert len(await store.listar_assuntos_por_flow(flow_id)) == 0
    assert len(await store.listar_perguntas_por_flow(outro)) == 1, "flowId diferente não deveria ser afetado"

    # Simula a recoleta: insere de novo depois de limpar, sem duplicar.
    await store.inserir_pergunta(pergunta(flow_id, id="p-nova"))
    assert len(await store.listar_perguntas_por_flow(flow_id)) == 1


# --- Divergência mantida entre as stores (em memória) -------------------------


async def test_em_memoria_listar_mantem_a_ordem_de_insercao(monkeypatch: pytest.MonkeyPatch) -> None:
    # Develop (perguntasDb.ts:96-98): a memória não ordena por `ordem`; o Postgres ordena.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = await obter_perguntas_store()
    await store.inserir_pergunta(pergunta("flow-ordem", ordem=1, id="segunda"))
    await store.inserir_pergunta(pergunta("flow-ordem", ordem=0, id="primeira"))
    assert [p["id"] for p in await store.listar_perguntas_por_flow("flow-ordem")] == ["segunda", "primeira"]


# --- Postgres real ------------------------------------------------------------


@pytest.mark.postgres
async def test_postgres_pergunta_raiz_com_ids_nulos_e_chaves_presentes(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 11: develop devolve null (e não undefined) nesses dois campos.
    store = await obter_perguntas_store()
    await store.inserir_pergunta(pergunta("flow-pg-raiz", id="pg-raiz", ordem=0))
    raiz = await store.buscar_pergunta_raiz("flow-pg-raiz")
    assert raiz is not None
    assert "idItemCategoria" in raiz and raiz["idItemCategoria"] is None
    assert "veioDaRespostaId" in raiz and raiz["veioDaRespostaId"] is None
    assert raiz["opcoes"] == [{"id": 1, "resposta": "SIM"}, {"id": 2, "resposta": "NÃO"}]


@pytest.mark.postgres
async def test_postgres_upsert_de_pergunta_nao_altera_flow_id(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 12: o DO UPDATE de develop não atualiza flow_id nem os ids de origem.
    store = await obter_perguntas_store()
    await store.inserir_pergunta(pergunta("flow-original", id="mesmo-id", textoPergunta="antes"))
    await store.inserir_pergunta(pergunta("flow-outro", id="mesmo-id", textoPergunta="depois"))
    cursor = await banco_de_negocio.execute("SELECT flow_id, texto_pergunta FROM perguntas WHERE id = 'mesmo-id'")
    assert await cursor.fetchall() == [("flow-original", "depois")]


@pytest.mark.postgres
async def test_postgres_listar_ordena_por_ordem(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    store = await obter_perguntas_store()
    await store.inserir_pergunta(pergunta("flow-pg-ordem", ordem=1, id="pg-segunda"))
    await store.inserir_pergunta(pergunta("flow-pg-ordem", ordem=0, id="pg-primeira"))
    assert [p["id"] for p in await store.listar_perguntas_por_flow("flow-pg-ordem")] == ["pg-primeira", "pg-segunda"]


@pytest.mark.postgres
async def test_postgres_assunto_sem_campos_opcionais_omite_as_chaves(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    store = await obter_perguntas_store()
    await store.inserir_assunto(assunto(555))
    await store.inserir_flow_assunto(flow_assunto("flow-pg-assunto", 555))
    [item] = await store.listar_assuntos_por_flow("flow-pg-assunto")
    assert "nomeMateria" not in item and "descricao" not in item and "txDocumentosNecessarios" not in item
    assert item["veioDaRespostaId"] is None
