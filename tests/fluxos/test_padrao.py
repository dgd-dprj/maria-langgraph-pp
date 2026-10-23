"""Tradução de `fluxos/padrao/graph.test.ts` (develop @ 0aecd98): 3 testes.

Sem `DATABASE_URL`, `adicionar_planejado_de_teste` simula uma linha da tabela
`fluxos_planejados` sem tocar dado de produção, como em develop.
"""

from maria.fluxos.padrao.api import MENSAGEM_CONCLUIDO
from maria.fluxos.padrao.graph import obter_grafo
from maria.shared.fluxos_planejados_db import adicionar_planejado_de_teste, remover_planejado_de_teste
from tests.fluxos.conftest import novo_config


async def test_categoria_sem_mensagem_fixa_usa_mensagem_generica() -> None:
    fluxo_id = "00000000-0000-0000-0000-0000000000a1"
    await adicionar_planejado_de_teste(
        {"id": fluxo_id, "nome": "categoria-teste", "descricao": "teste", "idCategoriaAssuntoVerde": 88888, "palavrasChave": []}
    )
    try:
        r = await obter_grafo().ainvoke({}, novo_config("teste-padrao", fluxoId=fluxo_id))
        assert r["statusFinal"] == "concluido"
        assert r["mensagemFinal"] == MENSAGEM_CONCLUIDO
    finally:
        await remover_planejado_de_teste(fluxo_id)


async def test_categoria_com_mensagem_fixa_usa_texto_especifico_issue_22() -> None:
    fluxo_id = "00000000-0000-0000-0000-0000000000b2"
    mensagem = "Não atuamos nesse tipo de caso — procure outro órgão."
    await adicionar_planejado_de_teste(
        {
            "id": fluxo_id,
            "nome": "categoria-redirecionamento-teste",
            "descricao": "teste",
            "idCategoriaAssuntoVerde": 88889,
            "palavrasChave": [],
            "mensagemFixa": mensagem,
        }
    )
    try:
        r = await obter_grafo().ainvoke({}, novo_config("teste-padrao", fluxoId=fluxo_id))
        assert r["statusFinal"] == "concluido", "redirecionamento permanente ainda é 'concluido'"
        assert r["mensagemFinal"] == mensagem
    finally:
        await remover_planejado_de_teste(fluxo_id)


async def test_sem_fluxo_id_no_config_cai_na_mensagem_generica() -> None:
    r = await obter_grafo().ainvoke({}, novo_config("teste-padrao"))
    assert r["mensagemFinal"] == MENSAGEM_CONCLUIDO
