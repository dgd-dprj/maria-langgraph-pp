"""Estado do fluxo de violência doméstica (develop: `fluxos/violenciaDomestica/state.ts`).

Os 30 canais de develop, na mesma ordem e com os mesmos nomes. Os canais de
pessoa (`cpf` a `viaOrquestrador`) são compartilhados por nome com os
subgrafos `identificar_assistido` e `cadastro_pessoa`, embutidos como nós.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from maria.shared.tokens_acumulados import CanalTokensGastos
from maria.shared.types import DadosPessoa, DadosProcesso, OrgaosViolenciaDomestica

MotivoHandoffViolenciaDomestica = Literal[
    "nao_e_vitima",
    "sem_orgao_disponivel",
    "falha_encaminhamento",
    "falha_cadastro",
    "assistido_nao_confirmado",
    "cpf_nao_encontrado",
    "falha_infra_verde",
]


class ViolenciaDomesticaState(TypedDict, total=False):
    ehVitima: bool | None
    temProcesso: bool | None
    numeroProcesso: str | None
    dadosProcesso: DadosProcesso | None
    tentativasProcesso: int | None
    querTentarNovamenteProcesso: bool | None
    digitouProcessoDireto: bool | None
    temRegistroOcorrencia: bool | None
    cpf: str | None
    dadosPessoa: DadosPessoa | None
    tentativasCpf: int | None
    querTentarNovamenteCpf: bool | None
    digitouCpfDireto: bool | None
    nome: str | None
    dataNascimento: str | None
    cadastroErro: str | None
    confirmaAssistido: bool | None
    viaOrquestrador: bool | None
    plantaoIds: list[int | None] | None
    orgaosViolenciaDomestica: OrgaosViolenciaDomestica | None
    encaminhamentoId: int | None
    encaminhamentoErro: str | None
    statusFinal: Literal["concluido", "handoff_humano"] | None
    motivoHandoff: MotivoHandoffViolenciaDomestica | None
    tipoEncaminhamento: Literal["padrao", "urgente"] | None
    mensagemFinal: str | None
    perguntaAtualTexto: str | None
    perguntaAtualViaIA: bool | None
    perguntaAtualTokensTotal: int | None
    tokensGastos: CanalTokensGastos
