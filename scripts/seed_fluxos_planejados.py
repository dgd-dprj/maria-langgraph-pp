"""Script de migração ÚNICO (issue #26): popula a tabela `fluxos_planejados`
(shared/fluxos_planejados_db.py) com os 74 registros que antes viviam no código
(src/fluxos/catalogo.ts, removido depois desta migração; o PR #24 trouxe a
origem desses dados: 71 de GET /integra/assunto/categorias e 3 achados só na
planilha de palavras-chave).

Os registros estão em `scripts/dados/fluxos_planejados.json`, extraídos do
literal de develop e verificados contra ele (spec 08, seção 2.3).

Uso: `uv run python scripts/seed_fluxos_planejados.py [--force]` (precisa de
DATABASE_URL no ambiente ou no .env).

#253 (decisão da Nicole, 2026-11-18): **o arquivo vale.** Antes de gravar, o seed
compara o banco com o arquivo. Se algum dos 74 registros estiver diferente (nome,
descrição, categoria, palavras-chave ou mensagem fixa), ele mostra a diferença e
**não grava nada**. `--force` grava mesmo assim, quando a sobrescrita é intencional.
A gravação é uma transação só: entram os 74 registros, ou nenhum.
"""

import asyncio
import io
import json
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import psycopg
from dotenv import load_dotenv

from maria.fluxos import fluxos_por_id
from maria.shared._js import trim_js
from maria.shared.fluxos_planejados_db import FluxoPlanejado

DADOS = Path(__file__).resolve().parent / "dados" / "fluxos_planejados.json"


class ErroSeed(Exception):
    """O `throw new Error(...)` de develop: sai no console como `Error: <mensagem>`."""


def carregar_dados() -> list[FluxoPlanejado]:
    return cast(list[FluxoPlanejado], json.loads(DADOS.read_bytes().decode("utf-8")))


def validar(dados: list[FluxoPlanejado]) -> None:
    """Mesmas checagens que antes viviam em fluxos/catalogo.test.ts, na mesma ordem.
    Faz sentido rodar uma vez aqui (dado estático, migrado uma vez) em vez de
    manter uma suíte perpétua sobre uma tabela que passa a ser editada por SQL."""
    ids_implementados = {f.id_categoria_assunto_verde for f in fluxos_por_id.values() if f.id_categoria_assunto_verde is not None}
    ids_vistos: set[str] = set()
    categorias_vistas: set[int] = set()
    for f in dados:
        if f["idCategoriaAssuntoVerde"] in ids_implementados:
            raise ErroSeed(f"{f['nome']} (idCategoriaAssuntoVerde {f['idCategoriaAssuntoVerde']}) duplica um fluxo já implementado")
        if f["idCategoriaAssuntoVerde"] in categorias_vistas:
            raise ErroSeed(f"idCategoriaAssuntoVerde {f['idCategoriaAssuntoVerde']} repetido dentro do próprio seed ({f['nome']})")
        categorias_vistas.add(f["idCategoriaAssuntoVerde"])
        if len(trim_js(f["descricao"])) == 0:
            raise ErroSeed(f"{f['nome']} está com descricao vazia")
        if f["id"] in ids_vistos:
            raise ErroSeed(f"uuid {f['id']} repetido dentro do seed ({f['nome']})")
        # Em develop é `f.id in fluxosPorId`, que também acharia propriedades herdadas
        # ("constructor", "toString"); com 74 UUIDs fixos, a diferença não tem efeito.
        if f["id"] in fluxos_por_id:
            raise ErroSeed(f"{f['id']} colide com um fluxo já implementado")
        ids_vistos.add(f["id"])
        if not isinstance(f["palavrasChave"], list):
            raise ErroSeed(f"{f['nome']} deveria ter palavrasChave como array")
    if len(dados) != 74:
        raise ErroSeed(f"esperava 74 registros no seed, achou {len(dados)} — dado mudou? confirmar antes de seguir")


