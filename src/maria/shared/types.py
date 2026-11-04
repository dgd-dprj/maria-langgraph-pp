"""Tipos compartilhados entre fluxos (`fluxos/*`) e integrações (`integracoes/*`).

Não pertencem a um fluxo específico, então não moram no `state.py` de nenhum
fluxo. Os nomes de campo ficam em camelCase: esses objetos vão para o estado
do grafo e, a partir dele, para `metadados` na resposta à Tykhe.

`TypedDict(total=False)` com `Required[...]` reproduz o `campo?:` do
TypeScript: um campo opcional ausente fica ausente, e não `None`.

`int | None` em `DadosApenado.idPessoa`, `DadosProcesso.id`,
`DadosPessoa.idPessoa`, `Plantao.id`, `ResultadoEncaminhamento.id` e
`ResultadoCadastroPessoa.idPessoa`: o Verde pode devolver `null` nesses campos,
e develop preserva o `null` (chave presente com `null` conta como encontrado
ou sucesso; ver a spec do módulo integracoes, tabela 3.3). Em TypeScript eles
eram `number` e recebiam `null` em execução; aqui o tipo diz a verdade.
"""

from __future__ import annotations

from typing import Literal, Required, TypedDict


class Pergunta(TypedDict, total=False):
    pergunta: Required[str]
    tipo: Required[Literal["texto", "sim_nao", "opcoes"]]
    opcoes: list[str]


class DadosApenado(TypedDict, total=False):
    encontrado: Required[bool]
    idSeap: int
    idPessoa: int | None
    nome: str
    situacao: str
    # Confirmados ao vivo em 2026-09-09: o Verde já devolve os dois no /apenado.
    # Usados no payload de encaminhamento do fluxo prisional.
    tipoPreso: str
    regime: str
    # Issue #172: distingue "RG não encontrado de verdade" de "não consegui nem
    # verificar" (401/403/5xx mesmo depois do retry automático). Os fluxos tratam
    # esse caso como handoff_humano direto, sem o retry de negócio.
    falhaInfra: bool


class MovimentoProcesso(TypedDict, total=False):
    titulo: str
    data: str
    descricao: str
    # Explicação em linguagem simples para o cidadão; vem pronta do Verde.
    traducao: str


class DadosProcesso(TypedDict, total=False):
    encontrado: Required[bool]
    id: int | None
    origem: str
    instancia: int
    nomeAssunto: str
    nomeOrgaoJulgador: str
    movimentos: list[MovimentoProcesso]


class EnderecoDetalhado(TypedDict, total=False):
    """Issue #127: só ids e CEP. `idUf` vem sempre; `idBairro` e `idMunicipio`
    ficam ausentes quando o Verde não tem o dado para o CEP."""

    cep: str
    idUf: int
    idBairro: int
    idMunicipio: int


class DadosPessoa(TypedDict, total=False):
    encontrado: Required[bool]
    idPessoa: int | None
    nome: str
    nomeSocial: str
    genero: str
    endereco: str
    enderecoDetalhado: EnderecoDetalhado
    # Issue #172: mesmo racional de DadosApenado.falhaInfra.
    falhaInfra: bool


class DadosCep(TypedDict, total=False):
    """Issue #127 (ids) e #176 (textos, usados pelo subgrafo coletarEndereco
    para não perguntar de novo o que o Verde já sabe)."""

    encontrado: Required[bool]
    idUf: int
    idBairro: int
    idMunicipio: int
    uf: str
    bairro: str
    municipio: str
    logradouro: str
    # Mesmo racional de DadosPessoa.falhaInfra: o Verde falhou (401/403/5xx), não "CEP não encontrado".
    falhaInfra: bool


class HorarioUrgencia(TypedDict, total=False):
    diaDaSemana: str
    horaInicio: str
    horaFim: str
    informacaoComplementar: str


class EnderecoOrgao(TypedDict, total=False):
    logradouro: str
    numero: str
    complemento: str
    cep: str
    bairro: str
    municipio: str
    uf: str
    # Vai como idLocalAtendimento no POST /integra/encaminhamento/encaminhar.
    idLocalAtendimento: int
    horariosUrgencia: list[HorarioUrgencia]
    horariosAtendimentoFormatado: str
    horariosUrgenciaFormatado: str


class OrgaoAtendimento(TypedDict, total=False):
    id: Required[int]
    nome: Required[str]
    enderecos: list[EnderecoOrgao]


class OrgaosViolenciaDomestica(TypedDict, total=False):
    encontrado: Required[bool]
    # O Verde devolve em ordem de prioridade; o primeiro item é o escolhido.
    orgaos: Required[list[OrgaoAtendimento]]
    # True só quando indicacaoRO é true e o Verde não achou nenhum órgão.
    # mensagemCrc vem pronta do Verde ("...ligar 129").
    contactarCrc: bool
    mensagemCrc: str


class OrgaosPrimeiroAtendimento(TypedDict, total=False):
    """`GET /orgao/primeiro-atendimento`: órgãos habilitados para o assunto e a pessoa."""

    encontrado: Required[bool]
    orgaos: Required[list[OrgaoAtendimento]]
    # Mesmo racional de DadosPessoa.falhaInfra.
    falhaInfra: bool


class Plantao(TypedDict, total=False):
    """GET /integra/plantao/vigente: lista vazia = fora de horário de plantão."""

    id: Required[int | None]
    tipo: str


class ResultadoEncaminhamento(TypedDict, total=False):
    sucesso: Required[bool]
    # Só com sucesso: id do encaminhamento criado no Verde (protocolo).
    id: int | None
    # Só sem sucesso.
    erro: str


class ResultadoCadastroPessoa(TypedDict, total=False):
    """Issue #171: cadastro de pessoa nova no Verde (POST /integra/pessoa)."""

    sucesso: Required[bool]
    idPessoa: int | None
    erro: str
