"""Estado do subgrafo `coletar_endereco` (develop: `subgrafos/coletarEndereco/state.ts`).

Os nomes de canal são os de develop, em camelCase: são compartilhados por nome
com o `cadastro_pessoa`, que embute este subgrafo, e ficam no checkpoint. Só
`endereco`, os três `perguntaAtual*` e `tokensGastos` existem no pai; os campos
crus do endereço ficam internos (comentário em `state.ts:19-21`).
"""

from __future__ import annotations

from typing import TypedDict

from maria.shared.tokens_acumulados import CanalTokensGastos


class EnderecoCadastro(TypedDict, total=False):
    """Endereço montado ao fim. Chave ausente onde develop tem `undefined`
    (regra de estado: dentro de objeto aninhado, `undefined` some no JSON)."""

    cep: str
    logradouro: str
    numero: str
    complemento: str
    bairro: str
    municipio: str
    uf: str


class ColetarEnderecoState(TypedDict, total=False):
    cep: str | None
    logradouro: str | None
    numero: str | None
    complemento: str | None
    bairro: str | None
    municipio: str | None
    uf: str | None
    endereco: EnderecoCadastro
    perguntaAtualTexto: str | None
    perguntaAtualViaIA: bool
    perguntaAtualTokensTotal: int | None
    tokensGastos: CanalTokensGastos
