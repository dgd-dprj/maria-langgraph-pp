"""`seed_fluxos_planejados.py` (spec 08, seção 3.2 e testes 4 e 5 da seção 6).

Develop não tem teste deste script. O `validar()` é provocado com cópias alteradas dos dados;
o arquivo de dados real não muda.
"""

import asyncio
import copy
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


# #255 (decisão da Nicole, 2026-11-17): o seed não inicializa mais o checkpointer do LangGraph. Em develop, a importação
# dos fluxos criava as tabelas de checkpoint e, com o banco fora, matava o processo antes do "seed falhou:" (B5).


def _checkpointer_proibido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qualquer chamada ao checkpointer quebra o teste: o seed não deve tocar nele."""

    async def proibido() -> None:
        raise AssertionError("o seed não pode inicializar o checkpointer (#255)")

    from maria.shared import checkpointer

    monkeypatch.setattr(checkpointer, "inicializar_checkpointer", proibido)
    monkeypatch.setattr(checkpointer, "fechar_checkpointer", proibido)


def test_sem_database_url(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _checkpointer_proibido(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "")  # definida e vazia: o load_dotenv não a substitui
    assert seed_mod.main() == 1
    captura = capsys.readouterr()
    # Sem a linha do MemorySaver no stdout: o checkpointer não nasce mais.
    assert captura.out == ""
    assert captura.err.splitlines()[0] == "seed falhou: Error: DATABASE_URL obrigatório pra rodar o seed"


def test_valida_antes_de_conectar(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], dados: list[FluxoPlanejado]) -> None:
    # validar() vem antes da conexão do seed, e nada do checkpointer acontece.
    _checkpointer_proibido(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ninguem@127.0.0.1:1/nada")
    monkeypatch.setattr(seed_mod, "carregar_dados", lambda: dados[:73])
    assert seed_mod.main() == 1
    assert capsys.readouterr().err.splitlines()[0] == (
        "seed falhou: Error: esperava 74 registros no seed, achou 73 — dado mudou? confirmar antes de seguir"
    )


def test_banco_inalcancavel_sai_com_o_prefixo_do_seed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # A falha da conexão passa pelo "seed falhou:" e dá código 1 (antes, escapava sem o prefixo).
    _checkpointer_proibido(monkeypatch)

    async def recusa(*_: object, **__: object) -> None:
        raise ConnectionRefusedError("connect ECONNREFUSED 127.0.0.1:1")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", recusa)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ninguem@127.0.0.1:1/nada")
    assert seed_mod.main() == 1
    assert capsys.readouterr().err.splitlines()[0] == "seed falhou: ConnectionRefusedError: connect ECONNREFUSED 127.0.0.1:1"


@pytest.mark.skipif(sys.platform == "win32", reason="o libpq do Windows não percebe a conexão recusada sem connect_timeout")
def test_banco_inalcancavel_com_o_processo_de_verdade() -> None:
    env = {**os.environ, "DATABASE_URL": "postgresql://ninguem@127.0.0.1:1/nada"}
    script = Path(seed_mod.__file__)
    r = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 1
    assert r.stderr.startswith("seed falhou: OperationalError")
    assert "MemorySaver" not in r.stdout


@pytest.mark.postgres
async def test_seed_nao_cria_tabela_de_checkpoint(
    banco_de_negocio: psycopg.AsyncConnection[TupleRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    # #255: rodar o seed de ponta a ponta (main) não cria o schema nem as tabelas de checkpoint do LangGraph.
    await banco_de_negocio.execute("DROP SCHEMA IF EXISTS checkpoint_py CASCADE")
    monkeypatch.setattr(seed_mod, "load_dotenv", lambda: None)
    assert await asyncio.to_thread(seed_mod.main) == 0
    # Só o schema do checkpointer do Python: `tests/shared/test_checkpointer.py` deixa em `public`, de propósito, as
    # tabelas `checkpoints` e `checkpoint_migrations` da versão em TypeScript (o estado da produção no corte), e elas
    # não são do seed. Contar `checkpoint%` em qualquer schema fazia este teste falhar conforme a ordem (#453).
    cursor = await banco_de_negocio.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'checkpoint_py'")
    linha = await cursor.fetchone()
    assert linha is not None and linha[0] == 0


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


# #253 (decisão da Nicole, 2026-11-18): o arquivo vale. Com o banco diferente, o seed mostra a diferença e não grava
# nada; `--force` sobrescreve. Em develop (achado B2), a edição feita à mão sumia sem aviso.


def test_comparar_acha_cada_coluna_diferente(dados: list[FluxoPlanejado]) -> None:
    a, b, c = dados[0], dados[1], dados[2]
    no_banco: dict[str, dict[str, object]] = {
        f["id"]: {
            "nome": f["nome"],
            "descricao": f["descricao"],
            "id_categoria_assunto_verde": f["idCategoriaAssuntoVerde"],
            "palavras_chave": list(f["palavrasChave"]),
            "mensagem_fixa": f.get("mensagemFixa"),
        }
        for f in (a, b)
    }
    no_banco[a["id"]]["mensagem_fixa"] = "corrigida no banco"
    no_banco[b["id"]]["palavras_chave"] = [*b["palavrasChave"][1:], "palavra só do banco"]
    # O registro `c` não está no banco: entra sem sobrescrever nada.
    diferencas = seed_mod.comparar(no_banco, [a, b, c])
    assert [(d.id, d.coluna) for d in diferencas] == [(a["id"], "mensagem_fixa"), (b["id"], "palavras_chave")]
    assert diferencas[0].detalhe == "banco «corrigida no banco» / arquivo (vazio)"
    assert diferencas[1].detalhe == f"o arquivo traz {b['palavrasChave'][0]}; o banco tem a mais palavra só do banco"


def test_comparar_sem_diferenca_quando_o_banco_e_igual(dados: list[FluxoPlanejado]) -> None:
    no_banco: dict[str, dict[str, object]] = {
        f["id"]: {
            "nome": f["nome"],
            "descricao": f["descricao"],
            "id_categoria_assunto_verde": f["idCategoriaAssuntoVerde"],
            "palavras_chave": list(f["palavrasChave"]),
            "mensagem_fixa": f.get("mensagemFixa"),
        }
        for f in dados
    }
    assert seed_mod.comparar(no_banco, dados) == []


def test_argumento_desconhecido(capsys: pytest.CaptureFixture[str]) -> None:
    assert seed_mod.main(["--forca"]) == 2
    assert capsys.readouterr().err == "seed falhou: Error: argumento desconhecido: --forca (o único aceito é --force)\n"


async def _valor(banco: psycopg.AsyncConnection[TupleRow], coluna: str, id_: str) -> object:
    cursor = await banco.execute(f"SELECT {coluna} FROM fluxos_planejados WHERE id = %s", (id_,))
    linha = await cursor.fetchone()
    assert linha is not None
    return linha[0]


@pytest.mark.postgres
async def test_seed_recusa_sobrescrever_e_mostra_a_diferenca(
    banco_de_negocio: psycopg.AsyncConnection[TupleRow], capsys: pytest.CaptureFixture[str]
) -> None:
    # O cenário BDD da issue: a mensagem fixa corrigida no banco, o seed com o texto antigo.
    dados = seed_mod.carregar_dados()
    await seed_mod.seed(dados)
    capsys.readouterr()
    editado = next(f for f in dados if "mensagemFixa" not in f)
    await banco_de_negocio.execute("UPDATE fluxos_planejados SET mensagem_fixa = 'corrigida à mão' WHERE id = %s", (editado["id"],))
    # E o arquivo mudou outro registro: se o seed gravasse alguma coisa, essa mudança entraria.
    novo_arquivo = copy.deepcopy(dados)
    outro = next(f for f in novo_arquivo if f["id"] != editado["id"])
    descricao_antiga = outro["descricao"]
    outro["descricao"] = "descrição nova só no arquivo"

    with pytest.raises(seed_mod.ErroSeed) as erro:
        await seed_mod.seed(novo_arquivo)

    assert "o banco difere do arquivo em 2 registro(s); nada foi gravado" in str(erro.value)
    assert "--force" in str(erro.value)
    saida = capsys.readouterr()
    assert saida.out == ""
    linhas = saida.err.splitlines()
    assert linhas[0] == "o banco difere do arquivo em 2 registro(s), 2 coluna(s):"
    trecho_antigo = descricao_antiga[:80] + ("…" if len(descricao_antiga) > 80 else "")
    assert sorted(linhas[1:]) == sorted(
        [
            f"  - {editado['nome']} ({editado['id']}), mensagem_fixa: banco «corrigida à mão» / arquivo (vazio)",
            f"  - {outro['nome']} ({outro['id']}), descricao: banco «{trecho_antigo}» / arquivo «descrição nova só no arquivo»",
        ]
    )
    # Nada foi gravado: a correção à mão ficou, e a mudança do arquivo não entrou.
    assert await _valor(banco_de_negocio, "mensagem_fixa", editado["id"]) == "corrigida à mão"
    assert await _valor(banco_de_negocio, "descricao", outro["id"]) == descricao_antiga


@pytest.mark.postgres
async def test_seed_com_force_sobrescreve(banco_de_negocio: psycopg.AsyncConnection[TupleRow], capsys: pytest.CaptureFixture[str]) -> None:
    dados = seed_mod.carregar_dados()
    await seed_mod.seed(dados)
    editado = next(f for f in dados if "mensagemFixa" not in f)
    await banco_de_negocio.execute("UPDATE fluxos_planejados SET mensagem_fixa = 'corrigida à mão' WHERE id = %s", (editado["id"],))
    capsys.readouterr()
    await seed_mod.seed(dados, forcar=True)
    saida = capsys.readouterr()
    assert "--force: sobrescrevendo 1 registro(s) com o valor do arquivo" in saida.err
    assert saida.out.splitlines() == ["seed concluído: 74 fluxos planejados inseridos/atualizados em fluxos_planejados"]
    assert await _valor(banco_de_negocio, "mensagem_fixa", editado["id"]) is None


@pytest.mark.postgres
async def test_seed_pela_linha_de_comando_recusa_e_aceita_force(
    banco_de_negocio: psycopg.AsyncConnection[TupleRow], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(seed_mod, "load_dotenv", lambda: None)
    assert await asyncio.to_thread(seed_mod.main, []) == 0
    editado = next(f for f in seed_mod.carregar_dados() if "mensagemFixa" not in f)
    await banco_de_negocio.execute("UPDATE fluxos_planejados SET nome = 'renomeado à mão' WHERE id = %s", (editado["id"],))
    capsys.readouterr()
    assert await asyncio.to_thread(seed_mod.main, []) == 1
    erro = capsys.readouterr().err
    assert f"  - renomeado à mão ({editado['id']}), nome:" not in erro  # o nome mostrado é o do arquivo
    assert f"({editado['id']}), nome: banco «renomeado à mão» / arquivo «{editado['nome']}»" in erro
    assert "seed falhou: Error: o banco difere do arquivo em 1 registro(s); nada foi gravado." in erro
    assert await _valor(banco_de_negocio, "nome", editado["id"]) == "renomeado à mão"
    assert await asyncio.to_thread(seed_mod.main, ["--force"]) == 0
    assert await _valor(banco_de_negocio, "nome", editado["id"]) == editado["nome"]


@pytest.mark.postgres
async def test_seed_nao_toca_em_registro_que_so_existe_no_banco(
    banco_de_negocio: psycopg.AsyncConnection[TupleRow], capsys: pytest.CaptureFixture[str]
) -> None:
    dados = seed_mod.carregar_dados()
    await seed_mod.seed(dados)
    await banco_de_negocio.execute(
        "INSERT INTO fluxos_planejados (id, nome, descricao, id_categoria_assunto_verde) VALUES ('so-no-banco', 'x', 'y', 999999)"
    )
    capsys.readouterr()
    await seed_mod.seed(dados)
    saida = capsys.readouterr()
    assert saida.err == "aviso: 1 registro(s) só no banco, que o seed não toca: so-no-banco\n"
    assert await _valor(banco_de_negocio, "nome", "so-no-banco") == "x"
