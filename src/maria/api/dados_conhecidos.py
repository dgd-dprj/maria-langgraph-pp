"""O que a Tykhe pode pré-preencher em `dadosConhecidos` (#240).

O LangGraph aceita na entrada qualquer canal do estado do fluxo, então um campo interno vindo da Tykhe
mudava o desfecho: com `encaminhamentoId` pré-preenchido e o encaminhamento falhando, a pessoa recebia
"Protocolo: <valor>" de um encaminhamento que não existia. Decisão da Nicole (2026-11-17): barrar os
campos internos dos fluxos (desfecho, contadores, resultados de consulta ao Verde e marcas de etapa), e
deixar passar os dados da pessoa (`cpf`, `nome`, `idPessoa`, `email`, `endereco`, `parentesco`...).

O `viaOrquestrador` fica fora desta lista: `criar_atendimento` já o descarta sem aviso desde a #191, e a
gravação desse caso (`violencia-domestica-criar-200`) continua igual.

O filtro vale só onde o `dadosConhecidos` **da Tykhe** entra: a rota `POST /atendimentos` e o corpo das
rotas do orquestrador. O próprio orquestrador repassa ao fluxo campos que são dele (`tokensGastos`), depois
do filtro. O nome de cada campo descartado vai para o log, nunca o valor.
"""

from __future__ import annotations

from typing import Any

# Desfechos, resultados de consulta, confirmações e marcas internas: nunca vêm de fora.
CAMPOS_INTERNOS = frozenset(
    {
        "statusFinal",
        "motivoHandoff",
        "mensagemFinal",
        "tipoEncaminhamento",
        "destino",
        "encaminhamentoId",
        "encaminhamentoErro",
        "cadastroErro",
        "erroCpfOutra",
        "tokensGastos",
        "cpfDaTykhe",
        "confirmaAssistido",
        "confirmaNome",
        "confirmado",
        "orgaosViolenciaDomestica",
        "plantaoIds",
        "dadosProcesso",
        "statusConsultaProcesso",
        "dadosApenado",
        "dadosPessoa",
        "dadosOutraPessoa",
        "perguntaParentesco",
        "opcoesParentesco",
    }
)
# Contadores de tentativa, respostas de "tentar de novo", marcas de "digitou direto" e a pergunta atual.
PREFIXOS_INTERNOS = ("tentativas", "recusas", "querTentarNovamente", "digitou", "perguntaAtual")


def eh_interno(campo: str) -> bool:
    return campo in CAMPOS_INTERNOS or campo.startswith(PREFIXOS_INTERNOS)


def sem_campos_internos(dados: Any, log: Any, origem: str) -> Any:
    """`dadosConhecidos` sem os campos internos dos fluxos. O que não é dicionário volta igual (a rota
    trata como hoje). Cada campo descartado vai para o log pelo nome, para a Tykhe saber que mandou algo
    fora do contrato. `log` é o logger da requisição (`LogRequisicao`); só o `warn` é usado."""
    if not isinstance(dados, dict):
        return dados
    descartados = sorted(campo for campo in dados if isinstance(campo, str) and eh_interno(campo))
    if not descartados:
        return dados
    log.warn(
        "dadosConhecidos com campo interno do fluxo: descartado",
        evento="dados_conhecidos_descartados",
        campos=descartados,
        origem=origem,
    )
    return {campo: valor for campo, valor in dados.items() if campo not in descartados}
