"""`seed_fluxos_planejados.py` (spec 08, seção 3.2 e testes 4 e 5 da seção 6).

Develop não tem teste deste script. O `validar()` é provocado com cópias alteradas dos dados;
o arquivo de dados real não muda.
"""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import TupleRow

import seed_fluxos_planejados as seed_mod
from maria.fluxos import ID_VIOLENCIA_DOMESTICA
from maria.shared.fluxos_planejados_db import FluxoPlanejado, listar_fluxos_planejados


@pytest.fixture
def dados() -> list[FluxoPlanejado]:
    return copy.deepcopy(seed_mod.carregar_dados())


def _mensagem(dados: list[FluxoPlanejado]) -> str:
    with pytest.raises(seed_mod.ErroSeed) as erro:
        seed_mod.validar(dados)
    return str(erro.value)


def test_os_74_registros_passam(dados: list[FluxoPlanejado]) -> None:
    seed_mod.validar(dados)


def test_categoria_de_fluxo_implementado(dados: list[FluxoPlanejado]) -> None:
    dados[3]["idCategoriaAssuntoVerde"] = 10113  # violência doméstica
    assert _mensagem(dados) == f"{dados[3]['nome']} (idCategoriaAssuntoVerde 10113) duplica um fluxo já implementado"


def test_categoria_repetida_no_seed(dados: list[FluxoPlanejado]) -> None:
    dados[5]["idCategoriaAssuntoVerde"] = dados[2]["idCategoriaAssuntoVerde"]
    categoria = dados[2]["idCategoriaAssuntoVerde"]
    assert _mensagem(dados) == f"idCategoriaAssuntoVerde {categoria} repetido dentro do próprio seed ({dados[5]['nome']})"


@pytest.mark.parametrize("descricao", ["", "   ", " ﻿", "\n\t"])
def test_descricao_vazia_pelo_trim_do_js(dados: list[FluxoPlanejado], descricao: str) -> None:
    dados[7]["descricao"] = descricao
    assert _mensagem(dados) == f"{dados[7]['nome']} está com descricao vazia"


def test_descricao_so_com_separador_nao_e_vazia_no_js(dados: list[FluxoPlanejado]) -> None:
    # \x1c não é espaço para o trim() do JS, mas é para o str.strip() do Python.
    dados[7]["descricao"] = "\x1c"
    seed_mod.validar(dados)


def test_uuid_repetido(dados: list[FluxoPlanejado]) -> None:
    dados[9]["id"] = dados[1]["id"]
    assert _mensagem(dados) == f"uuid {dados[1]['id']} repetido dentro do seed ({dados[9]['nome']})"


def test_uuid_de_fluxo_implementado(dados: list[FluxoPlanejado]) -> None:
    dados[4]["id"] = ID_VIOLENCIA_DOMESTICA
    assert _mensagem(dados) == f"{ID_VIOLENCIA_DOMESTICA} colide com um fluxo já implementado"


def test_palavras_chave_que_nao_sao_lista(dados: list[FluxoPlanejado]) -> None:
    dados[6]["palavrasChave"] = "pensão"  # type: ignore[typeddict-item]
    assert _mensagem(dados) == f"{dados[6]['nome']} deveria ter palavrasChave como array"


def test_contagem_diferente_de_74(dados: list[FluxoPlanejado]) -> None:
    assert _mensagem(dados[:73]) == "esperava 74 registros no seed, achou 73 — dado mudou? confirmar antes de seguir"


def test_contagem_e_checada_depois_dos_registros(dados: list[FluxoPlanejado]) -> None:
    dados[0]["descricao"] = ""
    assert _mensagem(dados[:73]) == f"{dados[0]['nome']} está com descricao vazia"


def test_ordem_das_checagens_dentro_do_registro(dados: list[FluxoPlanejado]) -> None:
    # Categoria repetida e descrição vazia no mesmo registro: a categoria vem primeiro.
    dados[5]["idCategoriaAssuntoVerde"] = dados[2]["idCategoriaAssuntoVerde"]
    dados[5]["descricao"] = ""
    assert "repetido dentro do próprio seed" in _mensagem(dados)


