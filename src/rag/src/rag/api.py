"""API local de demonstração para recuperação e explicação da API Verde."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .catalogo import CandidatoCatalogo
from .chain import ExplicadorVerde
from .embeddings import criar_modelo_embeddings
from .recuperador_catalogo import LIMITE_CANDIDATOS, RecuperadorCatalogo
from .retriever import RecuperadorVerde
from .settings import carregar_configuracoes
from .vector_store import ArmazenamentoVetorial

armazenamento = ArmazenamentoVetorial(carregar_configuracoes().database_url)
recuperador: RecuperadorVerde | None = None
explicador: ExplicadorVerde | None = None
recuperador_catalogo: RecuperadorCatalogo | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global recuperador, explicador, recuperador_catalogo
    armazenamento.abrir()
    modelo_embeddings = criar_modelo_embeddings()
    recuperador = RecuperadorVerde(armazenamento, modelo_embeddings)
    recuperador_catalogo = RecuperadorCatalogo(armazenamento, modelo_embeddings)
    explicador = ExplicadorVerde(recuperador)
    yield
    armazenamento.fechar()


app = FastAPI(title="RAG da API Verde", version="0.2.0", lifespan=lifespan)


class BuscaRequest(BaseModel):
    consulta: str = Field(min_length=1, max_length=4000)
    limite: int = Field(default=3, ge=1, le=10)


class ExplicarRequest(BaseModel):
    mensagem: str = Field(min_length=1, max_length=4000)
    endpoint: str = Field(default="", max_length=500)
    metodo: str = Field(default="", max_length=12)
    status_http: int | None = Field(default=None, ge=100, le=599)


class CandidatoRequest(BaseModel):
    id: str = Field(min_length=1, max_length=250)
    nome: str = Field(min_length=1, max_length=500)
    descricao: str = Field(min_length=1, max_length=10000)
    palavras_chave: list[str] = Field(default_factory=list, max_length=100)
    dados: dict[str, Any] = Field(default_factory=dict)


class IndexarCatalogoRequest(BaseModel):
    candidatos: list[CandidatoRequest] = Field(min_length=1, max_length=500)
    sincronizar_completo: bool = Field(
        default=True,
        description="Envie o catálogo inteiro quando true; false apenas adiciona ou atualiza os IDs recebidos.",
    )


class BuscaCatalogoRequest(BaseModel):
    relato: str = Field(min_length=1, max_length=4000)
    limite: int = Field(default=LIMITE_CANDIDATOS, ge=1, le=LIMITE_CANDIDATOS)
    busca_hibrida: bool | None = Field(
        default=None,
        description="Sem valor, usa ORQUESTRADOR_BUSCA_HIBRIDA (exatamente 'true' ativa). Permite comparar modos na avaliação.",
    )
    candidatos: list[CandidatoRequest] | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Snapshot atual do catálogo; quando presente, é sincronizado antes da busca.",
    )
    sincronizar_completo: bool = True


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        total = armazenamento.contar()
        candidatos = armazenamento.contar_candidatos()
    except Exception as erro:
        raise HTTPException(status_code=503, detail=f"Banco pgvector indisponível: {erro}") from erro
    return {"status": "ok", "documentos_indexados": total, "candidatos_orquestrador": candidatos}


@app.post("/api/index")
def indexar() -> dict[str, int]:
    if recuperador is None:
        raise HTTPException(status_code=503, detail="RAG ainda não inicializado.")
    try:
        return recuperador.indexar()
    except Exception as erro:
        raise HTTPException(status_code=500, detail=f"Falha ao indexar documentos: {erro}") from erro


@app.post("/api/search")
def buscar(pedido: BuscaRequest) -> dict[str, Any]:
    if recuperador is None:
        raise HTTPException(status_code=503, detail="RAG ainda não inicializado.")
    try:
        return {"resultados": recuperador.buscar(pedido.consulta, pedido.limite)}
    except Exception as erro:
        raise HTTPException(status_code=500, detail=f"Falha na busca: {erro}") from erro


@app.post("/api/explain")
def explicar(pedido: ExplicarRequest) -> dict[str, Any]:
    if explicador is None:
        raise HTTPException(status_code=503, detail="RAG ainda não inicializado.")
    try:
        return explicador.explicar(pedido.mensagem, pedido.endpoint, pedido.metodo, pedido.status_http)
    except Exception as erro:
        raise HTTPException(status_code=500, detail=f"Falha ao explicar a mensagem: {erro}") from erro


@app.post("/api/catalog/index")
def indexar_catalogo(pedido: IndexarCatalogoRequest) -> dict[str, int]:
    if recuperador_catalogo is None:
        raise HTTPException(status_code=503, detail="RAG ainda não inicializado.")
    candidatos = [
        CandidatoCatalogo(
            id=candidato.id,
            nome=candidato.nome,
            descricao=candidato.descricao,
            palavras_chave=tuple(candidato.palavras_chave),
            dados=candidato.dados,
        )
        for candidato in pedido.candidatos
    ]
    try:
        return recuperador_catalogo.indexar(candidatos, sincronizar_completo=pedido.sincronizar_completo)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except Exception as erro:
        raise HTTPException(status_code=500, detail=f"Falha ao indexar catálogo do orquestrador: {erro}") from erro


@app.post("/api/catalog/search")
def buscar_catalogo(pedido: BuscaCatalogoRequest) -> dict[str, Any]:
    if recuperador_catalogo is None:
        raise HTTPException(status_code=503, detail="RAG ainda não inicializado.")
    try:
        resposta: dict[str, Any] = {}
        if pedido.candidatos is not None:
            candidatos = [
                CandidatoCatalogo(
                    id=candidato.id,
                    nome=candidato.nome,
                    descricao=candidato.descricao,
                    palavras_chave=tuple(candidato.palavras_chave),
                    dados=candidato.dados,
                )
                for candidato in pedido.candidatos
            ]
            resposta["indexacao"] = recuperador_catalogo.indexar(candidatos, sincronizar_completo=pedido.sincronizar_completo)
        resposta.update(recuperador_catalogo.buscar(pedido.relato, pedido.limite, pedido.busca_hibrida))
        return resposta
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except Exception as erro:
        raise HTTPException(status_code=500, detail=f"Falha na recuperação do catálogo: {erro}") from erro
