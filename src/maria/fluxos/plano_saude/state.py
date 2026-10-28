"""Estado do fluxo Problemas com plano de saúde (NUDECON, issue #329).

As chaves de `dadosConhecidos` que a Tykhe manda (`cpf` a `endereco`, mais
`imagensRecebidas`) são canais do estado: chave que não existe aqui o LangGraph
ignora. Os dados aparecem no resumo da confirmação; `imagensRecebidas` pula a
pergunta das imagens.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from maria.shared.tokens_acumulados import CanalTokensGastos

CanalAtendimento = Literal["aqui", "email", "presencial"]

MotivoHandoffPlanoSaude = Literal[
    "outra_pessoa", "canal_nao_entendido", "imagens_pendentes", "renda_nao_entendida", "dados_nao_confirmados"
]


class EnderecoPlanoSaude(TypedDict, total=False):
    cep: str
    logradouro: str
    numero: str
    complemento: str
    bairro: str
    municipio: str
    uf: str


class PlanoSaudeState(TypedDict, total=False):
    # Vêm da Tykhe em `dadosConhecidos` (formato proposto na #329).
    cpf: str
    nome: str
    dataNascimento: str
    email: str
    telefone: str
    endereco: EnderecoPlanoSaude
    # Premissa da #329 (a confirmar na #336): a Tykhe avisa que guardou as imagens dos documentos.
    imagensRecebidas: bool | None
    # Respostas da conversa.
    canal: CanalAtendimento | None
    tentativasCanal: int | None
    paraSi: bool | None
    tentativasImagens: int | None
    renda: float | None
    tentativasRenda: int | None
    confirmado: bool | None
    tentativasConfirmacao: int | None
    statusFinal: Literal["concluido", "handoff_humano"] | None
    motivoHandoff: MotivoHandoffPlanoSaude | None
    mensagemFinal: str | None
    perguntaAtualTexto: str | None
    perguntaAtualViaIA: bool | None
    perguntaAtualTokensTotal: int | None
    tokensGastos: CanalTokensGastos
