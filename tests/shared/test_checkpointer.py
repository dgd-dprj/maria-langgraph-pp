"""Checkpointer: memória sem `DATABASE_URL`; Postgres em schema próprio com `DATABASE_URL`.

Os testes `postgres` rodam na segunda etapa do CI, contra o serviço Postgres
com pgvector. Eles provam que o `setup()` do Python cria as tabelas só em
`SCHEMA_CHECKPOINT` e não toca nas tabelas de checkpoint que o LangGraph JS
criou em `public`.
"""

import json
import math
import os
from collections.abc import AsyncIterator

import psycopg
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import sql
from psycopg.rows import TupleRow

from maria.app import criar_app
from maria.shared.checkpointer import SCHEMA_CHECKPOINT, fechar_checkpointer, inicializar_checkpointer, obter_checkpointer

TABELAS_CHECKPOINT = {"checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes"}


@pytest.fixture(autouse=True)
async def _checkpointer_limpo() -> AsyncIterator[None]:
    await fechar_checkpointer()
    yield
    await fechar_checkpointer()


async def test_sem_database_url_usa_memoria(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert isinstance(await inicializar_checkpointer(), InMemorySaver)


async def test_memoizado_por_processo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    primeiro = await inicializar_checkpointer()
    assert await inicializar_checkpointer() is primeiro
    assert obter_checkpointer() is primeiro


def test_obter_antes_de_inicializar_lanca() -> None:
    with pytest.raises(RuntimeError, match="não inicializado"):
        obter_checkpointer()


class _ConexaoFalsa:
    def __init__(self) -> None:
        self.comandos: list[str] = []

    async def execute(self, comando: sql.Composable) -> None:
        self.comandos.append(comando.as_string(None))

    async def __aenter__(self) -> "_ConexaoFalsa":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


async def test_search_path_e_fixado_em_cada_conexao_nova_pelo_configure_do_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    # search_path vale por conexão. Se fosse definido uma vez depois de abrir o
    # pool, as conexões criadas depois cairiam em public, onde estão as tabelas
    # do JS com os mesmos nomes. O psycopg_pool chama `configure` em
    # AsyncConnectionPool._connect, para cada conexão nova; este teste prova que
    # o checkpointer usa esse gancho, sem precisar de banco.
    from maria.shared import checkpointer

    argumentos_do_pool: dict[str, object] = {}
    conexao_do_schema = _ConexaoFalsa()

    class _PoolFalso:
        def __init__(self, _conninfo: str, **kwargs: object) -> None:
            argumentos_do_pool.update(kwargs)

        async def open(self) -> None:
            return None

        async def close(self) -> None:
            return None

    class _SaverFalso:
        def __init__(self, _pool: object) -> None:
            return None

        async def setup(self) -> None:
            return None

    async def _conectar(*_a: object, **_k: object) -> _ConexaoFalsa:
        return conexao_do_schema

    from maria.shared import pool as modulo_pool

    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario@host-falso/banco")
    monkeypatch.setattr(modulo_pool, "AsyncConnectionPool", _PoolFalso)
    monkeypatch.setattr(checkpointer, "AsyncPostgresSaver", _SaverFalso)
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _conectar)

    await inicializar_checkpointer()

    assert conexao_do_schema.comandos == ['CREATE SCHEMA IF NOT EXISTS "checkpoint_py"']
    assert argumentos_do_pool["configure"] is checkpointer._fixar_search_path
    assert argumentos_do_pool["open"] is False
    kwargs = argumentos_do_pool["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["autocommit"] is True
    assert kwargs["prepare_threshold"] is None
    # O pool do checkpointer sai de shared/pool.py, com os tempos do pg de develop.
    assert argumentos_do_pool["min_size"] == 0
    assert argumentos_do_pool["max_size"] == 10
    assert argumentos_do_pool["max_idle"] == 10.0
    assert argumentos_do_pool["timeout"] == 120.0
    assert argumentos_do_pool["max_lifetime"] == math.inf

    # Duas conexões novas: cada uma recebe o próprio SET.
    primeira, segunda = _ConexaoFalsa(), _ConexaoFalsa()
    for conexao in (primeira, segunda):
        await checkpointer._fixar_search_path(conexao)  # type: ignore[arg-type]
    assert primeira.comandos == segunda.comandos == ['SET search_path TO "checkpoint_py"']


def _linhas_de_log(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(linha) for linha in capsys.readouterr().out.splitlines() if linha.strip()]


class _ConexaoSemCreate(_ConexaoFalsa):
    class info:  # imita `conexao.info` do psycopg
        dbname = "banco_do_release"
        user = "usuario_da_app"

    async def execute(self, comando: sql.Composable) -> None:
        raise psycopg.errors.InsufficientPrivilege("permission denied for database banco_do_release")


async def test_sem_permissao_de_create_registra_o_que_falta_e_relanca(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # #260: o primeiro erro de um deploy num banco novo precisa dizer o que falta
    # numa linha própria, e não só no fim do traceback. A URL tem a senha.
    async def _conectar(*_a: object, **_k: object) -> _ConexaoSemCreate:
        return _ConexaoSemCreate()

    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario_da_app:senha-secreta@host-falso/banco_do_release")
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _conectar)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await inicializar_checkpointer()

    saida = _linhas_de_log(capsys)
    [linha] = [registro for registro in saida if str(registro["msg"]).startswith("[checkpoint] sem permissão")]
    assert linha["level"] == 50
    assert linha["schema"] == SCHEMA_CHECKPOINT
    assert linha["banco"] == "banco_do_release"
    assert linha["usuario"] == "usuario_da_app"
    assert linha["permissao"] == "CREATE"
    assert linha["correcao"] == 'GRANT CREATE ON DATABASE "banco_do_release" TO "usuario_da_app";'
    assert "senha-secreta" not in json.dumps(saida)


# --- Postgres real -----------------------------------------------------------


async def _tabelas(conexao: psycopg.AsyncConnection[TupleRow], schema: str) -> set[str]:
    cursor = await conexao.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (schema,))
    return {linha[0] for linha in await cursor.fetchall()}


