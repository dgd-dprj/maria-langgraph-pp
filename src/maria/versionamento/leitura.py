"""Leitura das versões dos fluxos para a rota do Visor (#547). Só `SELECT`, com lista explícita de colunas.

A tabela `fluxos_versoes` (#542) guarda só código, textos fixos do repositório e metadados de PR: nada do assistido.
A lista de colunas é explícita de propósito: coluna nova na tabela não vira campo da rota sem decisão.
Um pool por chamada, aberto e fechado aqui, como `listar_versoes`: não disputa conexão com o atendimento.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from maria.shared.pool import criar_pool

# (coluna, campo na resposta)
CAMPOS_DA_LISTA: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("fluxo", "fluxo"),
    ("nome_fluxo", "nomeFluxo"),
    ("ambiente", "ambiente"),
    ("registrado_em", "registradoEm"),
    ("hash", "hash"),
    ("hash_anterior", "hashAnterior"),
    ("resumo", "resumo"),
    ("resumo_origem", "resumoOrigem"),
    ("solicitante", "solicitante"),
    ("autor_commit", "autorCommit"),
    ("aprovado_por", "aprovadoPor"),
    ("pr_numero", "prNumero"),
    ("pr_titulo", "prTitulo"),
    ("issue_origem", "issueOrigem"),
    ("commit_sha", "commitSha"),
    ("tag_imagem", "tagImagem"),
    ("mudou_codigo_compartilhado", "mudouCodigoCompartilhado"),
    ("alteracoes", "alteracoes"),
)
_COLUNAS_DA_LISTA = ", ".join(coluna for coluna, _ in CAMPOS_DA_LISTA)
_COLUNAS_DO_DETALHE = f"{_COLUNAS_DA_LISTA}, snapshot"

_LISTA = f"""SELECT {_COLUNAS_DA_LISTA} FROM fluxos_versoes
             WHERE (%s::text IS NULL OR fluxo = %s OR nome_fluxo = %s) AND (%s::text IS NULL OR ambiente = %s)
             ORDER BY id DESC LIMIT %s"""  # noqa: S608 (colunas fixas deste módulo; os valores vão como parâmetro)
# A versão em vigor é a última linha de cada fluxo em cada ambiente.
_EM_VIGOR = """SELECT DISTINCT ON (fluxo, ambiente) id, fluxo, nome_fluxo, ambiente, registrado_em, hash FROM fluxos_versoes
               WHERE (%s::text IS NULL OR fluxo = %s OR nome_fluxo = %s) AND (%s::text IS NULL OR ambiente = %s)
               ORDER BY fluxo, ambiente, id DESC"""
_DETALHE = f"SELECT {_COLUNAS_DO_DETALHE} FROM fluxos_versoes WHERE id = %s"  # noqa: S608 (colunas fixas; o id vai como parâmetro)


def _valor(valor: Any) -> Any:
    return valor.isoformat() if isinstance(valor, datetime) else valor


def _versao(linha: dict[str, Any], *, com_snapshot: bool = False) -> dict[str, Any]:
    item = {campo: _valor(linha[coluna]) for coluna, campo in CAMPOS_DA_LISTA}
    if com_snapshot:
        item["snapshot"] = linha["snapshot"]
    return item


def _em_vigor(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        "fluxo": linha["fluxo"],
        "nomeFluxo": linha["nome_fluxo"],
        "ambiente": linha["ambiente"],
        "id": linha["id"],
        "hash": linha["hash"],
        "registradoEm": _valor(linha["registrado_em"]),
    }


async def listar(url: str, fluxo: str | None, ambiente: str | None, limite: int) -> dict[str, Any]:
    """`emVigor` e `versoes` (da mais nova para a mais antiga, sem o snapshot). Levanta se o banco falhar."""
    filtros = (fluxo, fluxo, fluxo, ambiente, ambiente)
    pool = criar_pool(url)
    await pool.open()
    try:
        async with pool.connection() as conexao:
            vigor = await (await conexao.execute(_EM_VIGOR, filtros)).fetchall()
            versoes = await (await conexao.execute(_LISTA, (*filtros, limite))).fetchall()
    finally:
        await pool.close()
    return {"emVigor": [_em_vigor(dict(v)) for v in vigor], "versoes": [_versao(dict(v)) for v in versoes]}


async def buscar(url: str, id_: int) -> dict[str, Any] | None:
    """Uma versão, com o snapshot; None se não existir. Levanta se o banco falhar."""
    pool = criar_pool(url)
    await pool.open()
    try:
        async with pool.connection() as conexao:
            linha = await (await conexao.execute(_DETALHE, (id_,))).fetchone()
    finally:
        await pool.close()
    return _versao(dict(linha), com_snapshot=True) if linha else None
