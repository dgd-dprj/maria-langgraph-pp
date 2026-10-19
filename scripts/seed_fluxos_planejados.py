"""Script de migração ÚNICO (issue #26): popula a tabela `fluxos_planejados`
(shared/fluxos_planejados_db.py) com os 74 registros que antes viviam no código
(src/fluxos/catalogo.ts, removido depois desta migração; o PR #24 trouxe a
origem desses dados: 71 de GET /integra/assunto/categorias e 3 achados só na
planilha de palavras-chave).

Os registros estão em `scripts/dados/fluxos_planejados.json`, extraídos do
literal de develop e verificados contra ele (spec 08, seção 2.3).

Uso: `uv run python scripts/seed_fluxos_planejados.py` (precisa de DATABASE_URL
no ambiente ou no .env).

Atenção (#253): o seed sobrescreve nome, descrição, palavras-chave e
mensagem_fixa de todos os 74 registros com o valor do arquivo. Uma edição feita
à mão no banco, inclusive em `mensagem_fixa` (#249), some na próxima execução.
"""

import asyncio
import io
import json
import os
import sys
import traceback
from pathlib import Path
from typing import cast

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


async def seed(dados: list[FluxoPlanejado]) -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ErroSeed("DATABASE_URL obrigatório pra rodar o seed")

    validar(dados)

    # Como o pool.query de develop: cada comando no próprio autocommit, sem transação.
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


def main() -> int:
    load_dotenv()
    try:
        asyncio.run(seed(carregar_dados()))
    except Exception as erro:
        # `console.error("seed falhou:", erro)` do Node: primeira linha `<nome>: <mensagem>`,
        # seguida da pilha. A pilha é a do Python (spec 08, D-4).
        nome = "Error" if isinstance(erro, ErroSeed) else type(erro).__name__
        print(f"seed falhou: {nome}: {erro}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # O console.* do Node escreve sempre em UTF-8; o Python, com a saída redirecionada no
    # Windows, usaria a página de código local e trocaria os acentos.
    for fluxo in (sys.stdout, sys.stderr):
        if isinstance(fluxo, io.TextIOWrapper):
            fluxo.reconfigure(encoding="utf-8")
    if sys.platform == "win32":
        # O psycopg assíncrono não funciona com o loop padrão do Windows (ver tests/conftest.py).
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(main())
