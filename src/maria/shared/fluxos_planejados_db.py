"""Catálogo de fluxos que a Maria RECONHECE pelo relato, mas sem grafo próprio.

Eles caem no grafo padrão. Até a issue #26, o catálogo era um array no código;
agora mora nesta tabela, editável sem deploy.

Para "ativar" um fluxo planejado: antes de implementar, consulte
`perguntas`/`assuntos_verde` pelo `id` desta linha (issue #20). Depois de
implementar e registrar o fluxo, REMOVA a linha correspondente desta tabela.

Sem DATABASE_URL (testes), a store fica em memória. Divergência entre as duas,
reproduzida de propósito porque develop é assim: `listar` ordena por `id` no
Postgres e mantém a ordem de inserção em memória.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, NotRequired, Protocol, TypedDict

from maria.shared.logger import logger
from maria.shared.pool import PoolAsync, criar_pool


class FluxoPlanejado(TypedDict):
    id: str
    nome: str
    descricao: str
    # idCategoriaAssunto do Verde (GET /integra/assunto/categorias, issue #19).
    idCategoriaAssuntoVerde: int
    # Palavras-chave curadas do Verde por categoria (ver texto_para_classificacao).
    palavrasChave: list[str]
    # Issue #22: redirecionamento PERMANENTE (ex.: "procure o sindicato"). Quando
    # presente, o grafo padrão usa este texto como mensagem final.
    mensagemFixa: NotRequired[str]


def texto_para_classificacao(f: FluxoPlanejado) -> str:
    """descricao + palavrasChave num texto só, que a IA de classificação lê."""
    if len(f["palavrasChave"]) == 0:
        return f["descricao"]
    return f"{f['descricao']} Palavras-chave: {', '.join(f['palavrasChave'])}."


class FluxosPlanejadosStore(Protocol):
    async def listar(self) -> list[FluxoPlanejado]: ...
    async def buscar_por_id(self, id: str) -> FluxoPlanejado | None: ...


class _StoreEmMemoria:
    """Os testes usam adicionar_planejado_de_teste/remover_planejado_de_teste."""

    def __init__(self) -> None:
        self._lista: list[FluxoPlanejado] = []

    async def listar(self) -> list[FluxoPlanejado]:
        # Ordem de inserção, SEM ordenar por id (a store Postgres ordena).
        return list(self._lista)

    async def buscar_por_id(self, id: str) -> FluxoPlanejado | None:
        return next((f for f in self._lista if f["id"] == id), None)

    def adicionar_de_teste(self, f: FluxoPlanejado) -> None:
        self._lista.append(f)

    def remover_de_teste(self, id: str) -> None:
        for i, f in enumerate(self._lista):
            if f["id"] == id:
                del self._lista[i]
                return


def _fluxo(linha: dict[str, Any]) -> FluxoPlanejado:
    fluxo: FluxoPlanejado = {
        "id": linha["id"],
        "nome": linha["nome"],
        "descricao": linha["descricao"],
        "idCategoriaAssuntoVerde": linha["id_categoria_assunto_verde"],
        "palavrasChave": linha["palavras_chave"],
    }
    # `mensagem_fixa ?? undefined` de develop: chave ausente quando NULL.
    if linha["mensagem_fixa"] is not None:
        fluxo["mensagemFixa"] = linha["mensagem_fixa"]
    return fluxo


class _StorePostgres:
    def __init__(self, pool: PoolAsync) -> None:
        self._pool = pool
        # Como o prontoPromise de develop: dispara na construção; se falhar,
        # toda chamada falha, sem nova tentativa.
        self._pronto: asyncio.Task[None] = asyncio.ensure_future(self._preparar())

    async def _preparar(self) -> None:
        await self._pool.open()
        async with self._pool.connection() as conexao:
            await conexao.execute(
                """
      CREATE TABLE IF NOT EXISTS fluxos_planejados (
        id TEXT PRIMARY KEY,
        nome TEXT NOT NULL,
        descricao TEXT NOT NULL,
        id_categoria_assunto_verde INTEGER NOT NULL,
        palavras_chave TEXT[] NOT NULL DEFAULT '{}'
      )
    """
            )
            # Issue #22: coluna nova numa tabela que já existe em produção.
            await conexao.execute("ALTER TABLE fluxos_planejados ADD COLUMN IF NOT EXISTS mensagem_fixa TEXT")
        logger.info("[fluxosPlanejadosDb] tabela 'fluxos_planejados' pronta (Postgres)")

    async def listar(self) -> list[FluxoPlanejado]:
        await self._pronto
        async with self._pool.connection() as conexao:
            linhas = await (
                await conexao.execute(
                    "SELECT id, nome, descricao, id_categoria_assunto_verde, palavras_chave, mensagem_fixa FROM fluxos_planejados ORDER BY id"
                )
            ).fetchall()
        return [_fluxo(linha) for linha in linhas]

    async def buscar_por_id(self, id: str) -> FluxoPlanejado | None:
        await self._pronto
        async with self._pool.connection() as conexao:
            linha = await (
                await conexao.execute(
                    "SELECT id, nome, descricao, id_categoria_assunto_verde, palavras_chave, mensagem_fixa FROM fluxos_planejados WHERE id = %s",
                    (id,),
                )
            ).fetchone()
        return _fluxo(linha) if linha else None


_store: _StoreEmMemoria | _StorePostgres | None = None
_pool: PoolAsync | None = None


async def _obter_store() -> _StoreEmMemoria | _StorePostgres:
    global _store, _pool
    if _store is None:
        url = os.environ.get("DATABASE_URL")
        if url:
            _pool = criar_pool(url)
            _store = _StorePostgres(_pool)
        else:
            _store = _StoreEmMemoria()
    return _store


async def listar_fluxos_planejados() -> list[FluxoPlanejado]:
    return await (await _obter_store()).listar()


async def buscar_fluxo_planejado_por_id(id: str) -> FluxoPlanejado | None:
    return await (await _obter_store()).buscar_por_id(id)


async def adicionar_planejado_de_teste(f: FluxoPlanejado) -> None:
    """Só funciona sem DATABASE_URL: simula um planejado sem editar dado real."""
    store = await _obter_store()
    if not isinstance(store, _StoreEmMemoria):
        # Mensagem mantida literalmente de develop.
        raise RuntimeError("adicionarPlanejadoDeTeste só funciona sem DATABASE_URL")
    store.adicionar_de_teste(f)


async def remover_planejado_de_teste(id: str) -> None:
    store = await _obter_store()
    if not isinstance(store, _StoreEmMemoria):
        raise RuntimeError("removerPlanejadoDeTeste só funciona sem DATABASE_URL")
    store.remover_de_teste(id)


async def fechar_fluxos_planejados_store() -> None:
    """Fecha o pool e zera a memoização (lifespan e testes; ver a spec)."""
    global _store, _pool
    if isinstance(_store, _StorePostgres):
        await asyncio.gather(_store._pronto, return_exceptions=True)
    if _pool is not None:
        await _pool.close()
    _store = None
    _pool = None
