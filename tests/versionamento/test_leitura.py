"""A leitura das versões (#547): lista explícita de colunas, só SELECT, datas em texto."""

from datetime import UTC, datetime
from typing import Any

import pytest

from maria.versionamento import leitura


class _Cursor:
    def __init__(self, linhas: list[dict[str, Any]]) -> None:
        self.linhas = linhas

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.linhas

    async def fetchone(self) -> dict[str, Any] | None:
        return self.linhas[0] if self.linhas else None


class _Conexao:
    def __init__(self, sqls: list[str], linha: dict[str, Any]) -> None:
        self.sqls, self.linha = sqls, linha

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self.sqls.append(sql)
        return _Cursor([self.linha])

    async def __aenter__(self) -> "_Conexao":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class _Pool:
    def __init__(self, conexao: _Conexao) -> None:
        self.conexao, self.fechado = conexao, False

    async def open(self) -> None:
        return None

    def connection(self) -> _Conexao:
        return self.conexao

    async def close(self) -> None:
        self.fechado = True


LINHA = {
    **{coluna: None for coluna, _ in leitura.CAMPOS_DA_LISTA},
    "id": 3,
    "fluxo": "f1",
    "nome_fluxo": "pessoa-presa",
    "ambiente": "producao",
    "hash": "h",
    "registrado_em": datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
    "alteracoes": [],
    "mudou_codigo_compartilhado": False,
    "snapshot": {"a": 1},
}


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> tuple[_Pool, list[str]]:
    sqls: list[str] = []
    p = _Pool(_Conexao(sqls, LINHA))
    monkeypatch.setattr(leitura, "criar_pool", lambda _url: p)
    return p, sqls


async def test_listar_devolve_campos_em_camel_e_data_em_texto(pool: tuple[_Pool, list[str]]) -> None:
    p, sqls = pool
    dados = await leitura.listar("postgresql://x", None, None, 10)
    versao = dados["versoes"][0]
    assert versao["nomeFluxo"] == "pessoa-presa" and versao["registradoEm"].startswith("2026-11-23T12:00")
    assert "snapshot" not in versao
    assert dados["emVigor"][0]["id"] == 3
    assert p.fechado
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in sqls)
    assert all("SELECT *" not in sql for sql in sqls)


async def test_buscar_traz_snapshot_e_none_quando_nao_existe(pool: tuple[_Pool, list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    assert (await leitura.buscar("postgresql://x", 3))["snapshot"] == {"a": 1}  # type: ignore[index]

    vazio = _Pool(_Conexao([], LINHA))
    vazio.conexao.execute = lambda *_a, **_k: _async(_Cursor([]))  # type: ignore[method-assign,assignment]
    monkeypatch.setattr(leitura, "criar_pool", lambda _url: vazio)
    assert await leitura.buscar("postgresql://x", 99) is None


async def _async(valor: Any) -> Any:
    return valor