@pytest.fixture
async def banco() -> AsyncIterator[psycopg.AsyncConnection[TupleRow]]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("os testes postgres precisam de DATABASE_URL (no CI, o serviço Postgres)")
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conexao:
        # Estado de partida igual ao de produção no corte: as tabelas do JS em
        # public, com um registro, e nenhum schema do Python.
        await conexao.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(SCHEMA_CHECKPOINT)))
        for tabela in TABELAS_CHECKPOINT:
            await conexao.execute(sql.SQL("DROP TABLE IF EXISTS public.{}").format(sql.Identifier(tabela)))
        await conexao.execute("CREATE TABLE public.checkpoint_migrations (v INTEGER PRIMARY KEY)")
        await conexao.execute("INSERT INTO public.checkpoint_migrations (v) VALUES (0), (1), (2)")
        await conexao.execute("CREATE TABLE public.checkpoints (thread_id TEXT, sentinela TEXT)")
        await conexao.execute("INSERT INTO public.checkpoints VALUES ('thread-do-js', 'não tocar')")
        yield conexao


@pytest.mark.postgres
async def test_setup_cria_as_tabelas_so_no_schema_proprio(banco: psycopg.AsyncConnection[TupleRow]) -> None:
    saver = await inicializar_checkpointer()
    assert isinstance(saver, AsyncPostgresSaver)
    assert await _tabelas(banco, SCHEMA_CHECKPOINT) == TABELAS_CHECKPOINT


@pytest.mark.postgres
async def test_setup_nao_toca_nas_tabelas_do_js(banco: psycopg.AsyncConnection[TupleRow]) -> None:
    await inicializar_checkpointer()
    assert await _tabelas(banco, "public") >= {"checkpoint_migrations", "checkpoints"}
    assert "checkpoint_blobs" not in await _tabelas(banco, "public")
    cursor = await banco.execute("SELECT v FROM public.checkpoint_migrations ORDER BY v")
    assert [linha[0] for linha in await cursor.fetchall()] == [0, 1, 2]
    cursor = await banco.execute("SELECT thread_id, sentinela FROM public.checkpoints")
    assert await cursor.fetchall() == [("thread-do-js", "não tocar")]


