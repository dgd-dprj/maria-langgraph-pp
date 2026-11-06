"""Estado do orquestrador (develop: `orquestrador/state.ts`).

Regra de estado da migração (spec 06, seção 0.2): onde develop grava `undefined`
num canal, o Python grava `None`. Em `resumoRelato` o `null` do modelo também
vira `None`, e a divergência está aceita (D-1).
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from maria.orquestrador.fila import AssuntoPendente, ItemFila
from maria.shared.tokens_acumulados import CanalTokensGastos


class CandidatoOrquestrador(TypedDict):
    id: str
    nome: str
    descricao: str


class OrquestradorState(TypedDict, total=False):
    # Relato acumulado BRUTO: nas rodadas de desambiguação, a resposta da
    # pessoa é concatenada aqui, sempre, mesmo depois de começar a sumarizar
    # (issue #47). Serve de registro completo, mas deixa de ser o texto usado
    # para classificar a partir de LIMITE_RODADAS_SUMARIZACAO (ver
    # texto_para_classificacao em orquestrador/graph.py).
    mensagem: str
    # Issue #47: resumo do que já foi dito ATÉ a resposta mais recente
    # (exclusive). None = ainda não sumarizou. Sem validação (#212): o modelo
    # pode devolver outro tipo.
    resumoRelato: Any
    # Resposta mais recente, guardada separada do resumo e sempre enviada
    # verbatim para a classificação e a desambiguação.
    ultimaResposta: str | None
    # None = ainda não fez retrieval (1ª rodada). Definido = já filtrado por uma
    # rodada anterior: a próxima classifica DENTRO desse subconjunto.
    candidatosRestantes: list[CandidatoOrquestrador] | None
    rodada: int | None
    flowIdEscolhido: str | None
    statusFinal: Literal["identificado", "nao_identificado"] | None
    # Sem validação (#212): a pergunta gerada pelo modelo pode vir de outro tipo.
    perguntaAtualTexto: Any
    # Tokens gastos com IA NESTA rodada (entre 2 pausas do grafo); não acumula
    # entre rodadas. `classificar` sobrescreve; `prepararPerguntaDesambiguacao`
    # e `pedirDesambiguacao` somam em cima (issue #34).
    tokensGastosRodada: int | None
    # Soma de TODOS os tokens desta conversa do orquestrador (issues #35, #69,
    # #92). A rota repassa como dadosConhecidos.tokensGastos ao fluxo escolhido.
    tokensGastosConversa: CanalTokensGastos
    # Multi-fluxo, fase 1a (#435), só no release. A fila de assuntos do relato, na ordem em que a
    # Maria vai tratar; None quando o relato tem um assunto só (o caminho de sempre).
    fila: list[ItemFila] | None
    # A pessoa recusou a ordem com 3 assuntos ou mais: falta perguntar qual vem primeiro.
    escolherPrimeiro: bool | None
    # A Maria perguntou a ordem: a resposta que abre o fluxo começa com "Combinado. Vamos começar…".
    ordemPerguntada: bool | None
    # Os assuntos da fila depois do primeiro, para a Tykhe seguir com eles (campo `assuntosPendentes`).
    assuntosPendentes: list[AssuntoPendente] | None
    # #442: os `dadosConhecidos` da 1ª chamada. A resposta à desambiguação ou à ordem volta só com
    # `{ chatId, resposta }`, e sem isto o fluxo aberto depois começava sem os dados da pessoa. Dado
    # pessoal: fica no checkpoint, como nos fluxos, e nunca vai para log.
    dadosConhecidos: dict[str, Any] | None