COLUNAS: tuple[tuple[str, str], ...] = (
    ("nome", "nome"),
    ("descricao", "descricao"),
    ("id_categoria_assunto_verde", "idCategoriaAssuntoVerde"),
    ("palavras_chave", "palavrasChave"),
    ("mensagem_fixa", "mensagemFixa"),
)
TAMANHO_DO_TRECHO = 80


@dataclass(frozen=True)
class Diferenca:
    id: str
    nome: str
    coluna: str
    detalhe: str


def _trecho(valor: Any) -> str:
    if valor is None:
        return "(vazio)"
    texto = str(valor)
    return f"«{texto[:TAMANHO_DO_TRECHO]}…»" if len(texto) > TAMANHO_DO_TRECHO else f"«{texto}»"


def _detalhe(coluna: str, no_banco: Any, no_arquivo: Any) -> str:
    if coluna == "palavras_chave":
        banco, arquivo = list(no_banco or []), list(no_arquivo or [])
        entram = [p for p in arquivo if p not in banco]
        saem = [p for p in banco if p not in arquivo]
        partes = []
        if entram:
            partes.append("o arquivo traz " + ", ".join(entram))
        if saem:
            partes.append("o banco tem a mais " + ", ".join(saem))
        return "; ".join(partes) or "mesmas palavras em outra ordem"
    return f"banco {_trecho(no_banco)} / arquivo {_trecho(no_arquivo)}"


def comparar(no_banco: dict[str, dict[str, Any]], dados: list[FluxoPlanejado]) -> list[Diferenca]:
    """O que o seed sobrescreveria: cada registro do arquivo que já existe no banco com alguma coluna diferente."""
    diferencas: list[Diferenca] = []
    for f in dados:
        linha = no_banco.get(f["id"])
        if linha is None:
            continue  # registro novo: entra sem sobrescrever nada
        arquivo = cast(dict[str, Any], f)
        for coluna, campo in COLUNAS:
            valor_arquivo = arquivo.get(campo)
            if linha[coluna] != valor_arquivo:
                diferencas.append(Diferenca(f["id"], f["nome"], coluna, _detalhe(coluna, linha[coluna], valor_arquivo)))
    return diferencas


def _mostrar(diferencas: list[Diferenca]) -> None:
    registros = len({d.id for d in diferencas})
    print(f"o banco difere do arquivo em {registros} registro(s), {len(diferencas)} coluna(s):", file=sys.stderr)
    for d in diferencas:
        print(f"  - {d.nome} ({d.id}), {d.coluna}: {d.detalhe}", file=sys.stderr)


