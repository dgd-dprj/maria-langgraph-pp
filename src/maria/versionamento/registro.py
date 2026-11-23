"""Grava as versões dos fluxos na tabela `fluxos_versoes` (#542).

Roda no startup da Maria, em segundo plano. Para cada fluxo, compara o hash de agora com o da última linha do
ambiente: igual, não grava; diferente (ou primeira vez), insere uma linha nova com o snapshot, o que mudou e quem
pediu. A tabela só recebe `INSERT`: a aplicação nunca atualiza nem apaga linha, para servir de trilha de auditoria.
Voltar a uma versão antiga também grava uma linha (a história é a sequência, não o conjunto de hashes).

Falha aqui **nunca** derruba nem atrasa a Maria: o erro vai para o log e o atendimento segue (fluxo de urgência).
Sem DATABASE_URL (testes), nada é gravado. Metadados da esteira: `/app/versao-meta.json` (ou `MARIA_VERSAO_META`).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from maria.shared.logger import logger
from maria.shared.pool import PoolAsync, criar_pool
from maria.versionamento.alteracoes import comparar_compartilhado, comparar_fluxo, contagem
from maria.versionamento.manifesto import Manifesto
from maria.versionamento.meta import prs_do_compartilhado, prs_do_fluxo

CAMINHO_PADRAO_DA_META = "/app/versao-meta.json"
# Trava de sessão do Postgres: duas tasks subindo juntas não gravam a mesma versão duas vezes.
CHAVE_DA_TRAVA = 542_000_001
COMPARTILHADO = "compartilhado"

_CRIAR_TABELA = """
    CREATE TABLE IF NOT EXISTS fluxos_versoes (
      id BIGSERIAL PRIMARY KEY,
      fluxo TEXT NOT NULL,
      nome_fluxo TEXT NOT NULL,
      hash TEXT NOT NULL,
      hash_anterior TEXT,
      ambiente TEXT NOT NULL,
      registrado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
      snapshot JSONB NOT NULL,
      alteracoes JSONB NOT NULL,
      resumo TEXT NOT NULL,
      resumo_origem TEXT NOT NULL CHECK (resumo_origem IN ('pr', 'automatico')),
      commit_sha TEXT,
      tag_imagem TEXT,
      pr_numero INTEGER,
      pr_titulo TEXT,
      issue_origem INTEGER,
      autor_commit TEXT,
      solicitante TEXT,
      aprovado_por TEXT,
      mudou_codigo_compartilhado BOOLEAN NOT NULL DEFAULT false,
      prs JSONB NOT NULL DEFAULT '[]'::jsonb
    )
"""
_CRIAR_INDICE = "CREATE INDEX IF NOT EXISTS fluxos_versoes_fluxo ON fluxos_versoes (fluxo, ambiente, id DESC)"


def carregar_meta() -> dict[str, Any]:
    """Os metadados que a esteira gravou na imagem; vazio se não houver (build local)."""
    caminho = Path(os.environ.get("MARIA_VERSAO_META", CAMINHO_PADRAO_DA_META))
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _junta(valores: list[Any]) -> str | None:
    unicos = list(dict.fromkeys(str(v) for v in valores if v))
    return ", ".join(unicos) or None


def _autoria(prs: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    """Quem e por quê, a partir dos PRs que mexeram naquele fluxo."""
    ordenados = sorted(prs, key=lambda pr: pr["numero"])
    ultimo = ordenados[-1] if ordenados else None
    return {
        "pr_numero": ultimo["numero"] if ultimo else None,
        "pr_titulo": ultimo["titulo"] if ultimo else None,
        "issue_origem": next((pr["issue_origem"] for pr in reversed(ordenados) if pr.get("issue_origem")), None),
        "autor_commit": _junta([pr.get("autor") for pr in ordenados]),
        "solicitante": _junta([pr.get("solicitante") for pr in ordenados]),
        "aprovado_por": _junta([a for pr in ordenados for a in pr.get("aprovado_por", [])]),
        "resumo_pr": " / ".join(dict.fromkeys(pr["resumo"] for pr in ordenados if pr.get("resumo"))),
        "prs": [{k: pr[k] for k in ("numero", "titulo", "autor", "solicitante", "resumo", "aprovado_por") if k in pr} for pr in ordenados],
        "commit_sha": meta.get("commit_sha"),
        "tag_imagem": meta.get("tag_imagem"),
    }


async def _ultima(conexao: Any, fluxo: str, ambiente: str) -> dict[str, Any] | None:
    cursor = await conexao.execute(
        "SELECT hash, snapshot FROM fluxos_versoes WHERE fluxo = %s AND ambiente = %s ORDER BY id DESC LIMIT 1", (fluxo, ambiente)
    )
    linha = await cursor.fetchone()
    return dict(linha) if linha else None


async def _inserir(
    conexao: Any,
    *,
    fluxo: str,
    nome: str,
    hash_novo: str,
    ambiente: str,
    anterior: dict[str, Any] | None,
    snapshot: dict[str, Any],
    alteracoes: list[dict[str, Any]],
    autoria: dict[str, Any],
    compartilhado_mudou: bool,
) -> None:
    automatico = contagem(alteracoes)
    resumo_pr = autoria["resumo_pr"]
    resumo = f"{resumo_pr} ({automatico})" if resumo_pr else automatico
    await conexao.execute(
        """INSERT INTO fluxos_versoes
         (fluxo, nome_fluxo, hash, hash_anterior, ambiente, snapshot, alteracoes, resumo, resumo_origem, commit_sha,
          tag_imagem, pr_numero, pr_titulo, issue_origem, autor_commit, solicitante, aprovado_por,
          mudou_codigo_compartilhado, prs)
         VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
        (
            fluxo,
            nome,
            hash_novo,
            anterior["hash"] if anterior else None,
            ambiente,
            json.dumps(snapshot, ensure_ascii=False),
            json.dumps(alteracoes, ensure_ascii=False),
            resumo,
            "pr" if resumo_pr else "automatico",
            autoria["commit_sha"],
            autoria["tag_imagem"],
            autoria["pr_numero"],
            autoria["pr_titulo"],
            autoria["issue_origem"],
            autoria["autor_commit"],
            autoria["solicitante"],
            autoria["aprovado_por"],
            compartilhado_mudou,
            json.dumps(autoria["prs"], ensure_ascii=False),
        ),
    )


