"""Registro das versões (#542): `fluxos_versoes` só recebe linha nova quando o hash muda.

A lógica roda aqui contra um pool falso em memória; o SQL de verdade roda no CI (`-m postgres`).
"""

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from maria.versionamento import registro
from maria.versionamento.manifesto import montar_manifesto
from maria.versionamento.registro import carregar_meta, registrar_versoes
from tests.versionamento.conftest import GRAFO, escrever

ID = "11111111-1111-1111-1111-111111111111"
META = {
    "commit_sha": "abc123",
    "tag_imagem": "sha-abc123",
    "prs": [
        {
            "numero": 10,
            "titulo": "feat: pergunta",
            "autor": "dev",
            "aprovado_por": ["Ana"],
            "solicitante": "Nicole",
            "resumo": "Pede o nome completo.",
            "issue_origem": 5,
            "areas": ["fluxo:exemplo"],
        },
        {
            "numero": 11,
            "titulo": "chore: outro",
            "autor": "dev2",
            "aprovado_por": [],
            "solicitante": "",
            "resumo": "",
            "areas": ["compartilhado"],
        },
    ],
}


class Cursor:
    def __init__(self, linhas: list[dict[str, Any]]) -> None:
        self._linhas = linhas

    async def fetchone(self) -> dict[str, Any] | None:
        return self._linhas[0] if self._linhas else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._linhas


class Conexao:
    def __init__(self, banco: "Banco") -> None:
        self._banco = banco

    async def execute(self, comando: str, params: tuple[Any, ...] = ()) -> Cursor:
        comando = " ".join(comando.split())
        if comando.startswith("SELECT hash, snapshot FROM fluxos_versoes"):
            fluxo, ambiente = params
            achadas = [r for r in self._banco.linhas if r["fluxo"] == fluxo and r["ambiente"] == ambiente]
            return Cursor([{"hash": achadas[-1]["hash"], "snapshot": achadas[-1]["snapshot"]}] if achadas else [])
        if comando.startswith("INSERT INTO fluxos_versoes"):
            nomes = (
                "fluxo nome_fluxo hash hash_anterior ambiente snapshot alteracoes resumo resumo_origem commit_sha tag_imagem pr_numero "
                "pr_titulo issue_origem autor_commit solicitante aprovado_por mudou_codigo_compartilhado prs"
            ).split()
            linha = dict(zip(nomes, params, strict=True))
            for coluna in ("snapshot", "alteracoes", "prs"):
                linha[coluna] = json.loads(linha[coluna])
            self._banco.linhas.append(linha)
        else:
            self._banco.comandos.append(comando.split("(")[0])
        return Cursor([])


class ContextoDeConexao:
    def __init__(self, banco: "Banco") -> None:
        self._banco = banco

    async def __aenter__(self) -> Conexao:
        return Conexao(self._banco)

    async def __aexit__(self, *_: object) -> None:
        return None


class Banco:
    """Pool falso: guarda as linhas inseridas e responde à consulta da última versão."""

    def __init__(self) -> None:
        self.linhas: list[dict[str, Any]] = []
        self.comandos: list[str] = []
        self.fechado = False
        self.falhar = False

    def connection(self) -> ContextoDeConexao:
        if self.falhar:
            raise RuntimeError("banco fora do ar")
        return ContextoDeConexao(self)

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        self.fechado = True


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> Banco:
    b = Banco()
    monkeypatch.setattr(registro, "criar_pool", lambda _url: b)
    return b


async def test_primeira_subida_grava_todos_os_fluxos_e_o_compartilhado(raiz: Path, banco: Banco) -> None:
    gravados = await registrar_versoes("postgresql://x", "release", montar_manifesto(raiz), META)
    assert sorted(gravados) == sorted(["compartilhado", ID, "tykhe:saude"])
    assert banco.fechado
    exemplo = next(r for r in banco.linhas if r["fluxo"] == ID)
    assert exemplo["hash_anterior"] is None and exemplo["ambiente"] == "release"
    assert exemplo["alteracoes"][0]["item"] == "fluxo"


async def test_subida_sem_mudanca_nao_grava_nada(raiz: Path, banco: Banco) -> None:
    manifesto = montar_manifesto(raiz)
    await registrar_versoes("postgresql://x", "release", manifesto, META)
    total = len(banco.linhas)
    assert await registrar_versoes("postgresql://x", "release", manifesto, META) == []
    assert len(banco.linhas) == total


