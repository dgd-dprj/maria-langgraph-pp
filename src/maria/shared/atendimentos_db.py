"""Registro de atendimentos: chatId → flowId, desfecho e controle de TTL.

chatId é a chave: um chatId pertence a exatamente um flowId para sempre. É o
que permite GET e POST /atendimentos/respostas não precisarem de flowId de
novo: o servidor resolve sozinho. A chave primária em chat_id também bloqueia a
colisão que motivou a tabela: criar um atendimento com um chatId já usado por
OUTRO flowId vira erro explícito (ver `registrar`), em vez de dois fluxos
pisando no mesmo checkpoint do LangGraph, que é indexado só por
thread_id = chatId.

Issue #83: colunas de desfecho preenchidas na conclusão (`concluir`), para
consulta SQL direta no Grafana (painel id 12). Issue #166: TTL de inatividade.

Sem DATABASE_URL (testes), a store fica em memória. As duas implementações
divergem em três pontos, reproduzidos de propósito porque develop é assim:
`concluir` em memória grava só `statusFinal`; e `resolver_confirmacao_ttl_continuar`
devolve `None` no Postgres e a resposta pendente em memória (defeito de
produção, #217).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Literal, Protocol, Required, TypedDict

from maria.shared.logger import logger
from maria.shared.pool import PoolAsync, criar_pool
from maria.shared.tokens_acumulados import TokensGastos


class ConclusaoAtendimento(TypedDict, total=False):
    statusFinal: Required[Literal["concluido", "handoff_humano", "expirado"]]
    destino: str
    motivoHandoff: str
    tokensGastos: TokensGastos


class AtividadeAtendimento(TypedDict, total=False):
    """`atualizadoEm` é a última vez que uma resposta foi PROCESSADA de verdade
    (não a criação). `aguardandoConfirmacaoTtl`/`respostaPendente` existem só
    entre a pergunta "quer continuar?" e a resposta a ela."""

    atualizadoEm: Required[datetime]
    statusFinal: str
    aguardandoConfirmacaoTtl: Required[bool]
    respostaPendente: str


class RegistroOk(TypedDict):
    ok: Literal[True]


class RegistroConflito(TypedDict):
    ok: Literal[False]
    flowIdExistente: str


class AtendimentosStore(Protocol):
    async def registrar(self, chat_id: str, flow_id: str) -> RegistroOk | RegistroConflito: ...
    async def buscar_flow_id(self, chat_id: str) -> str | None: ...
    async def concluir(self, chat_id: str, dados: ConclusaoAtendimento) -> None: ...
    async def buscar_atividade(self, chat_id: str) -> AtividadeAtendimento | None: ...
    async def marcar_atividade(self, chat_id: str) -> None: ...
    async def marcar_aguardando_confirmacao_ttl(self, chat_id: str, resposta_pendente: str) -> None: ...
    async def resolver_confirmacao_ttl_continuar(self, chat_id: str) -> str | None: ...


def _atividade(atualizado_em: datetime, status_final: str | None, aguardando: bool, resposta_pendente: str | None) -> AtividadeAtendimento:
    # `?? undefined` de develop: chave ausente, e não None.
    atividade: AtividadeAtendimento = {"atualizadoEm": atualizado_em, "aguardandoConfirmacaoTtl": aguardando}
    if status_final is not None:
        atividade["statusFinal"] = status_final
    if resposta_pendente is not None:
        atividade["respostaPendente"] = resposta_pendente
    return atividade


class _RegistroEmMemoria:
    def __init__(self, flow_id: str) -> None:
        self.flow_id = flow_id
        self.atualizado_em = datetime.now(UTC)
        self.status_final: str | None = None
        self.aguardando_confirmacao_ttl = False
        self.resposta_pendente: str | None = None


class _StoreEmMemoria:
    """Mesmos campos de atividade/TTL do Postgres (issue #166). Os testes de TTL
    usam TTL_INATIVIDADE_HORAS=0 para forçar expiração sem mexer no relógio."""

    def __init__(self) -> None:
        self._mapa: dict[str, _RegistroEmMemoria] = {}

    async def registrar(self, chat_id: str, flow_id: str) -> RegistroOk | RegistroConflito:
        existente = self._mapa.get(chat_id)
        if existente is not None:
            if existente.flow_id == flow_id:
                return {"ok": True}
            return {"ok": False, "flowIdExistente": existente.flow_id}
        self._mapa[chat_id] = _RegistroEmMemoria(flow_id)
        return {"ok": True}

    async def buscar_flow_id(self, chat_id: str) -> str | None:
        registro = self._mapa.get(chat_id)
        return registro.flow_id if registro else None

    async def concluir(self, chat_id: str, dados: ConclusaoAtendimento) -> None:
        # Grava SÓ statusFinal, como develop (atendimentosDb.ts:70-73). A store
        # Postgres grava também destino, motivo, tokens e concluido_em.
        registro = self._mapa.get(chat_id)
        if registro:
            registro.status_final = dados["statusFinal"]

    async def buscar_atividade(self, chat_id: str) -> AtividadeAtendimento | None:
        registro = self._mapa.get(chat_id)
        if not registro:
            return None
        return _atividade(registro.atualizado_em, registro.status_final, registro.aguardando_confirmacao_ttl, registro.resposta_pendente)

    async def marcar_atividade(self, chat_id: str) -> None:
        registro = self._mapa.get(chat_id)
        if registro:
            registro.atualizado_em = datetime.now(UTC)

    async def marcar_aguardando_confirmacao_ttl(self, chat_id: str, resposta_pendente: str) -> None:
        registro = self._mapa.get(chat_id)
        if registro:
            registro.aguardando_confirmacao_ttl = True
            registro.resposta_pendente = resposta_pendente

    async def resolver_confirmacao_ttl_continuar(self, chat_id: str) -> str | None:
        registro = self._mapa.get(chat_id)
        if not registro:
            return None
        pendente = registro.resposta_pendente
        registro.aguardando_confirmacao_ttl = False
        registro.resposta_pendente = None
        registro.atualizado_em = datetime.now(UTC)
        return pendente


class _StorePostgres:
    def __init__(self, pool: PoolAsync) -> None:
        self._pool = pool

    async def registrar(self, chat_id: str, flow_id: str) -> RegistroOk | RegistroConflito:
        # ON CONFLICT DO NOTHING + RETURNING: se inseriu, era novo. Se não, busca
        # o flow_id real para comparar: mesmo chatId+flowId de novo é idempotente,
        # chatId com OUTRO flowId é o conflito que a tabela existe para pegar.
        async with self._pool.connection() as conexao:
            inserido = await conexao.execute(
                """INSERT INTO atendimentos (chat_id, flow_id) VALUES (%s, %s)
         ON CONFLICT (chat_id) DO NOTHING
         RETURNING flow_id""",
                (chat_id, flow_id),
            )
            if inserido.rowcount > 0:
                return {"ok": True}
            existente = await (await conexao.execute("SELECT flow_id FROM atendimentos WHERE chat_id = %s", (chat_id,))).fetchone()
        # A coluna é UUID: o psycopg devolve uuid.UUID, e o pg devolvia o texto
        # em minúsculas. Sem str(), UUID != str e todo registro repetido viraria
        # conflito falso (409 na rota).
        flow_id_existente = str(existente["flow_id"]) if existente else flow_id
        if flow_id_existente == flow_id:
            return {"ok": True}
        return {"ok": False, "flowIdExistente": flow_id_existente}

    async def buscar_flow_id(self, chat_id: str) -> str | None:
        async with self._pool.connection() as conexao:
            linha = await (await conexao.execute("SELECT flow_id FROM atendimentos WHERE chat_id = %s", (chat_id,))).fetchone()
        return str(linha["flow_id"]) if linha else None

    async def concluir(self, chat_id: str, dados: ConclusaoAtendimento) -> None:
        tokens = dados.get("tokensGastos")
        async with self._pool.connection() as conexao:
            await conexao.execute(
                """UPDATE atendimentos
         SET concluido_em = now(), status_final = %s, destino = %s, motivo_handoff = %s,
             tokens_entrada = %s, tokens_saida = %s, tokens_total = %s
         WHERE chat_id = %s""",
                (
                    dados["statusFinal"],
                    dados.get("destino"),
                    dados.get("motivoHandoff"),
                    tokens["input"] if tokens else None,
                    tokens["output"] if tokens else None,
                    tokens["total"] if tokens else None,
                    chat_id,
                ),
            )

    async def buscar_atividade(self, chat_id: str) -> AtividadeAtendimento | None:
        async with self._pool.connection() as conexao:
            linha = await (
                await conexao.execute(
                    """SELECT atualizado_em, status_final, aguardando_confirmacao_ttl, resposta_pendente_ttl
         FROM atendimentos WHERE chat_id = %s""",
                    (chat_id,),
                )
            ).fetchone()
        if not linha:
            return None
        # TIMESTAMPTZ volta com microssegundo (o pg truncava em milissegundo). Fica
        # assim: nenhum timestamp atravessa a fronteira HTTP (decisão da spec).
        return _atividade(
            linha["atualizado_em"], linha["status_final"], linha["aguardando_confirmacao_ttl"], linha["resposta_pendente_ttl"]
        )

    async def marcar_atividade(self, chat_id: str) -> None:
        async with self._pool.connection() as conexao:
            await conexao.execute("UPDATE atendimentos SET atualizado_em = now() WHERE chat_id = %s", (chat_id,))

    async def marcar_aguardando_confirmacao_ttl(self, chat_id: str, resposta_pendente: str) -> None:
        async with self._pool.connection() as conexao:
            await conexao.execute(
                "UPDATE atendimentos SET aguardando_confirmacao_ttl = true, resposta_pendente_ttl = %s WHERE chat_id = %s",
                (resposta_pendente, chat_id),
            )

    async def resolver_confirmacao_ttl_continuar(self, chat_id: str) -> str | None:
        # Issue #217, corrigida em develop pelo PR #226 (atendimentosDb.ts:221-234
        # em develop @ 0aecd98): o RETURNING de um UPDATE devolve o valor DEPOIS da
        # atualização (sempre NULL, a coluna acabou de ser limpa). O valor antigo
        # vem do subselect `anterior`, travado com FOR UPDATE para duas
        # confirmações simultâneas não lerem a mesma resposta pendente.
        async with self._pool.connection() as conexao:
            linha = await (
                await conexao.execute(
                    """UPDATE atendimentos a
         SET aguardando_confirmacao_ttl = false, resposta_pendente_ttl = NULL, atualizado_em = now()
         FROM (SELECT chat_id, resposta_pendente_ttl FROM atendimentos WHERE chat_id = %s FOR UPDATE) anterior
         WHERE a.chat_id = anterior.chat_id
         RETURNING anterior.resposta_pendente_ttl""",
                    (chat_id,),
                )
            ).fetchone()
        valor = linha["resposta_pendente_ttl"] if linha else None
        return valor if isinstance(valor, str) else None


async def _criar_store_postgres(url: str) -> AtendimentosStore:
    global _pool
    pool = criar_pool(url)
    await pool.open()
    _pool = pool
    async with pool.connection() as conexao:
        await conexao.execute(
            """
    CREATE TABLE IF NOT EXISTS atendimentos (
      chat_id TEXT PRIMARY KEY,
      flow_id UUID NOT NULL,
      criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  """
        )
        # Issue #83: colunas de desfecho por ALTER, e não recriação: a tabela já
        # existe em produção com linhas. Todas nullable: só ganham valor em concluir().
        await conexao.execute(
            """
    ALTER TABLE atendimentos
      ADD COLUMN IF NOT EXISTS concluido_em TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS status_final TEXT,
      ADD COLUMN IF NOT EXISTS destino TEXT,
      ADD COLUMN IF NOT EXISTS motivo_handoff TEXT,
      ADD COLUMN IF NOT EXISTS tokens_entrada INTEGER,
      ADD COLUMN IF NOT EXISTS tokens_saida INTEGER,
      ADD COLUMN IF NOT EXISTS tokens_total INTEGER
  """
        )
        # Issue #166: TTL de inatividade.
        await conexao.execute(
            """
    ALTER TABLE atendimentos
      ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS aguardando_confirmacao_ttl BOOLEAN NOT NULL DEFAULT false,
      ADD COLUMN IF NOT EXISTS resposta_pendente_ttl TEXT
  """
        )
        # Achado ao vivo em 2026-09-25: sem DEFAULT, toda linha NOVA ficava com
        # atualizado_em NULL. SET DEFAULT é idempotente.
        await conexao.execute("ALTER TABLE atendimentos ALTER COLUMN atualizado_em SET DEFAULT now()")
        await conexao.execute("UPDATE atendimentos SET atualizado_em = criado_em WHERE atualizado_em IS NULL")
    logger.info("[atendimentosDb] tabela 'atendimentos' pronta (Postgres)")
    return _StorePostgres(pool)


async def _criar_store(url: str | None) -> AtendimentosStore:
    if url:
        return await _criar_store_postgres(url)
    return _StoreEmMemoria()


# Memoizado por processo: um pool compartilhado. Uma falha na criação do esquema
# fica memoizada e se repete em toda chamada seguinte, sem nova tentativa, como
# a promessa rejeitada de develop (atendimentosDb.ts:237-243).
_tarefa: asyncio.Task[AtendimentosStore] | None = None
_pool: PoolAsync | None = None


async def obter_atendimentos_store() -> AtendimentosStore:
    global _tarefa
    if _tarefa is None:
        _tarefa = asyncio.ensure_future(_criar_store(os.environ.get("DATABASE_URL")))
    return await _tarefa


async def fechar_atendimentos_store() -> None:
    """Fecha o pool e zera a memoização (lifespan e testes; ver a spec)."""
    global _tarefa, _pool
    if _pool is not None:
        await _pool.close()
    _pool = None
    _tarefa = None