def test_sem_database_url(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("DATABASE_URL", "")  # definida e vazia: o load_dotenv não a substitui
    assert seed_mod.main() == 1
    captura = capsys.readouterr()
    # B5: como em develop, o checkpointer nasce antes da guarda do seed e loga o aviso do MemorySaver.
    (linha,) = captura.out.splitlines()
    assert json.loads(linha)["level"] == 40
    assert json.loads(linha)["msg"] == "[checkpoint] DATABASE_URL ausente — usando MemorySaver (não persiste)"
    assert captura.err.splitlines()[0] == "seed falhou: Error: DATABASE_URL obrigatório pra rodar o seed"


def _checkpointer_falso(monkeypatch: pytest.MonkeyPatch, ordem: list[str], erro: Exception | None = None) -> None:
    async def inicializar() -> None:
        ordem.append("checkpointer")
        if erro is not None:
            raise erro

    async def fechar() -> None:
        ordem.append("fechar checkpointer")

    monkeypatch.setattr(seed_mod, "inicializar_checkpointer", inicializar)
    monkeypatch.setattr(seed_mod, "fechar_checkpointer", fechar)


def test_valida_antes_de_conectar(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], dados: list[FluxoPlanejado]) -> None:
    # Ordem de develop: checkpointer (na importação dos fluxos), validar(), e só então a conexão do seed.
    ordem: list[str] = []
    _checkpointer_falso(monkeypatch, ordem)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ninguem@127.0.0.1:1/nada")
    monkeypatch.setattr(seed_mod, "carregar_dados", lambda: dados[:73])
    assert seed_mod.main() == 1
    assert ordem == ["checkpointer", "fechar checkpointer"]
    assert capsys.readouterr().err.splitlines()[0] == (
        "seed falhou: Error: esperava 74 registros no seed, achou 73 — dado mudou? confirmar antes de seguir"
    )


def test_falha_do_checkpointer_escapa_sem_o_prefixo(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # B5: em develop, a falha vem do top-level await da importação, fora do `.catch` do seed.
    ordem: list[str] = []
    _checkpointer_falso(monkeypatch, ordem, ConnectionRefusedError("connect ECONNREFUSED 127.0.0.1:1"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://ninguem@127.0.0.1:1/nada")
    with pytest.raises(ConnectionRefusedError):
        seed_mod.main()
    assert ordem == ["checkpointer"]
    assert "seed falhou" not in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="o libpq do Windows não percebe a conexão recusada sem connect_timeout")
def test_banco_inalcancavel_morre_na_hora_sem_o_prefixo() -> None:
    # B5 de ponta a ponta, com o processo de verdade, como o `node scripts/seedFluxosPlanejados.ts` de develop.
    env = {**os.environ, "DATABASE_URL": "postgresql://ninguem@127.0.0.1:1/nada"}
    script = Path(seed_mod.__file__)
    r = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 1
    assert "seed falhou" not in r.stderr
    assert "OperationalError" in r.stderr


@pytest.mark.postgres
async def test_seed_duas_vezes_no_postgres(banco_de_negocio: psycopg.AsyncConnection[TupleRow], capsys: pytest.CaptureFixture[str]) -> None:
    dados = seed_mod.carregar_dados()
    for _ in range(2):
        await seed_mod.seed(dados)
    assert capsys.readouterr().out.splitlines() == ["seed concluído: 74 fluxos planejados inseridos/atualizados em fluxos_planejados"] * 2

    cursor = await banco_de_negocio.execute(
        "SELECT id, nome, descricao, id_categoria_assunto_verde, palavras_chave, mensagem_fixa FROM fluxos_planejados"
    )
    linhas = {linha[0]: linha for linha in await cursor.fetchall()}
    assert len(linhas) == 74
    for f in dados:
        assert linhas[f["id"]] == (
            f["id"],
            f["nome"],
            f["descricao"],
            f["idCategoriaAssuntoVerde"],
            f["palavrasChave"],
            f.get("mensagemFixa"),
        )
    vazias = [linha for linha in linhas.values() if linha[4] == []]
    assert len(vazias) == 4
    assert sum(linha[5] is None for linha in linhas.values()) == 72

    planejados = await listar_fluxos_planejados()
    assert sorted(f["id"] for f in planejados) == sorted(linhas)


@pytest.mark.postgres
async def test_seed_desfaz_edicao_manual_da_mensagem_fixa(banco_de_negocio: psycopg.AsyncConnection[TupleRow]) -> None:
    # Achado B2 (#253), reproduzido de propósito: a régua é develop.
    dados = seed_mod.carregar_dados()
    await seed_mod.seed(dados)
    sem_mensagem = next(f for f in dados if "mensagemFixa" not in f)
    await banco_de_negocio.execute("UPDATE fluxos_planejados SET mensagem_fixa = 'editada à mão' WHERE id = %s", (sem_mensagem["id"],))
    await seed_mod.seed(dados)
    cursor = await banco_de_negocio.execute("SELECT mensagem_fixa FROM fluxos_planejados WHERE id = %s", (sem_mensagem["id"],))
    assert await cursor.fetchone() == (None,)