async def seed(dados: list[FluxoPlanejado], *, forcar: bool = False) -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ErroSeed("DATABASE_URL obrigatório pra rodar o seed")

    validar(dados)

    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conexao:
        await conexao.execute(
            """
    CREATE TABLE IF NOT EXISTS fluxos_planejados (
      id TEXT PRIMARY KEY,
      nome TEXT NOT NULL,
      descricao TEXT NOT NULL,
      id_categoria_assunto_verde INTEGER NOT NULL,
      palavras_chave TEXT[] NOT NULL DEFAULT '{}'
    )
  """
        )
        # Issue #22: coluna nova numa tabela que já existe (issue #26).
        await conexao.execute("ALTER TABLE fluxos_planejados ADD COLUMN IF NOT EXISTS mensagem_fixa TEXT")

        # #253: a comparação e a gravação ficam na mesma transação, com as linhas travadas: ninguém muda o banco entre
        # o que o seed comparou e o que ele grava. Uma falha no meio desfaz tudo.
        async with conexao.transaction():
            cursor = await conexao.execute(
                "SELECT id, nome, descricao, id_categoria_assunto_verde, palavras_chave, mensagem_fixa FROM fluxos_planejados FOR UPDATE"
            )
            colunas = [c.name for c in cursor.description or []]
            no_banco = {linha[0]: dict(zip(colunas, linha, strict=True)) for linha in await cursor.fetchall()}
            diferencas = comparar(no_banco, dados)
            so_no_banco = sorted(set(no_banco) - {f["id"] for f in dados})
            if so_no_banco:
                # O seed não apaga nada: um registro que só existe no banco continua como está.
                print(f"aviso: {len(so_no_banco)} registro(s) só no banco, que o seed não toca: {', '.join(so_no_banco)}", file=sys.stderr)
            if diferencas:
                _mostrar(diferencas)
                if not forcar:
                    raise ErroSeed(
                        f"o banco difere do arquivo em {len({d.id for d in diferencas})} registro(s); nada foi gravado. "
                        "O arquivo vale (#253): leve a mudança para scripts/dados/fluxos_planejados.json por PR, "
                        "ou rode com --force para sobrescrever o banco de propósito"
                    )
                print(f"--force: sobrescrevendo {len({d.id for d in diferencas})} registro(s) com o valor do arquivo", file=sys.stderr)

            for f in dados:
                await conexao.execute(
                    """INSERT INTO fluxos_planejados (id, nome, descricao, id_categoria_assunto_verde, palavras_chave, mensagem_fixa)
       VALUES (%(id)s, %(nome)s, %(descricao)s, %(categoria)s, %(palavras)s, %(fixa)s)
       ON CONFLICT (id) DO UPDATE SET nome = %(nome)s, descricao = %(descricao)s,
         id_categoria_assunto_verde = %(categoria)s, palavras_chave = %(palavras)s, mensagem_fixa = %(fixa)s""",
                    {
                        "id": f["id"],
                        "nome": f["nome"],
                        "descricao": f["descricao"],
                        "categoria": f["idCategoriaAssuntoVerde"],
                        "palavras": f["palavrasChave"],
                        "fixa": f.get("mensagemFixa"),
                    },
                )

    print(f"seed concluído: {len(dados)} fluxos planejados inseridos/atualizados em fluxos_planejados")


async def _executar(forcar: bool = False) -> int:
    # #255 (decisão da Nicole, 2026-11-17): o seed não inicializa mais o checkpointer do LangGraph. Em develop
    # (TypeScript), importar os fluxos já criava as tabelas de checkpoint e, com o banco fora, matava o processo
    # antes do "seed falhou:"; a tradução reproduzia isso de propósito. Agora qualquer falha passa pelo prefixo do seed.
    try:
        await seed(carregar_dados(), forcar=forcar)
    except Exception as erro:
        # `console.error("seed falhou:", erro)` do Node: primeira linha `<nome>: <mensagem>`,
        # seguida da pilha. A pilha é a do Python (spec 08, D-4).
        nome = "Error" if isinstance(erro, ErroSeed) else type(erro).__name__
        print(f"seed falhou: {nome}: {erro}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """`argv` são os argumentos da linha de comando (sem o nome do script); só a execução direta passa `sys.argv`."""
    argumentos = argv or []
    desconhecidos = [a for a in argumentos if a != "--force"]
    if desconhecidos:
        print(f"seed falhou: Error: argumento desconhecido: {' '.join(desconhecidos)} (o único aceito é --force)", file=sys.stderr)
        return 2
    load_dotenv()
    return asyncio.run(_executar(forcar="--force" in argumentos))


if __name__ == "__main__":
    # O console.* do Node escreve sempre em UTF-8; o Python, com a saída redirecionada no
    # Windows, usaria a página de código local e trocaria os acentos.
    for fluxo in (sys.stdout, sys.stderr):
        if isinstance(fluxo, io.TextIOWrapper):
            fluxo.reconfigure(encoding="utf-8")
    if sys.platform == "win32":
        # O psycopg assíncrono não funciona com o loop padrão do Windows (ver tests/conftest.py).
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(main(sys.argv[1:]))