async def test_mudanca_grava_so_o_fluxo_que_mudou_com_autoria_e_resumo(raiz: Path, banco: Banco) -> None:
    await registrar_versoes("postgresql://x", "release", montar_manifesto(raiz), {})
    antes = {r["fluxo"]: r for r in banco.linhas}
    escrever(raiz, "fluxos/exemplo/graph.py", GRAFO.replace("Qual o seu nome?", "Qual o nome completo?"))
    assert await registrar_versoes("postgresql://x", "release", montar_manifesto(raiz), META) == [ID]
    nova = banco.linhas[-1]
    assert nova["fluxo"] == ID and nova["hash_anterior"] == antes[ID]["hash"]
    assert nova["solicitante"] == "Nicole" and nova["aprovado_por"] == "Ana" and nova["autor_commit"] == "dev"
    assert (nova["pr_numero"], nova["issue_origem"], nova["commit_sha"], nova["tag_imagem"]) == (10, 5, "abc123", "sha-abc123")
    assert nova["resumo_origem"] == "pr" and nova["resumo"].startswith("Pede o nome completo. (")
    assert nova["mudou_codigo_compartilhado"] is False
    assert [p["numero"] for p in nova["prs"]] == [10]
    assert any(a["item"].endswith("::textos") for a in nova["alteracoes"])


async def test_sem_pr_o_resumo_e_automatico(raiz: Path, banco: Banco) -> None:
    await registrar_versoes("postgresql://x", "release", montar_manifesto(raiz), {})
    escrever(raiz, "fluxos/exemplo/graph.py", GRAFO.replace("Qual o seu nome?", "Qual o nome completo?"))
    await registrar_versoes("postgresql://x", "release", montar_manifesto(raiz), {})
    nova = banco.linhas[-1]
    assert nova["resumo_origem"] == "automatico" and nova["solicitante"] is None and nova["prs"] == []


async def test_codigo_compartilhado_marca_os_fluxos_gravados_junto(raiz: Path, banco: Banco) -> None:
    await registrar_versoes("postgresql://x", "release", montar_manifesto(raiz), {})
    escrever(raiz, "shared/util.py", "def util():\n    return 2\n")
    escrever(raiz, "fluxos/exemplo/graph.py", GRAFO.replace("Qual o seu nome?", "Qual o nome completo?"))
    await registrar_versoes("postgresql://x", "release", montar_manifesto(raiz), META)
    compartilhado, fluxo = banco.linhas[-2:]
    assert compartilhado["fluxo"] == "compartilhado" and compartilhado["mudou_codigo_compartilhado"] is False
    assert fluxo["fluxo"] == ID and fluxo["mudou_codigo_compartilhado"] is True


async def test_ambientes_tem_historias_separadas(raiz: Path, banco: Banco) -> None:
    manifesto = montar_manifesto(raiz)
    await registrar_versoes("postgresql://x", "release", manifesto, {})
    assert ID in await registrar_versoes("postgresql://x", "producao", manifesto, {})


async def test_falha_do_banco_nao_levanta_erro(raiz: Path, banco: Banco) -> None:
    banco.falhar = True
    assert await registrar_versoes("postgresql://x", "release", montar_manifesto(raiz), META) == []
    assert banco.fechado


def test_meta_da_imagem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arquivo = tmp_path / "meta.json"
    monkeypatch.setenv("MARIA_VERSAO_META", str(arquivo))
    assert carregar_meta() == {}  # arquivo ausente (build local)
    arquivo.write_text("", encoding="utf-8")
    assert carregar_meta() == {}  # build sem metadados (argumento vazio)
    arquivo.write_text('{"commit_sha": "abc"}', encoding="utf-8")
    assert carregar_meta() == {"commit_sha": "abc"}
    arquivo.write_text("[1]", encoding="utf-8")
    assert carregar_meta() == {}


@pytest.fixture
async def banco_real() -> AsyncIterator[str]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("os testes postgres precisam de DATABASE_URL (no CI, o serviço Postgres)")
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conexao:
        await conexao.execute("DROP TABLE IF EXISTS public.fluxos_versoes")
    yield url
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conexao:
        await conexao.execute("DROP TABLE IF EXISTS public.fluxos_versoes")


@pytest.mark.postgres
async def test_postgres_grava_e_so_acrescenta_quando_o_hash_muda(raiz: Path, banco_real: str) -> None:
    gravados = await registrar_versoes(banco_real, "release", montar_manifesto(raiz), META)
    assert sorted(gravados) == sorted(["compartilhado", ID, "tykhe:saude"])
    assert await registrar_versoes(banco_real, "release", montar_manifesto(raiz), META) == []
    escrever(raiz, "fluxos/exemplo/graph.py", GRAFO.replace("Qual o seu nome?", "Qual o nome completo?"))
    assert await registrar_versoes(banco_real, "release", montar_manifesto(raiz), META) == [ID]
    async with await psycopg.AsyncConnection.connect(banco_real, autocommit=True) as conexao:
        cursor = await conexao.execute(
            "SELECT hash_anterior IS NOT NULL, solicitante, resumo_origem, jsonb_array_length(alteracoes), prs->0->>'numero' "
            "FROM fluxos_versoes WHERE fluxo = %s ORDER BY id DESC LIMIT 1",
            (ID,),
        )
        linha = await cursor.fetchone()
        assert linha is not None and linha[0] is True and linha[1] == "Nicole" and linha[2] == "pr" and linha[3] >= 1 and linha[4] == "10"
        total = await (await conexao.execute("SELECT count(*) FROM fluxos_versoes WHERE fluxo = %s", (ID,))).fetchone()
        assert total is not None and total[0] == 2
