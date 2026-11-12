"""Estado do fluxo de pessoa presa (develop: `fluxos/pessoaPresa/state.ts`).

Os 27 canais de develop, na mesma ordem e com os mesmos nomes. Os canais de
pessoa (`cpf` a `viaOrquestrador`) são compartilhados por nome com os
subgrafos `identificar_assistido` e `cadastro_pessoa`.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from maria.shared.tokens_acumulados import CanalTokensGastos
from maria.shared.types import DadosApenado, DadosPessoa, DadosProcesso

MotivoHandoffPessoaPresa = Literal[
    "nome_nao_confirmado",
    "rg_nao_encontrado",
    "sem_numero_processo",
    "origem_processo_nao_suportada",
    "dados_pessoa_nao_atendidos",
    "falha_cadastro",
    "assistido_nao_confirmado",
    "falha_infra_verde",
    # #394 (decisão da Nicole, 2026-11-12): três RGs recusados pelo formato. Valor novo no contrato; a Tykhe
    # encaminha pelo `destino`, como nos outros handoffs.
    "rg_formato_invalido",
]


class PessoaPresaState(TypedDict, total=False):
    parentesco: str | None
    # #438: a pergunta curta tirada do relato ("Você é a mãe ou o pai dele?", "Sobre qual deles…?") e
    # as respostas que ela aceita (palavra sem acento -> parentesco). None: a pergunta de sempre.
    perguntaParentesco: str | None
    opcoesParentesco: dict[str, str] | None
    temProcesso: bool | None
    numeroProcesso: str | None
    dadosProcesso: DadosProcesso | None
    rg: str | None
    dadosApenado: DadosApenado | None
    tentativasRg: int | None
    querTentarNovamente: bool | None
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
    digitouRgDireto: bool | None
    confirmaNome: bool | None
    statusFinal: Literal["concluido", "handoff_humano"] | None
    motivoHandoff: MotivoHandoffPessoaPresa | None
    mensagemFinal: str | None
    perguntaAtualTexto: str | None
    perguntaAtualViaIA: bool | None
    perguntaAtualTokensTotal: int | None
    tokensGastos: CanalTokensGastos
    # #341/#352, fora dos 27 de develop: o status da resposta do Verde quando ele
    # não acha o processo (400, 404, 422). Interno: não vai para os metadados.
    statusConsultaProcesso: int | None
    # #394, fora dos 27 de develop: quantas vezes o RG foi recusado pelo formato. Na 3ª, a conversa vai para o
    # atendimento humano. Interno: não vai para os metadados.
    recusasRgFormato: int | None
