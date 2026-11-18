"""Modelos e utilitários para acompanhamento do progresso de ingestão RAG."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ProgressoIngest:
    """Estado pontual do processo de ingestão."""

    etapa: str = "ocioso"
    mensagem: str = "Nenhuma ingestão em andamento."
    atual: int = 0
    total: int = 0
    porcentagem: float = 0.0
    arquivo_atual: str = ""
    em_andamento: bool = False
    iniciado_em: str | None = None
    finalizado_em: str | None = None
    duracao_segundos: float = 0.0
    resumo: dict[str, int] = field(default_factory=dict)
    erro: str | None = None
    detalhes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CallbackProgresso = Callable[[ProgressoIngest], None]


class RastreadorProgresso:
    """Gerencia o progresso da ingestão de forma thread-safe com suporte a SSE."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._estado = ProgressoIngest()
        self._inicio_timestamp: float | None = None
        self._ouvintes: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def obter_estado(self) -> ProgressoIngest:
        with self._lock:
            # Retorna cópia rasa
            return ProgressoIngest(**asdict(self._estado))

    def obter_status(self) -> dict[str, Any]:
        with self._lock:
            if self._estado.em_andamento and self._inicio_timestamp is not None:
                self._estado.duracao_segundos = round(time.time() - self._inicio_timestamp, 2)
            return self._estado.to_dict()

    def registrar_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def iniciar(self, mensagem: str = "Iniciando ingestão de documentos...") -> ProgressoIngest:
        agora = datetime.now(UTC).isoformat()
        with self._lock:
            self._inicio_timestamp = time.time()
            self._estado = ProgressoIngest(
                etapa="iniciando",
                mensagem=mensagem,
                atual=0,
                total=0,
                porcentagem=0.0,
                arquivo_atual="",
                em_andamento=True,
                iniciado_em=agora,
                finalizado_em=None,
                duracao_segundos=0.0,
                resumo={},
                erro=None,
                detalhes={},
            )
            estado_copia = ProgressoIngest(**asdict(self._estado))
        self._notificar(estado_copia)
        return estado_copia

    def atualizar(
        self,
        etapa: str | None = None,
        mensagem: str | None = None,
        atual: int | None = None,
        total: int | None = None,
        arquivo_atual: str | None = None,
        porcentagem: float | None = None,
        detalhes: dict[str, Any] | None = None,
    ) -> ProgressoIngest:
        with self._lock:
            if etapa is not None:
                self._estado.etapa = etapa
            if mensagem is not None:
                self._estado.mensagem = mensagem
            if atual is not None:
                self._estado.atual = atual
            if total is not None:
                self._estado.total = total
            if arquivo_atual is not None:
                self._estado.arquivo_atual = arquivo_atual

            if porcentagem is not None:
                self._estado.porcentagem = round(porcentagem, 1)
            elif self._estado.total > 0:
                calc = (self._estado.atual / self._estado.total) * 100
                self._estado.porcentagem = round(min(max(calc, 0.0), 100.0), 1)

            if detalhes is not None:
                self._estado.detalhes = {**self._estado.detalhes, **detalhes}

            if self._inicio_timestamp is not None:
                self._estado.duracao_segundos = round(time.time() - self._inicio_timestamp, 2)

            estado_copia = ProgressoIngest(**asdict(self._estado))

        self._notificar(estado_copia)
        return estado_copia

    def concluir(
        self,
        resumo: dict[str, int],
        mensagem: str = "Indexação concluída com sucesso.",
    ) -> ProgressoIngest:
        agora = datetime.now(UTC).isoformat()
        with self._lock:
            duracao = round(time.time() - self._inicio_timestamp, 2) if self._inicio_timestamp else 0.0
            self._estado.etapa = "concluido"
            self._estado.mensagem = mensagem
            self._estado.em_andamento = False
            self._estado.finalizado_em = agora
            self._estado.duracao_segundos = duracao
            self._estado.porcentagem = 100.0
            self._estado.resumo = dict(resumo)
            estado_copia = ProgressoIngest(**asdict(self._estado))

        self._notificar(estado_copia)
        return estado_copia

    def falhar(
        self,
        erro: str | Exception,
        mensagem: str | None = None,
    ) -> ProgressoIngest:
        agora = datetime.now(UTC).isoformat()
        msg_erro = str(erro)
        with self._lock:
            duracao = round(time.time() - self._inicio_timestamp, 2) if self._inicio_timestamp else 0.0
            self._estado.etapa = "erro"
            self._estado.mensagem = mensagem or f"Falha na ingestão: {msg_erro}"
            self._estado.em_andamento = False
            self._estado.finalizado_em = agora
            self._estado.duracao_segundos = duracao
            self._estado.erro = msg_erro
            estado_copia = ProgressoIngest(**asdict(self._estado))

        self._notificar(estado_copia)
        return estado_copia

    def _notificar(self, estado: ProgressoIngest) -> None:
        dados = estado.to_dict()
        with self._lock:
            ouvintes = list(self._ouvintes)
            loop = self._loop

        for fila in ouvintes:
            try:
                if loop is not None and loop.is_running():
                    loop.call_soon_threadsafe(fila.put_nowait, dados)
                else:
                    fila.put_nowait(dados)
            except Exception:
                pass

    def como_callback(self) -> CallbackProgresso:
        """Retorna uma função callback compatível com CallbackProgresso."""

        def _cb(p: ProgressoIngest) -> None:
            self.atualizar(
                etapa=p.etapa,
                mensagem=p.mensagem,
                atual=p.atual,
                total=p.total,
                arquivo_atual=p.arquivo_atual,
                porcentagem=p.porcentagem if p.porcentagem > 0 else None,
                detalhes=p.detalhes,
            )

        return _cb

    async def registrar_ouvinte(self) -> asyncio.Queue[dict[str, Any]]:
        fila: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        with self._lock:
            self._ouvintes.add(fila)
            self._loop = asyncio.get_running_loop()
        # Envia estado inicial atual imediatamente
        await fila.put(self.obter_status())
        return fila

    def remover_ouvinte(self, fila: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._ouvintes.discard(fila)

    async def gerar_stream_sse(self) -> AsyncIterator[str]:
        """Gera eventos SSE no formato 'data: {...}\\n\\n' para clientes HTTP."""
        import json

        fila = await self.registrar_ouvinte()
        try:
            while True:
                dados = await fila.get()
                yield f"data: {json.dumps(dados, ensure_ascii=False)}\n\n"
                if not dados.get("em_andamento") and dados.get("etapa") in ("concluido", "erro"):
                    # Ao concluir ou falhar, envia o último e encerra stream
                    break
        finally:
            self.remover_ouvinte(fila)
