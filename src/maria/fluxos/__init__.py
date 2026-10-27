"""Catálogo dos fluxos (develop: `fluxos/index.ts`).

Diferenças de forma, sem mudar o comportamento:
- `FluxoConfig.grafo` vira `obter_grafo`: em develop o grafo é compilado na
  importação, com top-level await do checkpointer; aqui o checkpointer é
  preparado no lifespan e o grafo é compilado na primeira chamada.
- `metadadosSchema` não é traduzido (spec 05, decisão 3): não tem consumidor
  em develop, e a rota declara `metadados` genérico.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

from maria.fluxos._fabrica import GrafoCompilado
from maria.fluxos.padrao import api as api_padrao
from maria.fluxos.padrao.graph import obter_grafo as obter_grafo_padrao
from maria.fluxos.pessoa_presa import api as api_pessoa_presa
from maria.fluxos.pessoa_presa.graph import obter_grafo as obter_grafo_pessoa_presa
from maria.fluxos.plano_saude import api as api_plano_saude
from maria.fluxos.plano_saude.graph import obter_grafo as obter_grafo_plano_saude
from maria.fluxos.tipos_tykhe import TIPOS_TYKHE
from maria.fluxos.violencia_domestica import api as api_violencia_domestica
from maria.fluxos.violencia_domestica.graph import obter_grafo as obter_grafo_violencia_domestica
from maria.shared.fluxos_planejados_db import buscar_fluxo_planejado_por_id, listar_fluxos_planejados, texto_para_classificacao


@dataclass(frozen=True)
class FluxoConfig:
    nome: str
    # Lida pela classificação do orquestrador para escolher o fluxo a partir do
    # relato livre: texto curto, em pt-BR, dizendo para quem o fluxo serve.
    descricao: str
    obter_grafo: Callable[[], GrafoCompilado]
    extrair_metadados: Callable[[Mapping[str, Any]], dict[str, Any]]
    mensagem_concluido: str
    mensagem_handoff: str
    # idCategoriaAssunto do Verde equivalente, quando existe (issue #19). Só
    # evita duplicar o fluxo na tabela fluxos_planejados (#26).
    id_categoria_assunto_verde: int | None = None


# Id fixo por fluxo, no formato que uma linha de tabela teria (uuid).
ID_PESSOA_PRESA = "3df874f2-675a-4c43-9ec7-480f7c702f50"
ID_VIOLENCIA_DOMESTICA = "cabb2495-4e12-4f4a-9956-3d20649059bc"
ID_PLANO_SAUDE = "84433c84-4776-4b05-a5a0-af8012d8eced"

fluxos_por_id: dict[str, FluxoConfig] = {
    ID_PESSOA_PRESA: FluxoConfig(
        nome="pessoa-presa",
        descricao=(
            "Alguém (geralmente familiar) buscando informação ou encaminhamento sobre uma pessoa que está presa — "
            "situação prisional, processo, número do processo, dados do apenado no sistema penitenciário."
        ),
        obter_grafo=obter_grafo_pessoa_presa,
        extrair_metadados=api_pessoa_presa.extrair_metadados_pessoa_presa,
        mensagem_concluido=api_pessoa_presa.MENSAGEM_CONCLUIDO,
        mensagem_handoff=api_pessoa_presa.MENSAGEM_HANDOFF,
    ),
    ID_VIOLENCIA_DOMESTICA: FluxoConfig(
        nome="violencia-domestica",
        descricao=(
            "Mulher vítima de violência doméstica buscando ajuda, proteção ou encaminhamento jurídico — "
            "relato de agressão física/psicológica, medo do agressor, com ou sem Boletim de Ocorrência já registrado."
        ),
        obter_grafo=obter_grafo_violencia_domestica,
        extrair_metadados=api_violencia_domestica.extrair_metadados_violencia_domestica,
        mensagem_concluido=api_violencia_domestica.MENSAGEM_CONCLUIDO,
        mensagem_handoff=api_violencia_domestica.MENSAGEM_HANDOFF,
        # Confirmado ao vivo em 2026-09-10 (GET /assunto/categorias), issue #19.
        id_categoria_assunto_verde=10113,
    ),
    # NUDECON (#329). Esqueleto: ainda sem as perguntas; o id foi combinado com a Tykhe.
    ID_PLANO_SAUDE: FluxoConfig(
        nome="plano-saude",
        descricao=(
            "Problemas com plano de saúde (NUDECON): negativa de cobertura de procedimento, exame ou internação, "
            "reajuste abusivo, cancelamento do plano ou descumprimento de contrato com a operadora."
        ),
        obter_grafo=obter_grafo_plano_saude,
        extrair_metadados=api_plano_saude.extrair_metadados_plano_saude,
        mensagem_concluido=api_plano_saude.MENSAGEM_CONCLUIDO,
        mensagem_handoff=api_plano_saude.MENSAGEM_HANDOFF,
    ),
}

# Grafo compartilhado por qualquer fluxo planejado sem implementação (#21).
# Instância única: o isolamento entre conversas é pelo thread_id.
FLUXO_PADRAO = FluxoConfig(
    nome="padrao-em-construcao",
    # Nunca entra em catalogo_para_classificacao: é só o destino de um
    # planejado já escolhido.
    descricao="",
    obter_grafo=obter_grafo_padrao,
    extrair_metadados=api_padrao.extrair_metadados_padrao,
    mensagem_concluido=api_padrao.MENSAGEM_CONCLUIDO,
    mensagem_handoff=api_padrao.MENSAGEM_HANDOFF,
)


async def buscar_fluxo(fluxo_id: str) -> FluxoConfig | None:
    """Implementado tem prioridade; um planejado (#26) cai no grafo padrão (#21).
    `None` só se o catálogo de classificação ficar inconsistente com os dois."""
    implementado = fluxos_por_id.get(fluxo_id)
    if implementado is not None:
        return implementado
    planejado = await buscar_fluxo_planejado_por_id(fluxo_id)
    return FLUXO_PADRAO if planejado else None


class OpcaoCatalogo(TypedDict):
    id: str
    nome: str
    descricao: str


async def catalogo_para_classificacao() -> list[OpcaoCatalogo]:
    """Catálogo de classificação do orquestrador. Issue #225: implementados (a
    Maria conduz) e depois os tipos que a Tykhe atende (`tipos_tykhe`, a Maria só
    identifica e devolve), nesta ordem. Os planejados (#26) saíram do catálogo,
    mas a tabela fica intacta e `buscar_fluxo` continua resolvendo um planejado
    para o grafo padrão. `ORQUESTRADOR_INCLUIR_PLANEJADOS == "true"`, lido a cada
    chamada, volta a oferecê-los, no fim, com `texto_para_classificacao` (#19)."""
    implementados: list[OpcaoCatalogo] = [{"id": id_, "nome": cfg.nome, "descricao": cfg.descricao} for id_, cfg in fluxos_por_id.items()]
    tykhe: list[OpcaoCatalogo] = [{"id": t.id, "nome": t.nome, "descricao": t.descricao} for t in TIPOS_TYKHE]
    # `!== "true"` de develop: comparação exata, sem caixa e sem outros valores.
    if os.environ.get("ORQUESTRADOR_INCLUIR_PLANEJADOS") != "true":
        return [*implementados, *tykhe]
    planejados: list[OpcaoCatalogo] = [
        {"id": f["id"], "nome": f["nome"], "descricao": texto_para_classificacao(f)} for f in await listar_fluxos_planejados()
    ]
    return [*implementados, *tykhe, *planejados]
