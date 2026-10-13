"""Catálogo de fluxos planejados: testes novos da spec do módulo persistencia (10)
e dos auxiliares de teste."""

import re

import psycopg
import pytest
from psycopg.rows import TupleRow

from maria.shared.fluxos_planejados_db import (
    FluxoPlanejado,
    adicionar_planejado_de_teste,
    buscar_fluxo_planejado_por_id,
    listar_fluxos_planejados,
    remover_planejado_de_teste,
    texto_para_classificacao,
)

pytestmark = pytest.mark.usefixtures("stores_limpas")


def planejado(id: str, **sobrescritas: object) -> FluxoPlanejado:
    base: dict[str, object] = {"id": id, "nome": "Nome", "descricao": "Descrição.", "idCategoriaAssuntoVerde": 1, "palavrasChave": []}
    base.update(sobrescritas)
    return base  # type: ignore[return-value]


def test_texto_para_classificacao() -> None:
    assert texto_para_classificacao(planejado("a")) == "Descrição."
    assert texto_para_classificacao(planejado("a", palavrasChave=["pensão", "filho"])) == "Descrição. Palavras-chave: pensão, filho."


async def test_memoria_auxiliares_de_teste_e_ordem_de_insercao(monkeypatch: pytest.MonkeyPatch) -> None:
    # Divergência mantida: a memória lista na ordem de inserção; o Postgres, por id.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    await adicionar_planejado_de_teste(planejado("b"))
    await adicionar_planejado_de_teste(planejado("a"))
    assert [f["id"] for f in await listar_fluxos_planejados()] == ["b", "a"]
    encontrado = await buscar_fluxo_planejado_por_id("a")
    assert encontrado is not None
    assert encontrado["id"] == "a"
    await remover_planejado_de_teste("b")
    assert [f["id"] for f in await listar_fluxos_planejados()] == ["a"]
    assert await buscar_fluxo_planejado_por_id("inexistente") is None


async def test_auxiliares_de_teste_recusam_store_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    from maria.shared import fluxos_planejados_db

    class _PoolQueNaoAbre:
        async def open(self) -> None:
            raise OSError("sem banco neste teste")

        async def close(self) -> None:
            return None

    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario@host-falso/banco")
    monkeypatch.setattr(fluxos_planejados_db, "criar_pool", lambda _url: _PoolQueNaoAbre())
    with pytest.raises(RuntimeError, match=f"^{re.escape('adicionarPlanejadoDeTeste só funciona sem DATABASE_URL')}$"):
        await adicionar_planejado_de_teste(planejado("x"))
    with pytest.raises(RuntimeError, match=f"^{re.escape('removerPlanejadoDeTeste só funciona sem DATABASE_URL')}$"):
        await remover_planejado_de_teste("x")


@pytest.mark.postgres
async def test_postgres_mensagem_fixa_nula_omite_a_chave(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Spec, teste 10.
    await listar_fluxos_planejados()  # cria o esquema
    await banco_de_negocio.execute(
        """INSERT INTO fluxos_planejados (id, nome, descricao, id_categoria_assunto_verde, palavras_chave, mensagem_fixa)
           VALUES ('z-com', 'Com', 'D', 1, ARRAY['a','b'], 'Procure o sindicato.'), ('a-sem', 'Sem', 'D', 2, '{}', NULL)"""
    )
    lista = await listar_fluxos_planejados()
    assert [f["id"] for f in lista] == ["a-sem", "z-com"]  # ORDER BY id
    sem, com = lista
    assert "mensagemFixa" not in sem
    assert com["mensagemFixa"] == "Procure o sindicato."
    assert com["palavrasChave"] == ["a", "b"]
    assert (await buscar_fluxo_planejado_por_id("a-sem")) == sem
