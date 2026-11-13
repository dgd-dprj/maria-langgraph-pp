"""Estado do subgrafo `identificar_assistido` (develop: `subgrafos/identificarAssistido/state.ts`).

Compartilhado com os fluxos pai por nome de canal, sem nó de tradução
(comentário em `state.ts:7-11`): os nomes em camelCase são o contrato.
"""

from __future__ import annotations

from typing import TypedDict

from maria.shared.tokens_acumulados import CanalTokensGastos
from maria.shared.types import DadosPessoa


class IdentificarAssistidoState(TypedDict, total=False):
    cpf: str | None
    dadosPessoa: DadosPessoa
    tentativasCpf: int | None
    querTentarNovamenteCpf: bool | None
    digitouCpfDireto: bool | None
    confirmaAssistido: bool | None
    # Interno do subgrafo (#236): o CPF consultado veio da Tykhe
    # (`dadosConhecidos`), e não foi digitado na conversa. Os fluxos pai não
    # têm este canal, então ele não sai do subgrafo nem chega à resposta HTTP.
    cpfDaTykhe: bool
    viaOrquestrador: bool | None
    perguntaAtualTexto: str | None
    perguntaAtualViaIA: bool
    perguntaAtualTokensTotal: int | None
    tokensGastos: CanalTokensGastos
