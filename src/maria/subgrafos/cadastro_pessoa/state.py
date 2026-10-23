"""Estado do subgrafo `cadastro_pessoa` (develop: `subgrafos/cadastroPessoa/state.ts`).

Nomes de canal em camelCase, como em develop: compartilhados por nome com os
fluxos pai e com o `coletar_endereco` embutido (só `endereco`, `perguntaAtual*`
e `tokensGastos` existem nos dois).
"""

from __future__ import annotations

from typing import TypedDict

from maria.shared.tokens_acumulados import CanalTokensGastos
from maria.shared.types import DadosPessoa
from maria.subgrafos.coletar_endereco.state import EnderecoCadastro


class CadastroPessoaState(TypedDict, total=False):
    cpf: str | None
    nome: str | None
    dataNascimento: str | None
    endereco: EnderecoCadastro
    dadosPessoa: DadosPessoa
    cadastroErro: str | None
    confirmaAssistido: bool | None
    viaOrquestrador: bool | None
    perguntaAtualTexto: str | None
    perguntaAtualViaIA: bool
    perguntaAtualTokensTotal: int | None
    tokensGastos: CanalTokensGastos
