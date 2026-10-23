"""Tradução de `src/shared/embeddingsFluxos.test.ts` (4 testes, BDD da issue #8),
mais os novos 6, 7, 8, 9 e 13 da spec do módulo persistencia.

APP_ENV=test nunca chama o Bedrock (embedding falso) e, sem DATABASE_URL, a
busca é em memória, como em develop.
"""

import psycopg
import pytest
from psycopg.rows import TupleRow

from maria.shared import embeddings_fluxos
from maria.shared.embeddings_fluxos import FluxoParaIndexar, aquecer_catalogo, buscar_candidatos, embedding_falso

pytestmark = pytest.mark.usefixtures("stores_limpas")


def catalogo(n: int) -> list[FluxoParaIndexar]:
    return [
        {"id": f"fluxo-{i}", "nome": f"Fluxo {i}", "descricao": f"Descrição do fluxo número {i}, usado só pra teste de retrieval."}
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _sem_banco(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("postgres") is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)


async def test_poucos_fluxos_devolve_o_catalogo_inteiro() -> None:
    c = catalogo(2)
    candidatos = await buscar_candidatos("relato qualquer", 10, c)
    assert len(candidatos) == 2
    assert candidatos == c


async def test_muitos_fluxos_so_os_k_mais_similares() -> None:
    c = catalogo(80)
    candidatos = await buscar_candidatos("relato qualquer", 10, c)
    assert len(candidatos) == 10
    ids = {f["id"] for f in c}
    for candidato in candidatos:
        assert candidato["id"] in ids, f"{candidato['id']} deveria vir do catálogo original"


async def test_exatamente_k_fluxos_nao_corta() -> None:
    candidatos = await buscar_candidatos("relato qualquer", 10, catalogo(10))
    assert len(candidatos) == 10


async def test_resultado_consistente_para_a_mesma_mensagem() -> None:
    c = catalogo(80)
    r1 = await buscar_candidatos("mesma mensagem sempre", 10, c)
    r2 = await buscar_candidatos("mesma mensagem sempre", 10, c)
    assert sorted(f["id"] for f in r1) == sorted(f["id"] for f in r2)


# --- Novos -------------------------------------------------------------------


def test_embedding_falso_soma_code_units_utf16_como_develop() -> None:
    # Spec, teste 7. Referência calculada com o charCodeAt do JS (develop). O emoji
    # conta como 2 code units; com ord() (code points), o vetor seria outro.
    texto = "meu filho \U0001f44b foi preso — ção"
    assert embedding_falso(texto) == [141, 213, 231, 133, 217, 216, 140, 8316, 143, 263, 55584, 56506, 32, 102, 111, 105]


async def test_ate_k_fluxos_devolve_na_ordem_sem_gerar_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    # Spec, teste 8.
    async def proibido(_texto: str) -> list[int]:
        raise AssertionError("não deveria gerar embedding com o catálogo de até k fluxos")

    monkeypatch.setattr(embeddings_fluxos, "gerar_embedding", proibido)
    c = list(reversed(catalogo(5)))
    assert await buscar_candidatos("qualquer", 5, c) == c


async def test_empate_de_similaridade_mantem_a_ordem_do_catalogo() -> None:
    # Spec, teste 9: mesma descrição dá o mesmo vetor e a mesma similaridade; a
    # ordenação é estável, como o sort de JS.
    c: list[FluxoParaIndexar] = [{"id": f"igual-{i}", "nome": "x", "descricao": "texto idêntico"} for i in range(12)]
    candidatos = await buscar_candidatos("qualquer relato", 10, c)
    assert [f["id"] for f in candidatos] == [f"igual-{i}" for i in range(10)]


async def test_aquecer_em_memoria_nao_faz_nada() -> None:
    await aquecer_catalogo(catalogo(80))


# --- Postgres real ------------------------------------------------------------


@pytest.mark.postgres
async def test_postgres_vetor_ida_e_volta_pelo_cast_manual(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 6: o Python escreve 1e-07 onde o JS escreve 1e-7; o pgvector aceita
    # os dois e guarda o mesmo valor.
    await banco_de_negocio.execute("CREATE EXTENSION IF NOT EXISTS vector")
    literal = embeddings_fluxos._literal_vector([1, 0.5, 1e-7, -2.25])
    assert literal == "[1,0.5,1e-07,-2.25]"
    cursor = await banco_de_negocio.execute("SELECT %s::vector::text, '[1,0.5,1e-7,-2.25]'::vector::text", (literal,))
    linha = await cursor.fetchone()
    assert linha is not None
    assert linha[0] == linha[1]


def _vetor_1024(texto: str) -> list[float]:
    base = embedding_falso(texto)
    return [float(base[i % 16]) for i in range(embeddings_fluxos.DIMENSOES)]


@pytest.mark.postgres
async def test_postgres_indexacao_que_falha_e_refeita_na_chamada_seguinte(
    banco_de_negocio: psycopg.AsyncConnection[TupleRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec, teste 13: memoização com reinício (embeddingsFluxos.ts:152-160). Só a
    # variante Postgres indexa; o embedding falso de 16 posições não cabe em vector(1024).
    chamadas = {"n": 0}

    async def embedding(texto: str) -> list[float]:
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("throttling simulado")
        return _vetor_1024(texto)

    monkeypatch.setattr(embeddings_fluxos, "gerar_embedding", embedding)
    c = catalogo(3)
    with pytest.raises(RuntimeError, match="throttling simulado"):
        await aquecer_catalogo(c)
    await aquecer_catalogo(c)
    cursor = await banco_de_negocio.execute("SELECT count(*) FROM fluxo_embeddings")
    assert (await cursor.fetchone() or (0,))[0] == 3


@pytest.mark.postgres
async def test_postgres_busca_devolve_os_k_mais_proximos(
    banco_de_negocio: psycopg.AsyncConnection[TupleRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def embedding(texto: str) -> list[float]:
        return _vetor_1024(texto)

    monkeypatch.setattr(embeddings_fluxos, "gerar_embedding", embedding)
    c = catalogo(15)
    candidatos = await buscar_candidatos("Descrição do fluxo número 3, usado só pra teste de retrieval.", 5, c)
    assert len(candidatos) == 5
    assert candidatos[0]["id"] == "fluxo-3"
    assert set(candidatos[0]) == {"id", "nome", "descricao"}
