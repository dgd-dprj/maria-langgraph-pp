"""Lado Python da conferência: o mesmo papel da cópia sonda de develop (`gerar_sonda.py`).

Roda `coletar_arvore_perguntas_verde.main()` com a mesma troca da sonda: sem a guarda de
DATABASE_URL, com os planejados do cenário cadastrados antes e o despejo das stores depois.

Uso (variáveis de ambiente): CENARIO_PLANEJADOS, DUMP_ARQUIVO, VERDE_API_URL, VERDE_JWT_TOKEN.
"""

import asyncio
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))

import coletar_arvore_perguntas_verde as crawler
from maria.fluxos import ID_VIOLENCIA_DOMESTICA
from maria.shared.fluxos_planejados_db import adicionar_planejado_de_teste, fechar_fluxos_planejados_store
from maria.shared.perguntas_db import fechar_perguntas_store, obter_perguntas_store

PLANEJADOS: list[Any] = json.loads(os.environ.get("CENARIO_PLANEJADOS", "[]"))


async def despejar() -> None:
    store = await obter_perguntas_store()
    saida: dict[str, Any] = {}
    for id_flow in [ID_VIOLENCIA_DOMESTICA, *(f["id"] for f in PLANEJADOS)]:
        perguntas = [{k: v for k, v in p.items() if k != "id"} for p in await store.listar_perguntas_por_flow(id_flow)]
        saida[id_flow] = {"perguntas": perguntas, "assuntos": await store.listar_assuntos_por_flow(id_flow)}
    # Escrita única no fim do processo da conferência; bloquear o loop aqui não importa.
    Path(os.environ["DUMP_ARQUIVO"]).write_text(json.dumps(saida, ensure_ascii=False), encoding="utf-8")  # noqa: ASYNC240


async def principal_sonda() -> None:
    for f in PLANEJADOS:
        await adicionar_planejado_de_teste(f)
    config = crawler.config_do_ambiente()
    if not config.jwt_token:
        raise crawler.ErroJs("VERDE_JWT_TOKEN obrigatório — este script fala com o Verde de verdade, sem modo mock")
    try:
        async with httpx.AsyncClient(timeout=None) as cliente:
            await crawler.coletar(cliente, config)
        await despejar()
    finally:
        await fechar_perguntas_store()
        await fechar_fluxos_planejados_store()


if __name__ == "__main__":
    for fluxo in (sys.stdout, sys.stderr):
        if isinstance(fluxo, io.TextIOWrapper):
            fluxo.reconfigure(encoding="utf-8")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    crawler.principal = principal_sonda
    sys.exit(crawler.main())
