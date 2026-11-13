"""Estado do fluxo Problemas com plano de saúde (NUDECON, issue #329).

As chaves de `dadosConhecidos` que a Tykhe manda (`cpf` a `endereco`, mais
`imagensRecebidas`) são canais do estado: chave que não existe aqui o LangGraph
ignora. Os dados aparecem no resumo da confirmação; `imagensRecebidas` pula a
pergunta das imagens.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from maria.shared.tokens_acumulados import CanalTokensGastos

MotivoHandoffPlanoSaude = Literal[
    "cpf_outra_pessoa_invalido",
    "dados_outra_pessoa_invalidos",
    "imagens_pendentes",
    "situacao_nao_informada",
    "renda_nao_entendida",
    "dados_nao_confirmados",
    "falha_infra_verde",
    "falha_envio_email",
    "imagens_nao_anexadas",
    "erro_interno",
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
    # Vem da Tykhe (de quem fala), só para mostrar no resumo e no e-mail; o fluxo não verifica o município (#439).
    endereco: EnderecoPlanoSaude
    # Premissa da #329 (a confirmar na #336): a Tykhe avisa que guardou as imagens dos documentos.
    imagensRecebidas: bool | None
    # Respostas da conversa.
    paraSi: bool | None
    # #438: o orquestrador leu no relato para quem é o atendimento; só então "para você?" é pulada.
    paraSiPeloRelato: bool | None
    # Outra pessoa (#433): o CPF dela e o que o Verde trouxe são dado de terceiro, sensível: nunca em log nem em `metadados`.
    cpfOutraPessoa: str | None
    tentativasCpfOutra: int | None
    erroCpfOutra: Literal["invalido"] | None
    # Do Verde (200) ou, sem cadastro (404), informados na conversa (#446): `origem` "informado" e a etapa em `etapaDadosOutra`.
    dadosOutraPessoa: dict[str, Any] | None
    tentativasDadosOutra: int | None
    # #446: a pergunta do endereço do subgrafo `coletar_endereco` fala da outra pessoa.
    enderecoDeOutraPessoa: bool | None
    # Para onde o atendimento concluído vai (`email_enviado`: por e-mail ao NUDECON).
    destino: str | None
    tentativasImagens: int | None
    # Links de baixar as imagens que a Tykhe respondeu (#398): `carteirinhaFrente` e `carteirinhaVerso`.
    # O token vai na URL, então é segredo: nunca em log, em metadados nem em erro.
    imagensLinks: dict[str, str] | None
    # Situação em palavras da pessoa. Vem do orquestrador (#334) ou da pergunta da Maria; é dado sensível, nunca vai para log.
    relato: str | None
    tentativasSituacao: int | None
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
