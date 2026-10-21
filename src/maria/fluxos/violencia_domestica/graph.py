"""Fluxo de violência doméstica (develop: `fluxos/violenciaDomestica/graph.ts`).

Perguntas: é vítima, processo (até 3 tentativas), Boletim de Ocorrência. Depois
identifica a pessoa (subgrafo `identificar_assistido`) e, vindo do orquestrador,
cadastra quem não foi encontrado (`cadastro_pessoa`). Com a pessoa, consulta
CEP, plantão e órgãos e cria o encaminhamento real no Verde.

Reproduzido de develop, com issues abertas para depois da migração:
- sucesso do Verde sem `dados.id` vira `falha_encaminhamento` (#238);
- falha de infra na consulta de órgãos vira "ligue 129", e na de plantão vira
  "sem plantão" (#239);
- a mensagem final mostra o município do órgão (#236);
- soma de tokens composta pelos subgrafos (#230).

Regra de `undefined` × `null` (spec 05, tabela 0.2): `encaminhamentoId` é
conflito, decidido como divergência aceita. `None` ali é o `undefined` de
develop.
"""

from __future__ import annotations

import re
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.fluxos._fabrica import FabricaGrafo, GrafoCompilado
from maria.fluxos.violencia_domestica.api import (
    MENSAGEM_CPF_NAO_ENCONTRADO,
    MENSAGEM_FALHA_CADASTRO,
    MENSAGEM_FALHA_ENCAMINHAMENTO,
    MENSAGEM_NAO_VITIMA,
    MENSAGEM_SEM_ORGAO_DISPONIVEL,
)
from maria.fluxos.violencia_domestica.state import ViolenciaDomesticaState
from maria.ia.reescrever import preparar_pergunta
from maria.integracoes.verde import (
    DadosEncaminhamento,
    consultar_orgaos_plantao_violencia_domestica,
    consultar_orgaos_violencia_domestica,
    consultar_plantao_vigente,
    criar_encaminhamento_violencia_domestica,
)
from maria.integracoes.verde import consultar_cep as consultar_cep_verde
from maria.integracoes.verde import consultar_processo as consultar_processo_verde
from maria.shared import _js
from maria.shared.respostas import resposta_eh_sim
from maria.subgrafos.cadastro_pessoa.graph import grafo as subgrafo_cadastro_pessoa
from maria.subgrafos.identificar_assistido.graph import grafo as subgrafo_identificar_assistido

TEXTO_EH_VITIMA = "Você é a vítima de violência doméstica?"
TEXTO_TEM_PROCESSO = "Existe algum processo relacionado ao seu caso?"
TEXTO_NUMERO_PROCESSO = "Qual o número do processo? Informe apenas os números."
TEXTO_TEM_RO = "Você já registrou o Boletim de Ocorrência (RO) na delegacia?"

Atualizacao = dict[str, Any]

# `\D` de JS sem a flag `u` é "não for 0-9 ASCII"; o `\D` do Python aceita
# dígitos de qualquer alfabeto.
_NAO_DIGITO_ASCII = re.compile(r"[^0-9]")


def numero_processo_formato_valido(valor: str) -> bool:
    # Número CNJ tem 20 dígitos. Só valida: o valor é gravado como veio.
    return len(_NAO_DIGITO_ASCII.sub("", valor)) == 20


def _ler(state: ViolenciaDomesticaState, canal: str) -> Any:
    """`state.<canal>` de develop: AUSENTE se o canal nunca foi escrito."""
    return state.get(canal, _js.AUSENTE)


def _orgao(state: ViolenciaDomesticaState) -> Any:
    # `state.orgaosViolenciaDomestica?.orgaos[0]`: o `?.` só protege o primeiro
    # acesso; `orgaos` ausente lança, como em develop.
    orgaos_vd = _ler(state, "orgaosViolenciaDomestica")
    if orgaos_vd is None or orgaos_vd is _js.AUSENTE:
        return _js.AUSENTE
    return _js.indice(_js.prop(orgaos_vd, "orgaos"), 0)


