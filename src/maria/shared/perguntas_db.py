"""Árvore de perguntas do Verde por categoria (issue #20).

Alimentada pelo script de coleta (`scripts/coletar_arvore_perguntas_verde.py`),
sob demanda, nunca em requisição. `flowId` é o MESMO uuid usado no registro de
fluxos e em `fluxos_planejados`, sem FK física: metade desses ids só existe em
código.

Sem DATABASE_URL (testes), a store fica em memória. Divergência entre as duas,
reproduzida de propósito porque develop é assim: `listar_perguntas_por_flow`
ordena por `ordem` no Postgres e mantém a ordem de inserção em memória.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Literal, NotRequired, Protocol, TypedDict

from maria.shared.logger import logger
from maria.shared.pool import PoolAsync, criar_pool


class OpcaoPergunta(TypedDict):
    id: int
    resposta: str


class PerguntaArvore(TypedDict):
    id: str
    flowId: str
    # None no nó raiz (identificado por idCategoria; só os filhos têm idItemCategoria).
    idItemCategoria: int | None
    # id da resposta (Verde) que levou até este nó; None no nó raiz.
    veioDaRespostaId: int | None
    textoPergunta: str
    # "texto" cobre nós informativos sem opções reais (dado inconsistente do Verde).
    tipo: Literal["sim_nao", "opcoes", "texto"]
    opcoes: list[OpcaoPergunta]
    # Ordem de inserção durante o crawl (DFS); não é profundidade na árvore.
    ordem: int


class DocumentoNecessario(TypedDict):
    id: int
    nomeDocumento: str
    basico: bool


class AssuntoVerde(TypedDict):
    """Nó FINAL da árvore (GET /assunto/{id}), SEM flowId de propósito: o mesmo
    assunto pode ser destino de várias categorias (ex.: "LIGAR 129"). A ligação
    (flow, assunto) mora em `flow_assuntos`."""

    idAssunto: int
    nome: str
    nomeMateria: NotRequired[str]
    descricao: NotRequired[str]
    txDocumentosNecessarios: NotRequired[str]
    documentosNecessarios: list[DocumentoNecessario]
    urgente: bool
    plantao: bool


class FlowAssunto(TypedDict):
    id: str
    flowId: str
    idAssunto: int
    veioDaRespostaId: int | None


class AssuntoDoFlow(AssuntoVerde):
    veioDaRespostaId: int | None


class PerguntasStore(Protocol):
    async def inserir_pergunta(self, p: PerguntaArvore) -> None: ...
    async def inserir_assunto(self, a: AssuntoVerde) -> None: ...
    async def inserir_flow_assunto(self, fa: FlowAssunto) -> None: ...
    async def listar_perguntas_por_flow(self, flow_id: str) -> list[PerguntaArvore]: ...
    # Pergunta raiz (ordem 0), usada pelo orquestrador (issue #32).
    async def buscar_pergunta_raiz(self, flow_id: str) -> PerguntaArvore | None: ...
    async def listar_assuntos_por_flow(self, flow_id: str) -> list[AssuntoDoFlow]: ...
    # Remove perguntas e ligações flow→assunto antes de recoletar. NÃO apaga
    # assuntos_verde (detalhe compartilhado com outros flows).
    async def limpar_flow(self, flow_id: str) -> None: ...


def _assunto_do_flow(detalhe: AssuntoVerde, veio_da_resposta_id: int | None) -> AssuntoDoFlow:
    assunto: dict[str, Any] = {**detalhe, "veioDaRespostaId": veio_da_resposta_id}
    return assunto  # type: ignore[return-value]


class _StoreEmMemoria:
    def __init__(self) -> None:
        self._perguntas: list[PerguntaArvore] = []
        self._assuntos: dict[int, AssuntoVerde] = {}
        self._flow_assuntos: list[FlowAssunto] = []

    async def inserir_pergunta(self, p: PerguntaArvore) -> None:
        self._perguntas.append(p)

    async def inserir_assunto(self, a: AssuntoVerde) -> None:
        self._assuntos[a["idAssunto"]] = a

    async def inserir_flow_assunto(self, fa: FlowAssunto) -> None:
        self._flow_assuntos.append(fa)

    async def listar_perguntas_por_flow(self, flow_id: str) -> list[PerguntaArvore]:
        # Ordem de inserção, SEM ordenar por `ordem` (perguntasDb.ts:96-98).
        return [p for p in self._perguntas if p["flowId"] == flow_id]

    async def buscar_pergunta_raiz(self, flow_id: str) -> PerguntaArvore | None:
        return next((p for p in self._perguntas if p["flowId"] == flow_id and p["ordem"] == 0), None)

    async def listar_assuntos_por_flow(self, flow_id: str) -> list[AssuntoDoFlow]:
        resultado: list[AssuntoDoFlow] = []
        for fa in self._flow_assuntos:
            if fa["flowId"] != flow_id:
                continue
            detalhe = self._assuntos.get(fa["idAssunto"])
            if detalhe is None:
                raise RuntimeError(f"flowAssunto aponta pra idAssunto {fa['idAssunto']} sem detalhe inserido")
            resultado.append(_assunto_do_flow(detalhe, fa["veioDaRespostaId"]))
        return resultado

    async def limpar_flow(self, flow_id: str) -> None:
        self._perguntas[:] = [p for p in self._perguntas if p["flowId"] != flow_id]
        self._flow_assuntos[:] = [fa for fa in self._flow_assuntos if fa["flowId"] != flow_id]


def _json(valor: object) -> str:
    # Mesmo texto do JSON.stringify: sem espaços e com UTF-8 cru.
    return json.dumps(valor, ensure_ascii=False, separators=(",", ":"))


def _pergunta(linha: dict[str, Any]) -> PerguntaArvore:
    return {
        "id": linha["id"],
        "flowId": linha["flow_id"],
        # null de verdade aqui (chave presente), como develop.
        "idItemCategoria": linha["id_item_categoria"],
        "veioDaRespostaId": linha["veio_da_resposta_id"],
        "textoPergunta": linha["texto_pergunta"],
        "tipo": linha["tipo"],
        "opcoes": linha["opcoes"],
        "ordem": linha["ordem"],
    }


class _StorePostgres:
    def __init__(self, pool: PoolAsync) -> None:
        self._pool = pool
        # Como o prontoPromise de develop: a criação do esquema dispara na
        # construção, e cada método a aguarda. Se falhar, toda chamada falha,
        # sem nova tentativa.
        self._pronto: asyncio.Task[None] = asyncio.ensure_future(self._preparar())

    async def _preparar(self) -> None:
        await self._pool.open()
        async with self._pool.connection() as conexao:
            await conexao.execute(
                """
      CREATE TABLE IF NOT EXISTS perguntas (
        id TEXT PRIMARY KEY,
        flow_id TEXT NOT NULL,
        id_item_categoria INTEGER,
        veio_da_resposta_id INTEGER,
        texto_pergunta TEXT NOT NULL,
        tipo TEXT NOT NULL,
        opcoes JSONB NOT NULL DEFAULT '[]',
        ordem INTEGER NOT NULL
      )
    """
            )
            await conexao.execute("CREATE INDEX IF NOT EXISTS perguntas_flow_id_idx ON perguntas (flow_id)")
            await conexao.execute(
                """
      CREATE TABLE IF NOT EXISTS assuntos_verde (
        id_assunto INTEGER PRIMARY KEY,
        nome TEXT NOT NULL,
        nome_materia TEXT,
        descricao TEXT,
        tx_documentos_necessarios TEXT,
        documentos_necessarios JSONB NOT NULL DEFAULT '[]',
        urgente BOOLEAN NOT NULL DEFAULT false,
        plantao BOOLEAN NOT NULL DEFAULT false
      )
    """
            )
            await conexao.execute(
                """
      CREATE TABLE IF NOT EXISTS flow_assuntos (
        id TEXT PRIMARY KEY,
        flow_id TEXT NOT NULL,
        id_assunto INTEGER NOT NULL,
        veio_da_resposta_id INTEGER
      )
    """
            )
            await conexao.execute("CREATE INDEX IF NOT EXISTS flow_assuntos_flow_id_idx ON flow_assuntos (flow_id)")
        logger.info("[perguntasDb] tabelas 'perguntas', 'assuntos_verde' e 'flow_assuntos' prontas (Postgres)")

    async def inserir_pergunta(self, p: PerguntaArvore) -> None:
        await self._pronto
        # Parâmetros nomeados onde develop reutiliza $5..$8 no DO UPDATE.
        async with self._pool.connection() as conexao:
            await conexao.execute(
                """INSERT INTO perguntas (id, flow_id, id_item_categoria, veio_da_resposta_id, texto_pergunta, tipo, opcoes, ordem)
         VALUES (%(id)s, %(flow_id)s, %(id_item_categoria)s, %(veio_da_resposta_id)s, %(texto_pergunta)s, %(tipo)s, %(opcoes)s::jsonb, %(ordem)s)
         ON CONFLICT (id) DO UPDATE SET texto_pergunta = %(texto_pergunta)s, tipo = %(tipo)s, opcoes = %(opcoes)s::jsonb, ordem = %(ordem)s""",
                {
                    "id": p["id"],
                    "flow_id": p["flowId"],
                    "id_item_categoria": p["idItemCategoria"],
                    "veio_da_resposta_id": p["veioDaRespostaId"],
                    "texto_pergunta": p["textoPergunta"],
                    "tipo": p["tipo"],
                    "opcoes": _json(p["opcoes"]),
                    "ordem": p["ordem"],
                },
            )

    async def inserir_assunto(self, a: AssuntoVerde) -> None:
        await self._pronto
        async with self._pool.connection() as conexao:
            await conexao.execute(
                """INSERT INTO assuntos_verde (id_assunto, nome, nome_materia, descricao, tx_documentos_necessarios, documentos_necessarios, urgente, plantao)
         VALUES (%(id_assunto)s, %(nome)s, %(nome_materia)s, %(descricao)s, %(tx_documentos_necessarios)s, %(documentos_necessarios)s::jsonb, %(urgente)s, %(plantao)s)
         ON CONFLICT (id_assunto) DO UPDATE SET nome = %(nome)s, nome_materia = %(nome_materia)s, descricao = %(descricao)s,
           tx_documentos_necessarios = %(tx_documentos_necessarios)s, documentos_necessarios = %(documentos_necessarios)s::jsonb, urgente = %(urgente)s, plantao = %(plantao)s""",
                {
                    "id_assunto": a["idAssunto"],
                    "nome": a["nome"],
                    "nome_materia": a.get("nomeMateria"),
                    "descricao": a.get("descricao"),
                    "tx_documentos_necessarios": a.get("txDocumentosNecessarios"),
                    "documentos_necessarios": _json(a["documentosNecessarios"]),
                    "urgente": a["urgente"],
                    "plantao": a["plantao"],
                },
            )

    async def inserir_flow_assunto(self, fa: FlowAssunto) -> None:
        await self._pronto
        async with self._pool.connection() as conexao:
            await conexao.execute(
                """INSERT INTO flow_assuntos (id, flow_id, id_assunto, veio_da_resposta_id)
         VALUES (%(id)s, %(flow_id)s, %(id_assunto)s, %(veio_da_resposta_id)s)
         ON CONFLICT (id) DO UPDATE SET id_assunto = %(id_assunto)s, veio_da_resposta_id = %(veio_da_resposta_id)s""",
                {"id": fa["id"], "flow_id": fa["flowId"], "id_assunto": fa["idAssunto"], "veio_da_resposta_id": fa["veioDaRespostaId"]},
            )

    async def listar_perguntas_por_flow(self, flow_id: str) -> list[PerguntaArvore]:
        await self._pronto
        async with self._pool.connection() as conexao:
            linhas = await (await conexao.execute("SELECT * FROM perguntas WHERE flow_id = %s ORDER BY ordem", (flow_id,))).fetchall()
        return [_pergunta(linha) for linha in linhas]

    async def buscar_pergunta_raiz(self, flow_id: str) -> PerguntaArvore | None:
        await self._pronto
        async with self._pool.connection() as conexao:
            linha = await (await conexao.execute("SELECT * FROM perguntas WHERE flow_id = %s AND ordem = 0 LIMIT 1", (flow_id,))).fetchone()
        return _pergunta(linha) if linha else None

    async def listar_assuntos_por_flow(self, flow_id: str) -> list[AssuntoDoFlow]:
        await self._pronto
        async with self._pool.connection() as conexao:
            linhas = await (
                await conexao.execute(
                    """SELECT av.*, fa.veio_da_resposta_id AS fa_veio_da_resposta_id
         FROM flow_assuntos fa
         JOIN assuntos_verde av ON av.id_assunto = fa.id_assunto
         WHERE fa.flow_id = %s""",
                    (flow_id,),
                )
            ).fetchall()
        resultado: list[AssuntoDoFlow] = []
        for linha in linhas:
            assunto: dict[str, Any] = {"idAssunto": linha["id_assunto"], "nome": linha["nome"]}
            # `?? undefined` de develop: chave ausente quando a coluna é NULL.
            for chave, coluna in (
                ("nomeMateria", "nome_materia"),
                ("descricao", "descricao"),
                ("txDocumentosNecessarios", "tx_documentos_necessarios"),
            ):
                if linha[coluna] is not None:
                    assunto[chave] = linha[coluna]
            assunto["documentosNecessarios"] = linha["documentos_necessarios"]
            assunto["urgente"] = linha["urgente"]
            assunto["plantao"] = linha["plantao"]
            assunto["veioDaRespostaId"] = linha["fa_veio_da_resposta_id"]
            resultado.append(assunto)  # type: ignore[arg-type]
        return resultado

    async def limpar_flow(self, flow_id: str) -> None:
        await self._pronto
        async with self._pool.connection() as conexao:
            await conexao.execute("DELETE FROM perguntas WHERE flow_id = %s", (flow_id,))
            await conexao.execute("DELETE FROM flow_assuntos WHERE flow_id = %s", (flow_id,))


_store: PerguntasStore | None = None
_pool: PoolAsync | None = None


async def obter_perguntas_store() -> PerguntasStore:
    global _store, _pool
    if _store is None:
        url = os.environ.get("DATABASE_URL")
        if url:
            _pool = criar_pool(url)
            _store = _StorePostgres(_pool)
        else:
            _store = _StoreEmMemoria()
    return _store


async def fechar_perguntas_store() -> None:
    """Fecha o pool e zera a memoização (lifespan e testes; ver a spec)."""
    global _store, _pool
    if isinstance(_store, _StorePostgres):
        await asyncio.gather(_store._pronto, return_exceptions=True)
    if _pool is not None:
        await _pool.close()
    _store = None
    _pool = None
