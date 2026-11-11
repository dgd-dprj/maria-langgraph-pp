"""Assuntos pendentes guardados por assistido (#450, multi-fluxo, só no release).

Quando a pessoa conta mais de um assunto, os que ficam para depois são guardados. Cada assunto guardado é
identificado por três coisas (decisão da Nicole, 2026-11-10):

- o `idUsuario`, o id da pessoa na Tykhe, que a Tykhe manda na 1ª chamada. É a chave da pessoa: quando ela volta
  outro dia, numa conversa com outro `chatId`, a Maria acha os assuntos dela por ele. Antes, a chave era o
  `idPessoa` do Verde, achado pelo CPF que a Maria pedia no começo;
- o `chatId` da conversa em que o assunto foi contado (`chat_id_origem`);
- o id do assunto, que é o `chatId` dele: `<chatId da conversa>-assunto-N`, o mesmo que a rota do próximo
  assunto usa (`chat_id_assunto`).

O que se guarda: o assunto (`flowId` ou `tipoCaso`, e o nome simples), a urgência, a situação e as datas. **Nunca** o
texto do relato nem os `dadosConhecidos`: o que a pessoa já disse volta do relato quando ela retomar (#442).

Prazo: 30 dias a partir da criação, com uma prorrogação de mais 30 por assunto (no máximo 60, decisão da Nicole
de 2026-11-09). Sem contato até o fim do prazo, o assunto é apagado de verdade, e não só muda de situação: a
limpeza roda na consulta dos pendentes de uma pessoa (`listar_ativos`) e apaga todos os vencidos, de qualquer pessoa.

Sem DATABASE_URL (testes), a store fica em memória. A data de agora vem de `agora()`, que os testes trocam para
simular o vencimento e a prorrogação.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NotRequired, Protocol, TypedDict

from maria.shared.logger import logger
from maria.shared.pool import PoolAsync, criar_pool

PRAZO = timedelta(days=30)

Situacao = Literal["pendente", "em_andamento", "resolvido"]
SITUACOES: tuple[Situacao, ...] = ("pendente", "em_andamento", "resolvido")
UrgenciaGuardada = Literal["urgente", "menos_urgente"]

# O `chatId` de cada assunto depois do primeiro é gerado pela Maria a partir do da conversa, e é o id do assunto.
SUFIXO_ASSUNTO = "-assunto-"


def chat_id_do_assunto(chat_id_conversa: str, posicao: int) -> str:
    """O 2º assunto é `<chatId>-assunto-2`, o 3º é `-assunto-3`: previsível, para a rota ser idempotente."""
    return f"{chat_id_conversa}{SUFIXO_ASSUNTO}{posicao}"


def agora() -> datetime:
    """A data de agora. Função própria para os testes simularem a passagem do tempo."""
    return datetime.now(UTC)


class PendenteGuardado(TypedDict):
    chatIdAssunto: str
    chatIdOrigem: str
    # 2, 3…: a mesma posição da rota do próximo assunto (`<chatId>-assunto-N`).
    posicao: int
    nome: str
    urgente: bool
    urgencia: UrgenciaGuardada
    situacao: Situacao
    criadoEm: datetime
    venceEm: datetime
    prorrogado: bool
    flowId: NotRequired[str]
    tipoCaso: NotRequired[str]


class PendentesStore(Protocol):
    async def guardar(self, id_usuario: str, chat_id_origem: str, pendentes: Sequence[Mapping[str, Any]]) -> None: ...
    async def listar_ativos(self, id_usuario: str) -> list[PendenteGuardado]: ...
    async def buscar(self, chat_id_assunto: str) -> PendenteGuardado | None: ...
    async def buscar_da_pessoa(self, id_usuario: str, chat_id_assunto: str) -> PendenteGuardado | None: ...
    async def marcar(self, chat_id_assunto: str, situacao: Situacao) -> bool: ...
    async def prorrogar(self, chat_id_assunto: str) -> bool: ...


@dataclass
class _Linha:
    id_usuario: str
    chat_id_origem: str
    posicao: int
    chat_id_assunto: str
    nome: str
    flow_id: str | None
    tipo_caso: str | None
    urgente: bool
    urgencia: UrgenciaGuardada
    situacao: Situacao
    criado_em: datetime
    vence_em: datetime
    prorrogado: bool = False


def _pendente(linha: _Linha | dict[str, Any]) -> PendenteGuardado:
    valores = linha if isinstance(linha, dict) else linha.__dict__
    saida: PendenteGuardado = {
        "chatIdAssunto": valores["chat_id_assunto"],
        "chatIdOrigem": valores["chat_id_origem"],
        "posicao": valores["posicao"],
        "nome": valores["nome"],
        "urgente": valores["urgente"],
        "urgencia": valores["urgencia"],
        "situacao": valores["situacao"],
        "criadoEm": valores["criado_em"],
        "venceEm": valores["vence_em"],
        "prorrogado": valores["prorrogado"],
    }
    if valores["flow_id"] is not None:
        saida["flowId"] = valores["flow_id"]
    if valores["tipo_caso"] is not None:
        saida["tipoCaso"] = valores["tipo_caso"]
    return saida


def _situacao_valida(situacao: str) -> None:
    if situacao not in SITUACOES:
        raise ValueError(f"situação desconhecida: {situacao}")


def _urgencia(item: Mapping[str, Any]) -> UrgenciaGuardada:
    """Item sem o campo (vindo de antes de 2026-11-10): o sinal de risco decide."""
    urgencia = item.get("urgencia")
    if urgencia == "urgente":
        return "urgente"
    if urgencia == "menos_urgente":
        return "menos_urgente"
    return "urgente" if item.get("urgente") is True else "menos_urgente"


class _StoreEmMemoria:
    def __init__(self) -> None:
        # Chave: o id do assunto (`chat_id_assunto`), a mesma restrição UNIQUE do Postgres.
        self._linhas: dict[str, _Linha] = {}

    async def guardar(self, id_usuario: str, chat_id_origem: str, pendentes: Sequence[Mapping[str, Any]]) -> None:
        criado = agora()
        for indice, item in enumerate(pendentes):
            chave = chat_id_do_assunto(chat_id_origem, indice + 2)
            if chave in self._linhas:
                continue  # idempotente: guardar de novo não muda nada
            self._linhas[chave] = _Linha(
                id_usuario=id_usuario,
                chat_id_origem=chat_id_origem,
                posicao=indice + 2,
                chat_id_assunto=chave,
                nome=item["nome"],
                flow_id=item.get("flowId"),
                tipo_caso=item.get("tipoCaso"),
                urgente=item["urgente"],
                urgencia=_urgencia(item),
                situacao="pendente",
                criado_em=criado,
                vence_em=criado + PRAZO,
            )

    async def listar_ativos(self, id_usuario: str) -> list[PendenteGuardado]:
        momento = agora()
        for chave, linha in list(self._linhas.items()):
            if linha.vence_em <= momento:
                del self._linhas[chave]
        ativos = [linha for linha in self._linhas.values() if linha.id_usuario == id_usuario and linha.situacao == "pendente"]
        return [_pendente(linha) for linha in sorted(ativos, key=lambda linha: (linha.criado_em, linha.chat_id_origem, linha.posicao))]

    async def buscar(self, chat_id_assunto: str) -> PendenteGuardado | None:
        linha = self._linhas.get(chat_id_assunto)
        return _pendente(linha) if linha is not None else None

    async def buscar_da_pessoa(self, id_usuario: str, chat_id_assunto: str) -> PendenteGuardado | None:
        linha = self._linhas.get(chat_id_assunto)
        return _pendente(linha) if linha is not None and linha.id_usuario == id_usuario and linha.vence_em > agora() else None

    async def marcar(self, chat_id_assunto: str, situacao: Situacao) -> bool:
        _situacao_valida(situacao)
        linha = self._linhas.get(chat_id_assunto)
        if linha is None:
            return False
        linha.situacao = situacao
        return True

    async def prorrogar(self, chat_id_assunto: str) -> bool:
        linha = self._linhas.get(chat_id_assunto)
        if linha is None or linha.prorrogado:
            return False
        linha.vence_em = agora() + PRAZO
        linha.prorrogado = True
        return True


_COLUNAS = (
    "chat_id_assunto, chat_id_origem, posicao, nome, flow_id, tipo_caso, urgente, urgencia, situacao, criado_em, vence_em, prorrogado"
)


class _StorePostgres:
    def __init__(self, pool: PoolAsync) -> None:
        self._pool = pool

    async def guardar(self, id_usuario: str, chat_id_origem: str, pendentes: Sequence[Mapping[str, Any]]) -> None:
        criado = agora()
        async with self._pool.connection() as conexao:
            for indice, item in enumerate(pendentes):
                await conexao.execute(
                    """INSERT INTO assuntos_pendentes
         (id_usuario, chat_id_origem, posicao, chat_id_assunto, nome, flow_id, tipo_caso, urgente, urgencia, situacao,
          criado_em, vence_em)
         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pendente', %s, %s)
         ON CONFLICT (chat_id_assunto) DO NOTHING""",
                    (
                        id_usuario,
                        chat_id_origem,
                        indice + 2,
                        chat_id_do_assunto(chat_id_origem, indice + 2),
                        item["nome"],
                        item.get("flowId"),
                        item.get("tipoCaso"),
                        item["urgente"],
                        _urgencia(item),
                        criado,
                        criado + PRAZO,
                    ),
                )

    async def listar_ativos(self, id_usuario: str) -> list[PendenteGuardado]:
        momento = agora()
        async with self._pool.connection() as conexao:
            await conexao.execute("DELETE FROM assuntos_pendentes WHERE vence_em <= %s", (momento,))
            linhas = await (
                await conexao.execute(
                    f"""SELECT {_COLUNAS} FROM assuntos_pendentes
         WHERE id_usuario = %s AND situacao = 'pendente' AND vence_em > %s
         ORDER BY criado_em, chat_id_origem, posicao""",
                    (id_usuario, momento),
                )
            ).fetchall()
        return [_pendente(dict(linha)) for linha in linhas]

    async def buscar(self, chat_id_assunto: str) -> PendenteGuardado | None:
        async with self._pool.connection() as conexao:
            linha = await (
                await conexao.execute(f"SELECT {_COLUNAS} FROM assuntos_pendentes WHERE chat_id_assunto = %s", (chat_id_assunto,))
            ).fetchone()
        return _pendente(dict(linha)) if linha else None

    async def buscar_da_pessoa(self, id_usuario: str, chat_id_assunto: str) -> PendenteGuardado | None:
        """O assunto, em qualquer situação, só se for desta pessoa e ainda estiver no prazo."""
        async with self._pool.connection() as conexao:
            linha = await (
                await conexao.execute(
                    f"SELECT {_COLUNAS} FROM assuntos_pendentes WHERE chat_id_assunto = %s AND id_usuario = %s AND vence_em > %s",
                    (chat_id_assunto, id_usuario, agora()),
                )
            ).fetchone()
        return _pendente(dict(linha)) if linha else None

    async def marcar(self, chat_id_assunto: str, situacao: Situacao) -> bool:
        _situacao_valida(situacao)
        async with self._pool.connection() as conexao:
            resultado = await conexao.execute(
                "UPDATE assuntos_pendentes SET situacao = %s WHERE chat_id_assunto = %s", (situacao, chat_id_assunto)
            )
        return resultado.rowcount > 0

    async def prorrogar(self, chat_id_assunto: str) -> bool:
        async with self._pool.connection() as conexao:
            resultado = await conexao.execute(
                "UPDATE assuntos_pendentes SET vence_em = %s, prorrogado = true WHERE chat_id_assunto = %s AND NOT prorrogado",
                (agora() + PRAZO, chat_id_assunto),
            )
        return resultado.rowcount > 0


_CRIAR_TABELA = """
    CREATE TABLE IF NOT EXISTS assuntos_pendentes (
      id BIGSERIAL PRIMARY KEY,
      id_usuario TEXT NOT NULL,
      chat_id_origem TEXT NOT NULL,
      posicao INTEGER NOT NULL,
      chat_id_assunto TEXT NOT NULL UNIQUE,
      nome TEXT NOT NULL,
      flow_id TEXT,
      tipo_caso TEXT,
      urgente BOOLEAN NOT NULL DEFAULT false,
      urgencia TEXT NOT NULL DEFAULT 'menos_urgente' CHECK (urgencia IN ('urgente', 'menos_urgente')),
      situacao TEXT NOT NULL DEFAULT 'pendente' CHECK (situacao IN ('pendente', 'em_andamento', 'resolvido')),
      criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
      vence_em TIMESTAMPTZ NOT NULL,
      prorrogado BOOLEAN NOT NULL DEFAULT false,
      UNIQUE (chat_id_origem, posicao)
    )
