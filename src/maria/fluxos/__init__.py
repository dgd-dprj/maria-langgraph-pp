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
    # Falso enquanto o fluxo está registrado (aparece em GET /fluxos e resolve por flowId)
    # mas ainda não deve ser escolhido pelo orquestrador: fica fora do catálogo de
    # classificação e a regra A10 não exige `descricao`.
    oferecer_ao_orquestrador: bool = True
    # Verdadeiro: quando o atendimento nasce no orquestrador (#334), o relato acumulado da triagem
    # entra no estado inicial no canal `relato` (fora de `dadosConhecidos`, que a Tykhe controla).
    # O fluxo precisa ter o canal `relato` no `state.py`. É dado sensível: nunca vai para log.
    usa_relato: bool = False
    # Fluxo em teste (#324): só liga onde `fluxo_em_teste_liga()`. Desligado, some
    # de GET /fluxos e do catálogo, e o flowId responde como desconhecido. Ligar em
    # produção é um PR que tira o campo, com registro na #208.
    em_teste: bool = False
    # Dados que o fluxo devolve em `dadosColetados`, além do `cpf` (#448). Dado pessoal: vai só na resposta da API,
    # nunca em log nem em `metadados`.
    extrair_dados_coletados: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None


# Única variável que liga um fluxo em teste, declarada no Terraform de cada
# ambiente (ecs.tf: "producao"; release.tf: "release"). Na dúvida, desligado:
# ausente, vazia ou qualquer valor diferente de exatamente "release" conta como
# produção, então uma variável esquecida ou copiada errada nunca liga um fluxo
# em teste. Não é a APP_ENV, que liga os simulados dos testes.
AMBIENTE_DO_FLUXO_EM_TESTE = "release"


def ambiente() -> str | None:
    return os.environ.get("MARIA_AMBIENTE")


def fluxo_em_teste_liga() -> bool:
    # Lida a cada chamada, como as outras variáveis de comportamento.
    return ambiente() == AMBIENTE_DO_FLUXO_EM_TESTE


# Id fixo por fluxo, no formato que uma linha de tabela teria (uuid).
ID_PESSOA_PRESA = "3df874f2-675a-4c43-9ec7-480f7c702f50"
ID_VIOLENCIA_DOMESTICA = "cabb2495-4e12-4f4a-9956-3d20649059bc"
ID_PROBLEMAS_PLANO_SAUDE = "84433c84-4776-4b05-a5a0-af8012d8eced"

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
    # Fluxo Problemas com plano de saúde (NUDECON, #329). Em teste (#324, decisão de 2026-11-03):
    # ligado só no release; na produção some de GET /fluxos e do catálogo, e o flowId responde como
    # desconhecido. Oferecido ao orquestrador desde a #386 (decisão da #266), SÓ PARA O QUE ENVOLVE
    # CIRURGIA (decisão da Nicole, 2026-11-05): onde está ligado, a cirurgia com o plano sai de
    # `tykhe:saude` (`TipoTykhe.trecho_de_fluxo_da_maria`). Cirurgia pelo SUS continua lá.
    # FUTURO: as outras negativas do plano (exame, tratamento, internação, remédio, reembolso que
    # não é de cirurgia) e, se o NUDECON confirmar, reajuste e cancelamento entram aqui depois de
    # validadas. Até lá, continuam em `tykhe:saude`. Ao ampliar, mudam juntos esta descrição, a
    # troca em `tipos_tykhe.py` e os casos de `tests/integracao/ia/test_classificacao_plano_saude.py`.
    ID_PROBLEMAS_PLANO_SAUDE: FluxoConfig(
        nome="problemas-plano-de-saude",
        descricao=(
            "Problema com plano de saúde particular ou convênio médico que envolve uma cirurgia: o plano negou, "
            "não autorizou ou está demorando para autorizar a cirurgia, não cobre material, prótese ou equipe da "
            "cirurgia, ou não quer reembolsar uma cirurgia. Cirurgia pelo SUS não entra aqui. "
            'A pessoa costuma escrever: "o plano negou a cirurgia", "o convênio não autorizou minha operação", '
            '"a Unimed tá enrolando pra liberar a cirurgia do meu joelho", "o plano não quer pagar a prótese da '
            'cirurgia".'
        ),
        obter_grafo=obter_grafo_plano_saude,
        extrair_metadados=api_plano_saude.extrair_metadados_plano_saude,
        extrair_dados_coletados=api_plano_saude.extrair_dados_coletados_plano_saude,
        mensagem_concluido=api_plano_saude.MENSAGEM_CONCLUIDO,
        mensagem_handoff=api_plano_saude.MENSAGEM_HANDOFF,
        em_teste=True,
        usa_relato=True,
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


def fluxos_ligados() -> dict[str, FluxoConfig]:
    """O registro sem os fluxos em teste, fora do ambiente que os liga (#324)."""
    liga = fluxo_em_teste_liga()
    return {id_: cfg for id_, cfg in fluxos_por_id.items() if liga or not cfg.em_teste}


async def buscar_fluxo(fluxo_id: str, *, conversa_em_andamento: bool = False) -> FluxoConfig | None:
    """Implementado tem prioridade; um planejado (#26) cai no grafo padrão (#21).
    `None` só se o catálogo de classificação ficar inconsistente com os dois.

    Um fluxo em teste desligado responde como um id desconhecido para conversa
    nova. A conversa que já começou nele termina normalmente
    (`conversa_em_andamento=True`), por decisão de 2026-10-23 (#324)."""
    implementado = fluxos_por_id.get(fluxo_id)
    if implementado is not None:
        if implementado.em_teste and not conversa_em_andamento and not fluxo_em_teste_liga():
            return None
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
    chamada, volta a oferecê-los, no fim, com `texto_para_classificacao` (#19).
    Fluxo em teste desligado não entra (#324). Um tipo da Tykhe perde o trecho que
    um fluxo da Maria no catálogo passou a atender (#386)."""
    implementados: list[OpcaoCatalogo] = [
        {"id": id_, "nome": cfg.nome, "descricao": cfg.descricao} for id_, cfg in fluxos_ligados().items() if cfg.oferecer_ao_orquestrador
    ]
    nomes_no_catalogo = {o["nome"] for o in implementados}
    tykhe: list[OpcaoCatalogo] = [
        {"id": t.id, "nome": t.nome, "descricao": t.descricao_no_catalogo(nomes_no_catalogo)} for t in TIPOS_TYKHE
    ]
    # `!== "true"` de develop: comparação exata, sem caixa e sem outros valores.
    if os.environ.get("ORQUESTRADOR_INCLUIR_PLANEJADOS") != "true":
        return [*implementados, *tykhe]
    planejados: list[OpcaoCatalogo] = [
        {"id": f["id"], "nome": f["nome"], "descricao": texto_para_classificacao(f)} for f in await listar_fluxos_planejados()
    ]
    return [*implementados, *tykhe, *planejados]