@pytest.mark.postgres
async def test_grava_e_le_checkpoint_no_schema_proprio(banco: psycopg.AsyncConnection[TupleRow]) -> None:
    from typing import NotRequired, TypedDict

    from langchain_core.runnables import RunnableConfig
    from langgraph.graph import END, START, StateGraph

    class Estado(TypedDict):
        valor: NotRequired[int]

    saver = await inicializar_checkpointer()
    grafo = StateGraph(Estado).add_node("n", lambda _s: {"valor": 7}).add_edge(START, "n").add_edge("n", END).compile(checkpointer=saver)
    config: RunnableConfig = {"configurable": {"thread_id": "chat-py"}}
    entrada: Estado = {}
    await grafo.ainvoke(entrada, config)
    assert (await grafo.aget_state(config)).values == {"valor": 7}
    cursor = await banco.execute(
        sql.SQL("SELECT count(*) FROM {}.checkpoints WHERE thread_id = 'chat-py'").format(sql.Identifier(SCHEMA_CHECKPOINT))
    )
    assert (await cursor.fetchone() or (0,))[0] > 0
    cursor = await banco.execute("SELECT count(*) FROM public.checkpoints")
    assert (await cursor.fetchone() or (0,))[0] == 1


@pytest.mark.postgres
async def test_todas_as_conexoes_do_pool_usam_o_schema_proprio(banco: psycopg.AsyncConnection[TupleRow]) -> None:
    import asyncio

    from maria.shared import checkpointer

    await inicializar_checkpointer()
    pool = checkpointer._pool
    assert pool is not None
    liberar = asyncio.Event()
    todas_presas = asyncio.Event()
    caminhos: list[str] = []

    async def usar_conexao() -> None:
        # Conexões presas ao mesmo tempo obrigam o pool a criar conexões novas.
        async with pool.connection() as conexao:
            cursor = await conexao.execute("SELECT current_setting('search_path') AS sp")
            linha = await cursor.fetchone()
            assert linha is not None
            caminhos.append(linha["sp"])
            if len(caminhos) == 4:
                todas_presas.set()
            await liberar.wait()

    tarefas = [asyncio.create_task(usar_conexao()) for _ in range(4)]
    await asyncio.wait_for(todas_presas.wait(), timeout=30)
    liberar.set()
    await asyncio.gather(*tarefas)
    assert caminhos == [SCHEMA_CHECKPOINT] * 4


@pytest.mark.postgres
async def test_tabelas_existem_antes_da_primeira_requisicao(banco: psycopg.AsyncConnection[TupleRow]) -> None:
    app = criar_app()
    async with app.router.lifespan_context(app):
        # Nenhuma requisição foi feita: as tabelas vêm da inicialização, não da primeira chamada.
        assert await _tabelas(banco, SCHEMA_CHECKPOINT) == TABELAS_CHECKPOINT


@pytest.mark.postgres
async def test_usuario_sem_create_no_banco_real(
    banco: psycopg.AsyncConnection[TupleRow], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # #260, contra o Postgres de verdade: um usuário sem CREATE no banco (o
    # padrão de um usuário novo) não cria o schema, e a linha diz o que falta.
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    usuario, senha = "maria_sem_create", "senha-do-teste-260"
    await banco.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(usuario)))
    await banco.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(usuario), sql.Literal(senha)))
    try:
        url = os.environ["DATABASE_URL"]
        monkeypatch.setenv("DATABASE_URL", make_conninfo(url, user=usuario, password=senha))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await inicializar_checkpointer()
        saida = _linhas_de_log(capsys)
        [linha] = [registro for registro in saida if str(registro["msg"]).startswith("[checkpoint] sem permissão")]
        assert linha["usuario"] == usuario
        assert linha["banco"] == conninfo_to_dict(url)["dbname"]
        assert senha not in json.dumps(saida)
        assert await _tabelas(banco, SCHEMA_CHECKPOINT) == set()
    finally:
        await banco.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(usuario)))
