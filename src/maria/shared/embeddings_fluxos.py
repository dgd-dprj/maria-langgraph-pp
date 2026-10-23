"""Corte de candidatos por similaridade de embeddings, antes da classificação por IA (issue #8).

Com poucos fluxos (≤ k), devolve o catálogo inteiro sem gastar embedding.
Acima disso, devolve os k mais próximos do relato.

Sem DATABASE_URL (testes), a busca é em memória, com cosseno calculado aqui.
Com DATABASE_URL, os vetores ficam em pgvector (`fluxo_embeddings`).
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections.abc import Sequence
from typing import Protocol, TypedDict

from botocore.exceptions import ClientError
from langchain_aws import BedrockEmbeddings

from maria.shared.bedrock import CONFIG_BOTOCORE, chamar_como_async_caller, cota_como_sdk_js
from maria.shared.logger import logger
from maria.shared.pool import PoolAsync, criar_pool


class FluxoParaIndexar(TypedDict):
    id: str
    nome: str
    descricao: str


class _BuscaFluxos(Protocol):
    async def buscar_candidatos(self, mensagem: str, k: int, catalogo: Sequence[FluxoParaIndexar]) -> list[FluxoParaIndexar]: ...


# Titan Embed Text v2.
DIMENSOES = 1024
# Issue #180: indexação em lotes concorrentes.
CONCORRENCIA = 10


def _cliente_embeddings() -> BedrockEmbeddings:
    # Um cliente por chamada, com o ambiente lido na hora, como develop
    # (embeddingsFluxos.ts:26-31). A cota de retentativas é por cliente, como
    # no SDK JS: cada chamada começa com 500 fichas.
    with cota_como_sdk_js():
        return BedrockEmbeddings(
            model_id=os.environ.get("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            config=CONFIG_BOTOCORE,
        )


class ErroEmbeddingBedrock(Exception):
    """O `new Error(...)` com que o `_embedText` de develop reembrulha o erro do SDK."""


def _mensagem_do_sdk(erro: Exception) -> str:
    # O `e.message` de uma exceção do SDK JS é a mensagem do Bedrock, sem o
    # prefixo que o botocore põe em str(ClientError).
    if isinstance(erro, ClientError):
        return str(erro.response.get("Error", {}).get("Message", ""))
    return str(erro)


async def _embed_query_como_develop(cliente: BedrockEmbeddings, texto: str) -> list[float]:
    """Reproduz `embedQuery` do @langchain/aws 1.4.4: DUAS camadas de AsyncCaller.

    O `embedQuery` chama o caller (embeddings.js:108), e o `_embedText` chama de
    novo (:73). Com o Bedrock falhando sempre: 7 × 7 = 49 chamadas ao SDK, cada
    uma com até 3 tentativas do botocore, e de 8 a 17 minutos até desistir (medido em develop: 12,6 a 13,4; no Python, 12,5 a 14,7).
    Ninguém escolheu esse número: é defeito de develop reproduzido de propósito,
    registrado na #222. Não "corrija" aqui.
    """

    async def _embed_text() -> list[float]:
        async def tentativa() -> list[float]:
            try:
                return await cliente.aembed_query(texto)
            except Exception as erro:
                # develop faz console.error({ error: e }) aqui; o equivalente é o
                # logger.exception do próprio langchain_aws (ver o MIGRACAO.md).
                raise ErroEmbeddingBedrock(f"An error occurred while embedding documents with Bedrock: {_mensagem_do_sdk(erro)}") from erro

        return await chamar_como_async_caller(tentativa)

    return await chamar_como_async_caller(_embed_text)


def embedding_falso(texto: str) -> list[int]:
    """Vetor determinístico para APP_ENV=test (nunca chama o Bedrock).

    Soma os code units UTF-16 em 16 posições, como o `charCodeAt` de develop
    (embeddingsFluxos.ts:39-44). Em Python, `ord()` itera code points, e um
    caractere fora do BMP (um emoji, por exemplo) conta como 1 em vez de 2: a ordem
    dos candidatos mudaria. Decisão da spec do módulo persistencia.
    """
    tamanho = 16
    vetor = [0] * tamanho
    bruto = texto.encode("utf-16-le", errors="surrogatepass")
    for i in range(len(bruto) // 2):
        vetor[i % tamanho] += int.from_bytes(bruto[2 * i : 2 * i + 2], "little")
    return vetor


async def gerar_embedding(texto: str) -> list[float] | list[int]:
    if os.environ.get("APP_ENV") == "test":
        return embedding_falso(texto)
    # O BedrockEmbeddings do JS troca "\n" por espaço; o do Python troca
    # os.linesep, que no Windows é "\r\n". A troca explícita não depende do SO.
    return await _embed_query_como_develop(_cliente_embeddings(), texto.replace("\n", " "))


def similaridade_cosseno(a: Sequence[float], b: Sequence[float]) -> float:
    produto = norma_a = norma_b = 0.0
    for x, y in zip(a, b, strict=False):
        produto += x * y
        norma_a += x * x
        norma_b += y * y
    if norma_a == 0 or norma_b == 0:
        return 0.0
    return produto / (math.sqrt(norma_a) * math.sqrt(norma_b))


class _BuscaEmMemoria:
    def __init__(self) -> None:
        # Cache por id do fluxo (e não pela descrição), como develop.
        self._cache: dict[str, list[float] | list[int]] = {}

    async def _embedding_cacheado(self, chave: str, texto: str) -> list[float] | list[int]:
        vetor = self._cache.get(chave)
        if vetor is None:
            vetor = await gerar_embedding(texto)
            self._cache[chave] = vetor
        return vetor

    async def buscar_candidatos(self, mensagem: str, k: int, catalogo: Sequence[FluxoParaIndexar]) -> list[FluxoParaIndexar]:
        if len(catalogo) <= k:
            return list(catalogo)
        embedding_mensagem = await gerar_embedding(mensagem)
        vetores = await asyncio.gather(*(self._embedding_cacheado(f["id"], f["descricao"]) for f in catalogo))
        com_similaridade = [(f, similaridade_cosseno(embedding_mensagem, v)) for f, v in zip(catalogo, vetores, strict=True)]
        # sorted é estável, como o sort de JS: empates mantêm a ordem do catálogo.
        com_similaridade = sorted(com_similaridade, key=lambda par: par[1], reverse=True)
        return [f for f, _ in com_similaridade[:k]]


def _literal_vector(vetor: Sequence[float]) -> str:
    # Vetor como texto '[v1,v2,...]' com cast ::vector, sem a dependência pgvector,
    # como develop. O Python escreve 1e-07 onde o JS escreve 1e-7; o pgvector
    # aceita os dois e guarda o mesmo valor.
    return "[" + ",".join(str(v) for v in vetor) + "]"


class _BuscaPostgres:
    def __init__(self, pool: PoolAsync) -> None:
        self._pool = pool
        self._pronto: asyncio.Task[None] = asyncio.ensure_future(self._preparar())
        self._indexado: asyncio.Task[None] | None = None

    async def _preparar(self) -> None:
        await self._pool.open()
        async with self._pool.connection() as conexao:
            await conexao.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conexao.execute(
                f"""
      CREATE TABLE IF NOT EXISTS fluxo_embeddings (
        id TEXT PRIMARY KEY,
        nome TEXT NOT NULL,
        descricao TEXT NOT NULL,
        embedding vector({DIMENSOES}) NOT NULL
      )
    """
            )
        logger.info("[embeddingsFluxos] tabela 'fluxo_embeddings' pronta (pgvector)")

    async def _indexar_um(self, f: FluxoParaIndexar) -> None:
        vetor = await gerar_embedding(f["descricao"])
        async with self._pool.connection() as conexao:
            await conexao.execute(
                """INSERT INTO fluxo_embeddings (id, nome, descricao, embedding)
             VALUES (%(id)s, %(nome)s, %(descricao)s, %(embedding)s::vector)
             ON CONFLICT (id) DO UPDATE SET nome = %(nome)s, descricao = %(descricao)s, embedding = %(embedding)s::vector""",
                {"id": f["id"], "nome": f["nome"], "descricao": f["descricao"], "embedding": _literal_vector(vetor)},
            )

    async def _indexar(self, catalogo: Sequence[FluxoParaIndexar]) -> None:
        await self._pronto
        for inicio in range(0, len(catalogo), CONCORRENCIA):
            await asyncio.gather(*(self._indexar_um(f) for f in catalogo[inicio : inicio + CONCORRENCIA]))
        logger.info("[embeddingsFluxos] catálogo (re)indexado", total=len(catalogo))

    def _esquecer_se_falhou(self, tarefa: asyncio.Task[None]) -> None:
        # Se a indexação falhar (ex.: throttling do Bedrock), a memoização é
        # desfeita e a próxima chamada tenta de novo (embeddingsFluxos.ts:152-160).
        if tarefa.cancelled() or tarefa.exception() is not None:
            self._indexado = None

    async def garantir_indexado(self, catalogo: Sequence[FluxoParaIndexar]) -> None:
        """Uma indexação por processo; chamadas concorrentes reaproveitam a mesma."""
        if self._indexado is None:
            self._indexado = asyncio.ensure_future(self._indexar(catalogo))
            self._indexado.add_done_callback(self._esquecer_se_falhou)
        await self._indexado

    async def buscar_candidatos(self, mensagem: str, k: int, catalogo: Sequence[FluxoParaIndexar]) -> list[FluxoParaIndexar]:
        if len(catalogo) <= k:
            return list(catalogo)
        await self.garantir_indexado(catalogo)
        embedding_mensagem = _literal_vector(await gerar_embedding(mensagem))
        inicio = time.monotonic()
        async with self._pool.connection() as conexao:
            linhas = await (
                await conexao.execute(
                    """SELECT id, nome, descricao FROM fluxo_embeddings
         WHERE id = ANY(%(ids)s)
         ORDER BY embedding <=> %(embedding)s::vector
         LIMIT %(k)s""",
                    {"embedding": embedding_mensagem, "ids": [f["id"] for f in catalogo], "k": k},
                )
            ).fetchall()
        logger.info(
            "[embeddingsFluxos] busca por similaridade concluída",
            candidatos=len(linhas),
            tempoMs=round((time.monotonic() - inicio) * 1000),
        )
        return [{"id": linha["id"], "nome": linha["nome"], "descricao": linha["descricao"]} for linha in linhas]


_busca: _BuscaEmMemoria | _BuscaPostgres | None = None
_pool: PoolAsync | None = None


async def _obter_busca() -> _BuscaEmMemoria | _BuscaPostgres:
    global _busca, _pool
    if _busca is None:
        url = os.environ.get("DATABASE_URL")
        if url:
            _pool = criar_pool(url)
            _busca = _BuscaPostgres(_pool)
        else:
            _busca = _BuscaEmMemoria()
    return _busca


async def buscar_candidatos(mensagem: str, k: int, catalogo: Sequence[FluxoParaIndexar]) -> list[FluxoParaIndexar]:
    return await (await _obter_busca()).buscar_candidatos(mensagem, k, catalogo)


async def aquecer_catalogo(catalogo: Sequence[FluxoParaIndexar]) -> None:
    """Issue #180: indexa no boot, sem esperar a primeira busca. Só a variante
    Postgres faz algo; a em memória não tem aquecimento."""
    busca = await _obter_busca()
    if isinstance(busca, _BuscaPostgres):
        await busca.garantir_indexado(catalogo)


async def fechar_busca_fluxos() -> None:
    """Fecha o pool e zera a memoização (lifespan e testes; ver a spec)."""
    global _busca, _pool
    if isinstance(_busca, _BuscaPostgres):
        pendentes = [t for t in (_busca._pronto, _busca._indexado) if t is not None]
        await asyncio.gather(*pendentes, return_exceptions=True)
    if _pool is not None:
        await _pool.close()
    _busca = None
    _pool = None
