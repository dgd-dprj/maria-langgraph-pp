"""API local de demonstração para recuperação e explicação da API Verde."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .catalogo import CandidatoCatalogo
from .chain import ExplicadorVerde
from .embeddings import criar_modelo_embeddings
from .progresso import RastreadorProgresso
from .recuperador_catalogo import LIMITE_CANDIDATOS, RecuperadorCatalogo
from .retriever import RecuperadorVerde
from .settings import carregar_configuracoes
from .vector_store import ArmazenamentoVetorial

armazenamento = ArmazenamentoVetorial(carregar_configuracoes().database_url)
recuperador: RecuperadorVerde | None = None
explicador: ExplicadorVerde | None = None
recuperador_catalogo: RecuperadorCatalogo | None = None
rastreador_ingest = RastreadorProgresso()


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


class StatusIngestResponse(BaseModel):
    etapa: str = Field(
        description="Etapa atual da ingestão (ex: ocioso, descoberta, carregamento, comparacao, embeddings, persistindo, concluido, erro)."
    )
    mensagem: str = Field(description="Descrição amigável do estado atual.")
    atual: int = Field(default=0, description="Quantidade de itens processados na etapa atual.")
    total: int = Field(default=0, description="Total de itens da etapa atual.")
    porcentagem: float = Field(default=0.0, description="Porcentagem de conclusão da etapa ou processo.")
    arquivo_atual: str = Field(default="", description="Nome do arquivo em processamento no momento.")
    em_andamento: bool = Field(default=False, description="Indica se existe uma ingestão rodando no momento.")
    iniciado_em: str | None = Field(default=None, description="Timestamp ISO de início.")
    finalizado_em: str | None = Field(default=None, description="Timestamp ISO de término.")
    duracao_segundos: float = Field(default=0.0, description="Duração decorrida em segundos.")
    resumo: dict[str, int] = Field(default_factory=dict, description="Estatísticas finais da indexação.")
    erro: str | None = Field(default=None, description="Mensagem de erro em caso de falha.")
    detalhes: dict[str, Any] = Field(default_factory=dict, description="Dados complementares da etapa.")


def _executar_indexacao(tamanho_lote: int = 25) -> dict[str, int]:
    if recuperador is None:
        raise RuntimeError("RAG ainda não inicializado.")
    rastreador_ingest.iniciar("Iniciando indexação dos documentos...")
    try:
        resumo = recuperador.indexar(
            callback_progresso=rastreador_ingest.como_callback(),
            tamanho_lote=tamanho_lote,
        )
        rastreador_ingest.concluir(resumo)
        return resumo
    except Exception as erro:
        rastreador_ingest.falhar(erro)
        raise


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        total = armazenamento.contar()
        candidatos = armazenamento.contar_candidatos()
    except Exception as erro:
        raise HTTPException(status_code=503, detail=f"Banco pgvector indisponível: {erro}") from erro
    return {"status": "ok", "documentos_indexados": total, "candidatos_orquestrador": candidatos}


@app.get("/api/index/status", response_model=StatusIngestResponse)
def status_indexacao() -> dict[str, Any]:
    """Retorna o progresso e estado atual da ingestão de documentos."""
    return rastreador_ingest.obter_status()


@app.get("/api/index/stream")
async def stream_indexacao() -> StreamingResponse:
    """Acompanha em tempo real o progresso da ingestão via Server-Sent Events (SSE)."""
    return StreamingResponse(
        rastreador_ingest.gerar_stream_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/index")
def indexar(
    tarefas_segundo_plano: BackgroundTasks,
    background: bool = Query(default=False, description="Quando true, executa a ingestão em segundo plano."),
    tamanho_lote: int = Query(default=25, ge=1, le=200, description="Tamanho do lote de embeddings."),
) -> dict[str, Any]:
    """Inicia a indexação vetorial dos documentos da pasta documentos/ com acompanhamento de progresso."""
    if rastreador_ingest.obter_estado().em_andamento:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "mensagem": "Indexação já está em andamento.",
                "progresso": rastreador_ingest.obter_status(),
            },
        )

    if recuperador is None:
        raise HTTPException(status_code=503, detail="RAG ainda não inicializado.")

    if background:
        tarefas_segundo_plano.add_task(_executar_indexacao, tamanho_lote=tamanho_lote)
        return {
            "status": "iniciado",
            "mensagem": "Indexação iniciada em segundo plano. Consulte /api/index/status ou /api/index/stream.",
        }

    try:
        return _executar_indexacao(tamanho_lote=tamanho_lote)
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