async def _registrar(pool: PoolAsync, ambiente: str, manifesto: Manifesto, meta: dict[str, Any]) -> list[str]:
    registrados: list[str] = []
    prs: list[dict[str, Any]] = [pr for pr in meta.get("prs", []) if isinstance(pr, dict) and "numero" in pr]
    async with pool.connection() as conexao:
        # A trava vem antes do DDL: duas tasks subindo juntas numa tabela nova não colidem no CREATE TABLE.
        await conexao.execute("SELECT pg_advisory_lock(%s)", (CHAVE_DA_TRAVA,))
        try:
            await conexao.execute(_CRIAR_TABELA)
            await conexao.execute(_CRIAR_INDICE)
            comp = manifesto[COMPARTILHADO]
            ultima_comp = await _ultima(conexao, COMPARTILHADO, ambiente)
            compartilhado_mudou = ultima_comp is not None and ultima_comp["hash"] != comp["hash"]
            if ultima_comp is None or compartilhado_mudou:
                await _inserir(
                    conexao,
                    fluxo=COMPARTILHADO,
                    nome=COMPARTILHADO,
                    hash_novo=comp["hash"],
                    ambiente=ambiente,
                    anterior=ultima_comp,
                    snapshot=comp["snapshot"],
                    alteracoes=comparar_compartilhado(ultima_comp["snapshot"] if ultima_comp else None, comp["snapshot"]),
                    autoria=_autoria(prs_do_compartilhado(prs), meta),
                    compartilhado_mudou=False,
                )
                registrados.append(COMPARTILHADO)
            for id_, entrada in manifesto["fluxos"].items():
                ultima = await _ultima(conexao, id_, ambiente)
                if ultima is not None and ultima["hash"] == entrada["hash"]:
                    continue
                await _inserir(
                    conexao,
                    fluxo=id_,
                    nome=entrada["nome"],
                    hash_novo=entrada["hash"],
                    ambiente=ambiente,
                    anterior=ultima,
                    snapshot=entrada["snapshot"],
                    alteracoes=comparar_fluxo(ultima["snapshot"] if ultima else None, entrada["snapshot"]),
                    autoria=_autoria(prs_do_fluxo(prs, entrada["snapshot"].get("pasta")), meta),
                    compartilhado_mudou=compartilhado_mudou,
                )
                registrados.append(id_)
        finally:
            await conexao.execute("SELECT pg_advisory_unlock(%s)", (CHAVE_DA_TRAVA,))
    return registrados


async def registrar_versoes(url: str, ambiente: str, manifesto: Manifesto, meta: dict[str, Any]) -> list[str]:
    """Devolve os fluxos que ganharam versão nova. Nunca levanta erro (só CancelledError passa)."""
    pool = criar_pool(url)
    try:
        await pool.open()
        registrados = await _registrar(pool, ambiente, manifesto, meta)
        for fluxo in registrados:
            logger.info("[versionamento] versão de fluxo registrada", evento="fluxo_versao_registrada", fluxoId=fluxo, ambiente=ambiente)
        return registrados
    except Exception as erro:
        logger.error("[versionamento] falha ao registrar as versões dos fluxos (a Maria segue atendendo)", err=erro)
        return []
    finally:
        try:
            await asyncio.shield(pool.close())
        except Exception as erro:
            logger.error("[versionamento] falha ao fechar o pool do registro", err=erro)


async def listar_versoes(url: str, fluxo: str, ambiente: str | None, limite: int = 20) -> list[dict[str, Any]]:
    """Para a consulta (`python -m maria.versionamento listar`): as versões mais novas de um fluxo, sem o snapshot."""
    pool = criar_pool(url)
    await pool.open()
    try:
        async with pool.connection() as conexao:
            cursor = await conexao.execute(
                """SELECT id, fluxo, nome_fluxo, ambiente, registrado_em, hash, resumo, resumo_origem, solicitante, autor_commit,
                          aprovado_por, pr_numero, commit_sha, tag_imagem, mudou_codigo_compartilhado, alteracoes
                   FROM fluxos_versoes
                   WHERE (fluxo = %s OR nome_fluxo = %s) AND (%s::text IS NULL OR ambiente = %s)
                   ORDER BY id DESC LIMIT %s""",
                (fluxo, fluxo, ambiente, ambiente, limite),
            )
            return [dict(linha) for linha in await cursor.fetchall()]
    finally:
        await pool.close()