def _primeiro_endereco(orgao: Any, chave: str) -> Any:
    # `orgao?.enderecos?.[0]?.<chave>`
    enderecos = _js.opt(orgao, "enderecos")
    if enderecos is None or enderecos is _js.AUSENTE:
        return _js.AUSENTE
    return _js.opt(_js.indice(enderecos, 0), chave)


def texto_tentar_novamente_processo(state: ViolenciaDomesticaState) -> str:
    tentativa = _js.coalesce(state.get("tentativasProcesso"), 1)
    return f"Não encontrei esse número de processo (tentativa {_js.texto_template(tentativa)} de 3). Quer tentar de novo?"


async def preparar_pergunta_eh_vitima(state: ViolenciaDomesticaState) -> Atualizacao:
    return dict(await preparar_pergunta("ehVitima", TEXTO_EH_VITIMA))


async def pedir_eh_vitima(state: ViolenciaDomesticaState) -> Atualizacao:
    resposta: str = interrupt(
        {"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_EH_VITIMA), "tipo": "sim_nao", "opcoes": ["Sim", "Não"]}
    )
    return {"ehVitima": resposta_eh_sim(resposta)}


def depois_de_eh_vitima(state: ViolenciaDomesticaState) -> str:
    return "temProcesso" if _js.verdadeiro(_ler(state, "ehVitima")) else "naoEhVitima"


async def nao_eh_vitima(state: ViolenciaDomesticaState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "nao_e_vitima", "mensagemFinal": MENSAGEM_NAO_VITIMA}


async def preparar_pergunta_tem_processo(state: ViolenciaDomesticaState) -> Atualizacao:
    return dict(await preparar_pergunta("temProcesso", TEXTO_TEM_PROCESSO))


async def pedir_tem_processo(state: ViolenciaDomesticaState) -> Atualizacao:
    resposta: str = interrupt(
        {"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_TEM_PROCESSO), "tipo": "sim_nao", "opcoes": ["Sim", "Não"]}
    )
    # Quem já sabe o número costuma digitá-lo direto em vez de "sim".
    if numero_processo_formato_valido(resposta):
        return {"temProcesso": True, "numeroProcesso": resposta, "digitouProcessoDireto": True}
    return {"temProcesso": resposta_eh_sim(resposta), "digitouProcessoDireto": False}


def depois_de_tem_processo(state: ViolenciaDomesticaState) -> str:
    if _js.verdadeiro(_ler(state, "digitouProcessoDireto")):
        return "consultarProcesso"
    return "pedirNumeroProcesso" if _js.verdadeiro(_ler(state, "temProcesso")) else "pedirTemRO"


async def preparar_pergunta_numero_processo(state: ViolenciaDomesticaState) -> Atualizacao:
    return dict(await preparar_pergunta("numeroProcesso", TEXTO_NUMERO_PROCESSO))


async def pedir_numero_processo(state: ViolenciaDomesticaState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_NUMERO_PROCESSO), "tipo": "texto"})
    return {"numeroProcesso": resposta}


async def consultar_processo(state: ViolenciaDomesticaState) -> Atualizacao:
    dados = await consultar_processo_verde(_js.coalesce(state.get("numeroProcesso"), ""))
    tentativas: int = _js.coalesce(state.get("tentativasProcesso"), 0)
    return {"dadosProcesso": dados, "tentativasProcesso": tentativas + 1}


def depois_de_consultar_processo(state: ViolenciaDomesticaState) -> str:
    # Processo é opcional: depois de 3 tentativas, segue para o RO mesmo assim.
    if _js.verdadeiro(_js.opt(_ler(state, "dadosProcesso"), "encontrado")):
        return "temRO"
    return "temRO" if _js.coalesce(state.get("tentativasProcesso"), 0) >= 3 else "tentarNovamente"


async def preparar_pergunta_tentar_novamente_processo(state: ViolenciaDomesticaState) -> Atualizacao:
    return dict(await preparar_pergunta("tentarNovamenteProcesso", texto_tentar_novamente_processo(state)))