"""

# A tabela da 1ª versão (release, 2026-11-09) era pela `id_pessoa` do Verde. A coluna vira `id_usuario`, e as linhas
# de antes ganham o prefixo `idPessoa:`: um idPessoa nunca é confundido com um idUsuario da Tykhe, e essas linhas
# saem sozinhas quando vencem (a limpeza apaga os vencidos de todo mundo). Nada é apagado na migração.
_MIGRAR_DA_1A_VERSAO = """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'assuntos_pendentes' AND column_name = 'id_pessoa'
      ) THEN
        ALTER TABLE assuntos_pendentes RENAME COLUMN id_pessoa TO id_usuario;
        UPDATE assuntos_pendentes SET id_usuario = 'idPessoa:' || id_usuario;
        DROP INDEX IF EXISTS assuntos_pendentes_id_pessoa;
      END IF;
    END $$
"""

_COMPLETAR_COLUNAS = (
    "ALTER TABLE assuntos_pendentes ADD COLUMN IF NOT EXISTS chat_id_assunto TEXT",
    "UPDATE assuntos_pendentes SET chat_id_assunto = chat_id_origem || '-assunto-' || posicao WHERE chat_id_assunto IS NULL",
    "ALTER TABLE assuntos_pendentes ALTER COLUMN chat_id_assunto SET NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS assuntos_pendentes_chat_id_assunto_key ON assuntos_pendentes (chat_id_assunto)",
    """ALTER TABLE assuntos_pendentes ADD COLUMN IF NOT EXISTS urgencia TEXT NOT NULL DEFAULT 'menos_urgente'
         CHECK (urgencia IN ('urgente', 'menos_urgente'))""",
    "CREATE INDEX IF NOT EXISTS assuntos_pendentes_id_usuario ON assuntos_pendentes (id_usuario)",
    "CREATE INDEX IF NOT EXISTS assuntos_pendentes_vence_em ON assuntos_pendentes (vence_em)",
)


async def _criar_store_postgres(url: str) -> PendentesStore:
    global _pool
    pool = criar_pool(url)
    await pool.open()
    _pool = pool
    async with pool.connection() as conexao:
        await conexao.execute(_MIGRAR_DA_1A_VERSAO)
        await conexao.execute(_CRIAR_TABELA)
        for comando in _COMPLETAR_COLUNAS:
            await conexao.execute(comando)
    logger.info("[pendentesDb] tabela 'assuntos_pendentes' pronta (Postgres)")
    return _StorePostgres(pool)


async def _criar_store(url: str | None) -> PendentesStore:
    if url:
        return await _criar_store_postgres(url)
    return _StoreEmMemoria()


# Memoizado por processo, como a store de atendimentos. Fora do boot: a tabela só é criada na primeira vez que o
# release usa os pendentes, e a produção nunca a cria.
_tarefa: asyncio.Task[PendentesStore] | None = None
_pool: PoolAsync | None = None


async def obter_pendentes_store() -> PendentesStore:
    global _tarefa
    if _tarefa is None:
        _tarefa = asyncio.ensure_future(_criar_store(os.environ.get("DATABASE_URL")))
    return await _tarefa


async def fechar_pendentes_store() -> None:
    """Fecha o pool e zera a memoização (lifespan e testes)."""
    global _tarefa, _pool
    if _pool is not None:
        await _pool.close()
    _pool = None
    _tarefa = None