async def pergunta_tentar_novamente_processo(state: ViolenciaDomesticaState) -> Atualizacao:
    resposta: str = interrupt(
        {
            "pergunta": _js.coalesce(state.get("perguntaAtualTexto"), texto_tentar_novamente_processo(state)),
            "tipo": "sim_nao",
            "opcoes": ["Sim", "Não"],
        }
    )
    if numero_processo_formato_valido(resposta):
        return {"querTentarNovamenteProcesso": True, "numeroProcesso": resposta, "digitouProcessoDireto": True}
    return {"querTentarNovamenteProcesso": resposta_eh_sim(resposta), "digitouProcessoDireto": False}


def depois_de_pergunta_tentar_processo(state: ViolenciaDomesticaState) -> str:
    if not _js.verdadeiro(_ler(state, "querTentarNovamenteProcesso")):
        return "temRO"
    return "consultarProcesso" if _js.verdadeiro(_ler(state, "digitouProcessoDireto")) else "pedirNumeroProcesso"


async def preparar_pergunta_tem_ro(state: ViolenciaDomesticaState) -> Atualizacao:
    return dict(await preparar_pergunta("temRegistroOcorrencia", TEXTO_TEM_RO))


async def pedir_tem_ro(state: ViolenciaDomesticaState) -> Atualizacao:
    resposta: str = interrupt(
        {"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_TEM_RO), "tipo": "sim_nao", "opcoes": ["Sim", "Não"]}
    )
    return {"temRegistroOcorrencia": resposta_eh_sim(resposta)}


def depois_de_identificar_assistido(state: ViolenciaDomesticaState) -> str:
    if state.get("confirmaAssistido") is False:
        return "naoConfirmado"
    if _js.verdadeiro(_js.opt(_ler(state, "dadosPessoa"), "falhaInfra")):
        return "falhaInfraVerde"
    if _js.verdadeiro(_js.opt(_ler(state, "dadosPessoa"), "encontrado")):
        return "encontrado"
    # Fora do orquestrador não há cadastro: CPF esgotado vira handoff.
    return "cadastrar" if _js.verdadeiro(_ler(state, "viaOrquestrador")) else "cpfEsgotado"


async def cpf_esgotado(state: ViolenciaDomesticaState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "cpf_nao_encontrado", "mensagemFinal": MENSAGEM_CPF_NAO_ENCONTRADO}


async def falha_infra_verde(state: ViolenciaDomesticaState) -> Atualizacao:
    # Sem mensagemFinal: a rota usa a mensagemHandoff do FluxoConfig.
    return {"statusFinal": "handoff_humano", "motivoHandoff": "falha_infra_verde"}


def depois_de_cadastrar_pessoa(state: ViolenciaDomesticaState) -> str:
    # `cadastroErro !== undefined`: develop nunca grava undefined no canal,
    # então o undefined é a chave ausente (regra de estado, tabela 0.2).
    if "cadastroErro" in state:
        return "falhou"
    if state.get("confirmaAssistido") is False:
        return "naoConfirmado"
    return "continuar"


async def falha_cadastro(state: ViolenciaDomesticaState) -> Atualizacao:
    erro = _ler(state, "cadastroErro")
    mensagem = f"{MENSAGEM_FALHA_CADASTRO} ({_js.texto_template(erro)})" if _js.verdadeiro(erro) else MENSAGEM_FALHA_CADASTRO
    return {"statusFinal": "handoff_humano", "motivoHandoff": "falha_cadastro", "mensagemFinal": mensagem}


async def assistido_nao_confirmado(state: ViolenciaDomesticaState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "assistido_nao_confirmado"}


async def consultar_cep(state: ViolenciaDomesticaState) -> Atualizacao:
    dados_pessoa = _ler(state, "dadosPessoa")
    cep = _js.opt(_js.opt(dados_pessoa, "enderecoDetalhado"), "cep")
    if not _js.verdadeiro(cep):
        return {}
    dados_cep = await consultar_cep_verde(cep)
    if not _js.verdadeiro(dados_cep.get("encontrado", _js.AUSENTE)) or not _js.verdadeiro(dados_pessoa):
        return {}
    # `{...enderecoDetalhado, idUf: dadosCep.idUf, ...}`: um id ausente na
    # resposta do CEP sobrescreve com undefined, e o JSON e o checkpoint apagam
    # a chave. Aqui a chave é REMOVIDA, não só deixada de escrever (tabela 0.2).
    # Com valor, a chave que já existia fica na mesma posição, como no spread
    # (a ordem chega aos metadados, comparados byte a byte).
    endereco: dict[str, Any] = dict(dados_pessoa["enderecoDetalhado"])
    for chave in ("idUf", "idBairro", "idMunicipio"):
        valor = dados_cep.get(chave, _js.AUSENTE)
        if valor is _js.AUSENTE:
            endereco.pop(chave, None)
        else:
            endereco[chave] = valor
    return {"dadosPessoa": {**dados_pessoa, "enderecoDetalhado": endereco}}


async def consultar_plantao(state: ViolenciaDomesticaState) -> Atualizacao:
    # Lista vazia = fora de horário de plantão.
    plantoes = await consultar_plantao_vigente()
    return {"plantaoIds": [p["id"] for p in plantoes]}


async def consultar_orgaos(state: ViolenciaDomesticaState) -> Atualizacao:
    id_pessoa: int = _js.coalesce(_js.opt(_ler(state, "dadosPessoa"), "idPessoa"), 0)
    plantao_ids: list[int | None] = _js.coalesce(state.get("plantaoIds"), [])
    if len(plantao_ids) > 0:
        resultado = await consultar_orgaos_plantao_violencia_domestica(plantao_ids, id_pessoa)
    else:
        resultado = await consultar_orgaos_violencia_domestica(_js.coalesce(state.get("temRegistroOcorrencia"), False), id_pessoa)
    return {"orgaosViolenciaDomestica": resultado}


def depois_de_consultar_orgaos(state: ViolenciaDomesticaState) -> str:
    # `orgaos?.contactarCrc || !orgaos?.orgaos.length`
    orgaos_vd = _ler(state, "orgaosViolenciaDomestica")
    if _js.verdadeiro(_js.opt(orgaos_vd, "contactarCrc")):
        return "semOrgao"
    if orgaos_vd is None or orgaos_vd is _js.AUSENTE:
        return "semOrgao"
    lista = _js.prop(orgaos_vd, "orgaos")
    tamanho = _js.prop(lista, "length") if not isinstance(lista, list) else len(lista)
    return "prosseguir" if _js.verdadeiro(tamanho) else "semOrgao"


async def sem_orgao_disponivel(state: ViolenciaDomesticaState) -> Atualizacao:
    mensagem = _js.coalesce(_js.opt(_ler(state, "orgaosViolenciaDomestica"), "mensagemCrc"), MENSAGEM_SEM_ORGAO_DISPONIVEL)
    return {"statusFinal": "handoff_humano", "motivoHandoff": "sem_orgao_disponivel", "mensagemFinal": mensagem}


async def criar_encaminhamento(state: ViolenciaDomesticaState) -> Atualizacao:
    orgao = _orgao(state)
    dados: DadosEncaminhamento = {
        "idPessoa": _js.coalesce(_js.opt(_ler(state, "dadosPessoa"), "idPessoa"), 0),
        "idOrgao": _js.coalesce(_js.opt(orgao, "id"), 0),
        "urgente": _js.verdadeiro(_ler(state, "temRegistroOcorrencia")),
    }
    # Argumento aninhado que vira JSON: ausente é omitido, null do Verde vai
    # como null (tabela 0.2).
    id_local = _primeiro_endereco(orgao, "idLocalAtendimento")
    if id_local is not _js.AUSENTE:
        dados["idLocalAtendimento"] = id_local
    resultado = await criar_encaminhamento_violencia_domestica(dados)
    if resultado["sucesso"]:
        # Sucesso sem `dados.id` grava undefined em develop: aqui, None (#238).
        return {"encaminhamentoId": resultado.get("id")}
    return {"encaminhamentoErro": _js.coalesce(resultado.get("erro"), "erro desconhecido")}


def depois_de_criar_encaminhamento(state: ViolenciaDomesticaState) -> str:
    # `encaminhamentoId !== undefined`. Conflito da tabela 0.2: None é o
    # undefined, e um `id: null` do Verde também vai para falha (divergência
    # aceita, MIGRACAO.md).
    return "concluir" if state.get("encaminhamentoId") is not None else "falhou"


async def falha_encaminhamento(state: ViolenciaDomesticaState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "falha_encaminhamento", "mensagemFinal": MENSAGEM_FALHA_ENCAMINHAMENTO}


def montar_mensagem_encaminhamento(orgao: Any, urgente: bool, encaminhamento_id: Any) -> str:
    municipio = _primeiro_endereco(orgao, "municipio")
    localizacao = f" ({_js.texto_template(municipio)})" if _js.verdadeiro(municipio) else ""
    protocolo = f" Protocolo: {_js.texto_template(encaminhamento_id)}." if encaminhamento_id is not None else ""
    nome = _js.texto_template(_js.prop(orgao, "nome"))
    if urgente:
        return (
            f"Como você já tem Boletim de Ocorrência, vou encaminhar seu atendimento com urgência para {nome}{localizacao}"
            f" — sem necessidade de agendamento.{protocolo}"
        )
    return f"Vou encaminhar seu caso para {nome}{localizacao}.{protocolo}"


async def concluir(state: ViolenciaDomesticaState) -> Atualizacao:
    orgao = _orgao(state)
    urgente = _js.verdadeiro(_ler(state, "temRegistroOcorrencia"))
    mensagem = (
        montar_mensagem_encaminhamento(orgao, urgente, state.get("encaminhamentoId"))
        if _js.verdadeiro(orgao)
        else MENSAGEM_SEM_ORGAO_DISPONIVEL
    )
    return {"statusFinal": "concluido", "tipoEncaminhamento": "urgente" if urgente else "padrao", "mensagemFinal": mensagem}


_construtor = StateGraph(ViolenciaDomesticaState)
_construtor.add_node("prepararPerguntaEhVitima", preparar_pergunta_eh_vitima)
_construtor.add_node("pedirEhVitima", pedir_eh_vitima)
_construtor.add_node("naoEhVitima", nao_eh_vitima)
_construtor.add_node("prepararPerguntaTemProcesso", preparar_pergunta_tem_processo)
_construtor.add_node("pedirTemProcesso", pedir_tem_processo)
_construtor.add_node("prepararPerguntaNumeroProcesso", preparar_pergunta_numero_processo)
_construtor.add_node("pedirNumeroProcesso", pedir_numero_processo)
_construtor.add_node("consultarProcesso", consultar_processo)
_construtor.add_node("prepararPerguntaTentarNovamenteProcesso", preparar_pergunta_tentar_novamente_processo)
_construtor.add_node("perguntaTentarNovamenteProcesso", pergunta_tentar_novamente_processo)
_construtor.add_node("prepararPerguntaTemRO", preparar_pergunta_tem_ro)
_construtor.add_node("pedirTemRO", pedir_tem_ro)
_construtor.add_node("identificarAssistido", subgrafo_identificar_assistido)
_construtor.add_node("cadastroPessoa", subgrafo_cadastro_pessoa)
_construtor.add_node("falhaCadastro", falha_cadastro)
_construtor.add_node("assistidoNaoConfirmado", assistido_nao_confirmado)
_construtor.add_node("cpfEsgotado", cpf_esgotado)
_construtor.add_node("falhaInfraVerde", falha_infra_verde)
_construtor.add_node("consultarCep", consultar_cep)
_construtor.add_node("consultarPlantao", consultar_plantao)
_construtor.add_node("consultarOrgaos", consultar_orgaos)
_construtor.add_node("semOrgaoDisponivel", sem_orgao_disponivel)
_construtor.add_node("criarEncaminhamento", criar_encaminhamento)
_construtor.add_node("falhaEncaminhamento", falha_encaminhamento)
_construtor.add_node("concluir", concluir)
_construtor.add_edge(START, "prepararPerguntaEhVitima")
_construtor.add_edge("prepararPerguntaEhVitima", "pedirEhVitima")
_construtor.add_conditional_edges(
    "pedirEhVitima", depois_de_eh_vitima, {"temProcesso": "prepararPerguntaTemProcesso", "naoEhVitima": "naoEhVitima"}
)
_construtor.add_edge("naoEhVitima", END)
_construtor.add_edge("prepararPerguntaTemProcesso", "pedirTemProcesso")
_construtor.add_conditional_edges(
    "pedirTemProcesso",
    depois_de_tem_processo,
    {
        "pedirNumeroProcesso": "prepararPerguntaNumeroProcesso",
        "pedirTemRO": "prepararPerguntaTemRO",
        "consultarProcesso": "consultarProcesso",
    },
)
_construtor.add_edge("prepararPerguntaNumeroProcesso", "pedirNumeroProcesso")
_construtor.add_edge("pedirNumeroProcesso", "consultarProcesso")
_construtor.add_conditional_edges(
    "consultarProcesso",
    depois_de_consultar_processo,
    {"temRO": "prepararPerguntaTemRO", "tentarNovamente": "prepararPerguntaTentarNovamenteProcesso"},
)
_construtor.add_edge("prepararPerguntaTentarNovamenteProcesso", "perguntaTentarNovamenteProcesso")
_construtor.add_conditional_edges(
    "perguntaTentarNovamenteProcesso",
    depois_de_pergunta_tentar_processo,
    {"pedirNumeroProcesso": "prepararPerguntaNumeroProcesso", "temRO": "prepararPerguntaTemRO", "consultarProcesso": "consultarProcesso"},
)
_construtor.add_edge("prepararPerguntaTemRO", "pedirTemRO")
_construtor.add_edge("pedirTemRO", "identificarAssistido")
_construtor.add_conditional_edges(
    "identificarAssistido",
    depois_de_identificar_assistido,
    {
        "encontrado": "consultarCep",
        "cadastrar": "cadastroPessoa",
        "naoConfirmado": "assistidoNaoConfirmado",
        "cpfEsgotado": "cpfEsgotado",
        "falhaInfraVerde": "falhaInfraVerde",
    },
)
_construtor.add_conditional_edges(
    "cadastroPessoa",
    depois_de_cadastrar_pessoa,
    {"continuar": "consultarCep", "falhou": "falhaCadastro", "naoConfirmado": "assistidoNaoConfirmado"},
)
_construtor.add_edge("falhaCadastro", END)
_construtor.add_edge("assistidoNaoConfirmado", END)
_construtor.add_edge("cpfEsgotado", END)
_construtor.add_edge("falhaInfraVerde", END)
_construtor.add_edge("consultarCep", "consultarPlantao")
_construtor.add_edge("consultarPlantao", "consultarOrgaos")
_construtor.add_conditional_edges(
    "consultarOrgaos", depois_de_consultar_orgaos, {"semOrgao": "semOrgaoDisponivel", "prosseguir": "criarEncaminhamento"}
)
_construtor.add_edge("semOrgaoDisponivel", END)
_construtor.add_conditional_edges(
    "criarEncaminhamento", depois_de_criar_encaminhamento, {"concluir": "concluir", "falhou": "falhaEncaminhamento"}
)
_construtor.add_edge("falhaEncaminhamento", END)
_construtor.add_edge("concluir", END)

_fabrica = FabricaGrafo(_construtor)
criar_grafo = _fabrica.criar


def obter_grafo() -> GrafoCompilado:
    return _fabrica.obter()
