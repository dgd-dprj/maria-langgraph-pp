"""Fluxo de pessoa presa (develop: `fluxos/pessoaPresa/graph.ts`).

Perguntas: relato livre (só com `EXTRACAO_LIVRE_IA`), processo, número, RG (até
3 tentativas), confirmação do nome da pessoa presa e parentesco (classificado
por IA). Vindo do orquestrador, identifica quem pede (`identificar_assistido`)
e cadastra quem não foi encontrado (`cadastro_pessoa`).

Reproduzido de develop, com issues abertas para depois da migração:
- `pedirConfirmaNome` mostra o nome do apenado a partir do RG digitado (#236);
- parentesco não validado, e a lista difere da do SIPEN (#212);
- `situacao`, `tipoPreso` ou `regime` com `null` do Verde lançam TypeError no
  `concluir`, como o `null.toUpperCase()` de develop (spec 05, 3.2).

Regra de `undefined` × `null` (spec 05, tabela 0.2): `temProcesso`,
`numeroProcesso` e `parentesco` são guardados pela presença da chave; `rg` é
conflito, decidido como divergência aceita (`None` é o undefined de develop).
"""

from __future__ import annotations

import os
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.fluxos._fabrica import FabricaGrafo, GrafoCompilado
from maria.fluxos.pessoa_presa.api import (
    MENSAGEM_FALHA_CADASTRO,
    MENSAGEM_HANDOFF_ORIGEM_NAO_SUPORTADA,
    MENSAGEM_HANDOFF_SEM_NUMERO_PROCESSO,
)
from maria.fluxos.pessoa_presa.state import PessoaPresaState
from maria.ia.classificar import classificar_entre_opcoes
from maria.ia.extrair import extrair_campos_livre
from maria.ia.reescrever import preparar_pergunta
from maria.integracoes.verde import consultar_apenado_por_rg
from maria.integracoes.verde import consultar_processo as consultar_processo_verde
from maria.shared import _js
from maria.shared.respostas import resposta_eh_sim
from maria.subgrafos.cadastro_pessoa.graph import grafo as subgrafo_cadastro_pessoa
from maria.subgrafos.identificar_assistido.graph import grafo as subgrafo_identificar_assistido

# Só processos de execução penal no SEEU, por enquanto. Igualdade estrita,
# sensível a caixa, como em develop.
ORIGEM_PROCESSO_SUPORTADA = "SEEU"

SITUACOES_PERMITIDAS = frozenset(
    {
        "ATIVO",
        "RESDOM",
        "TRABALHO EXTRAMURO",
        "BAIXA HOSPITALAR",
        "VPF",
        "VPF/TRABALHO EXTRAMURO",
        "VPF/ATIVIDADE EDUCACIONAL",
        "ABERTO/DOMICÍLIO COVID-19",
    }
)
TIPO_PRESO_PERMITIDO = "CONDENADO"
REGIMES_PERMITIDOS = frozenset({"FECHADO", "SEMIABERTO"})

TEXTO_LIVRE = (
    "Pode me contar a situação com suas palavras? Se já souber, pode falar o número do processo, "
    "o RG da pessoa presa e seu parentesco com ela — tudo de uma vez."
)
TEXTO_TEM_PROCESSO = "Você tem o número do processo da pessoa que está presa?"
TEXTO_NUMERO_PROCESSO = "Qual o número do processo? Informe apenas os números."
TEXTO_RG = "Qual o RG da pessoa presa? Informe apenas os números."
TEXTO_RG_INVALIDO = "O RG deve conter apenas números. Qual o RG da pessoa presa? Informe apenas os números."
TEXTO_PARENTESCO = "Qual seu parentesco com a pessoa presa?"

PARENTESCOS_PERMITIDOS = [
    "Mãe",
    "Pai",
    "Irmão(a)",
    "Esposo(a)",
    "Ex-esposo(a)",
    "Companheiro(a)",
    "Filho(a)",
    "Amigo(a)",
    "Primo(a)",
    "Tio(a)",
    "Sobrinho(a)",
    "Avô/Avó",
    "Cunhado(a)",
    "Sogro(a)",
    "Outro",
]

SISTEMA_PARENTESCO = f"""Você classifica o parentesco de quem busca informação sobre uma pessoa presa, na Defensoria Pública do RJ, a partir de um relato livre.
Parentescos possíveis: {", ".join(PARENTESCOS_PERMITIDOS)}.
Regras: escolha o que melhor descreve a relação, mesmo que o relato seja indireto (ex: "fui casada com ele mas já nos divorciamos" → "Ex-esposo(a)"). Se não bater com confiança em nenhum, responda "nenhum"."""  # noqa: E501

Atualizacao = dict[str, Any]

# `/^EM\s+/` de JS: o `\s` de lá é Unicode e inclui U+FEFF, mas não `\x1c` a
# `\x1f`, ao contrário do `\s` do Python.
_PREFIXO_EM = re.compile(f"^EM{_js.CLASSE_ESPACO_JS}+")
# `/^\d+$/` de JS: só 0-9 ASCII, com casamento completo (`fullmatch`, e não o
# `$` do Python, que aceita um `\n` final).
_SO_DIGITOS_ASCII = re.compile(r"[0-9]+")


def _ler(state: PessoaPresaState, canal: str) -> Any:
    """`state.<canal>` de develop: AUSENTE se o canal nunca foi escrito."""
    return state.get(canal, _js.AUSENTE)


def _to_upper_case(valor: Any, nome: str) -> str:
    """`valor.toUpperCase()` de JS: lança TypeError com null e com não string."""
    if isinstance(valor, str):
        return valor.upper()
    if valor is None:
        raise TypeError("Cannot read properties of null (reading 'toUpperCase')")
    raise TypeError(f"{nome}.toUpperCase is not a function")


def normalizar_situacao(situacao: Any) -> str:
    """O Verde devolve "EM VPF/TRABALHO EXTRAMURO"; a lista usa "VPF/TRABALHO EXTRAMURO"."""
    partes = _to_upper_case(situacao, "situacao").split("/")
    return "/".join(_PREFIXO_EM.sub("", _js.trim_js(parte), count=1) for parte in partes)


def dados_apenado_atendidos(state: PessoaPresaState) -> bool:
    # `const { situacao, tipoPreso, regime } = state.dadosApenado ?? {}`
    dados = _js.coalesce(_ler(state, "dadosApenado"), {})
    situacao = _js.prop(dados, "situacao")
    tipo_preso = _js.prop(dados, "tipoPreso")
    regime = _js.prop(dados, "regime")
    if situacao is _js.AUSENTE or tipo_preso is _js.AUSENTE or regime is _js.AUSENTE:
        return False
    # `&&` com curto-circuito: só o primeiro null encontrado lança.
    return (
        normalizar_situacao(situacao) in SITUACOES_PERMITIDAS
        and _to_upper_case(tipo_preso, "tipoPreso") == TIPO_PRESO_PERMITIDO
        and _to_upper_case(regime, "regime") in REGIMES_PERMITIDOS
    )


def extracao_livre_habilitada() -> bool:
    # Lida a cada chamada, como em develop.
    return os.environ.get("EXTRACAO_LIVRE_IA") == "true"


def rg_formato_valido(rg: Any) -> bool:
    """`z.string().trim().regex(/^\\d+$/)`: o trim vale só para validar."""
    return isinstance(rg, str) and _SO_DIGITOS_ASCII.fullmatch(_js.trim_js(rg)) is not None


def rg_veio_da_extracao(state: PessoaPresaState) -> bool:
    # `state.rg !== undefined`. Conflito da tabela 0.2: None é o undefined
    # gravado por `prepararPerguntaRgInvalido`, e um `rg: null` da Tykhe também
    # pergunta (divergência aceita, MIGRACAO.md).
    return state.get("rg") is not None and _js.coalesce(state.get("tentativasRg"), 0) == 0


def texto_tentar_novamente(state: PessoaPresaState) -> str:
    tentativa = _js.coalesce(state.get("tentativasRg"), 1)
    return f"Não encontrei ninguém com esse RG (tentativa {_js.texto_template(tentativa)} de 3). Quer tentar de novo?"


def texto_confirma_nome(state: PessoaPresaState) -> str:
    nome = _js.coalesce(_js.opt(_ler(state, "dadosApenado"), "nome"), "essa pessoa")
    return f"Confirma que a pessoa presa é {_js.texto_template(nome)}?"


async def preparar_pergunta_livre(state: PessoaPresaState) -> Atualizacao:
    return dict(await preparar_pergunta("relatoLivre", TEXTO_LIVRE))


async def pedir_livre(state: PessoaPresaState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_LIVRE), "tipo": "texto"})
    extraido = await extrair_campos_livre(resposta)
    # `...(extraido.x !== undefined ? { x } : {})`: o null do modelo é gravado.
    atualizacao: Atualizacao = {}
    for campo in ("temProcesso", "numeroProcesso", "rg", "parentesco"):
        if campo in extraido:
            atualizacao[campo] = extraido[campo]
    atualizacao["tokensGastos"] = {
        "input": _js.coalesce(extraido.get("tokensEntrada"), 0),
        "output": _js.coalesce(extraido.get("tokensSaida"), 0),
        "total": _js.coalesce(extraido.get("tokensTotal"), 0),
    }
    return atualizacao


def roteamento_inicial(state: PessoaPresaState) -> str:
    return "comExtracao" if extracao_livre_habilitada() else "semExtracao"


# Bypass das perguntas: `state.x !== undefined` em develop. Nenhum destes
# canais recebe undefined em develop, então o undefined é a chave ausente, e
# um null (Tykhe ou modelo) também pula a pergunta (tabela 0.2).


async def preparar_pergunta_tem_processo(state: PessoaPresaState) -> Atualizacao:
    if "temProcesso" in state:
        return {}
    return dict(await preparar_pergunta("temProcesso", TEXTO_TEM_PROCESSO))


async def pedir_tem_processo(state: PessoaPresaState) -> Atualizacao:
    if "temProcesso" in state:
        return {}
    resposta: str = interrupt(
        {"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_TEM_PROCESSO), "tipo": "sim_nao", "opcoes": ["Sim", "Não"]}
    )
    return {"temProcesso": resposta_eh_sim(resposta)}


async def preparar_pergunta_numero_processo(state: PessoaPresaState) -> Atualizacao:
    if "numeroProcesso" in state:
        return {}
    return dict(await preparar_pergunta("numeroProcesso", TEXTO_NUMERO_PROCESSO))


async def pedir_numero_processo(state: PessoaPresaState) -> Atualizacao:
    if "numeroProcesso" in state:
        return {}
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_NUMERO_PROCESSO), "tipo": "texto"})
    return {"numeroProcesso": resposta}


async def consultar_processo(state: PessoaPresaState) -> Atualizacao:
    # Sem contagem de tentativas: o processo não tem retry neste fluxo.
    dados = await consultar_processo_verde(_js.coalesce(state.get("numeroProcesso"), ""))
    return {"dadosProcesso": dados}


async def preparar_pergunta_rg(state: PessoaPresaState) -> Atualizacao:
    if rg_veio_da_extracao(state):
        return {}
    return dict(await preparar_pergunta("rg", TEXTO_RG))


async def pedir_rg(state: PessoaPresaState) -> Atualizacao:
    if rg_veio_da_extracao(state):
        return {}
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_RG), "tipo": "texto"})
    return {"rg": resposta}


def depois_de_tem_processo(state: PessoaPresaState) -> str:
    return "pedirNumeroProcesso" if _js.verdadeiro(_ler(state, "temProcesso")) else "pedirRg"


def depois_de_pedir_rg(state: PessoaPresaState) -> str:
    return "valido" if rg_formato_valido(_js.coalesce(state.get("rg"), "")) else "invalido"


async def preparar_pergunta_rg_invalido(state: PessoaPresaState) -> Atualizacao:
    preparado = await preparar_pergunta("rgInvalido", TEXTO_RG_INVALIDO)
    # `{ ...preparado, rg: undefined }`: limpa o RG inválido para o pedirRg
    # perguntar de novo (regra de estado: undefined no canal vira None).
    return {**preparado, "rg": None}


async def consultar_apenado(state: PessoaPresaState) -> Atualizacao:
    dados = await consultar_apenado_por_rg(_js.coalesce(state.get("rg"), ""))
    tentativas: int = _js.coalesce(state.get("tentativasRg"), 0)
    return {"dadosApenado": dados, "tentativasRg": tentativas + 1}


def depois_de_consultar_apenado(state: PessoaPresaState) -> str:
    apenado = _ler(state, "dadosApenado")
    if _js.verdadeiro(_js.opt(apenado, "encontrado")):
        return "pedirConfirmaNome"
    # Issue #172: falha de infra sai direto, sem o "quer tentar de novo?".
    if _js.verdadeiro(_js.opt(apenado, "falhaInfra")):
        return "naoConfirmado"
    if _js.coalesce(state.get("tentativasRg"), 0) >= 3:
        return "naoConfirmado"
    return "perguntaTentarNovamente"


async def preparar_pergunta_tentar_novamente(state: PessoaPresaState) -> Atualizacao:
    return dict(await preparar_pergunta("tentarNovamenteRg", texto_tentar_novamente(state)))


async def pergunta_tentar_novamente(state: PessoaPresaState) -> Atualizacao:
    resposta: str = interrupt(
        {
            "pergunta": _js.coalesce(state.get("perguntaAtualTexto"), texto_tentar_novamente(state)),
            "tipo": "sim_nao",
            "opcoes": ["Sim", "Não"],
        }
    )
    # Qualquer resposta só com dígitos (inclusive "1") é RG digitado direto.
    if rg_formato_valido(resposta):
        return {"querTentarNovamente": True, "rg": resposta, "digitouRgDireto": True}
    return {"querTentarNovamente": resposta_eh_sim(resposta), "digitouRgDireto": False}


def depois_de_pergunta_tentar(state: PessoaPresaState) -> str:
    if not _js.verdadeiro(_ler(state, "querTentarNovamente")):
        return "naoConfirmado"
    return "consultarApenado" if _js.verdadeiro(_ler(state, "digitouRgDireto")) else "pedirRg"


async def preparar_pergunta_confirma_nome(state: PessoaPresaState) -> Atualizacao:
    return dict(await preparar_pergunta("confirmaNome", texto_confirma_nome(state)))


async def pedir_confirma_nome(state: PessoaPresaState) -> Atualizacao:
    resposta: str = interrupt(
        {
            "pergunta": _js.coalesce(state.get("perguntaAtualTexto"), texto_confirma_nome(state)),
            "tipo": "sim_nao",
            "opcoes": ["Sim", "Não"],
        }
    )
    return {"confirmaNome": resposta_eh_sim(resposta)}


async def preparar_pergunta_parentesco(state: PessoaPresaState) -> Atualizacao:
    if "parentesco" in state:
        return {}
    return dict(await preparar_pergunta("parentesco", TEXTO_PARENTESCO))


class ResultadoClassificarParentesco(TypedDict, total=False):
    parentesco: Any
    tokensTotal: Any
    tokensEntrada: Any
    tokensSaida: Any


async def classificar_parentesco(resposta_livre: str) -> ResultadoClassificarParentesco:
    # `NODE_ENV === "test"` em develop. `??`: uma variável vazia passa como "".
    if os.environ.get("APP_ENV") == "test":
        return {"parentesco": _js.coalesce(os.environ.get("MOCK_CLASSIFICACAO_PARENTESCO"), "Outro")}
    resultado = await classificar_entre_opcoes(resposta_livre, SISTEMA_PARENTESCO, PARENTESCOS_PERMITIDOS)
    return {
        "parentesco": _js.coalesce(resultado.get("escolhaId"), "Outro"),
        "tokensTotal": resultado.get("tokensTotal"),
        "tokensEntrada": resultado.get("tokensEntrada"),
        "tokensSaida": resultado.get("tokensSaida"),
    }


async def pedir_parentesco(state: PessoaPresaState) -> Atualizacao:
    if "parentesco" in state:
        return {}
    resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_PARENTESCO), "tipo": "texto"})
    classificado = await classificar_parentesco(resposta)
    return {
        "parentesco": classificado["parentesco"],
        "tokensGastos": {
            "input": _js.coalesce(classificado.get("tokensEntrada"), 0),
            "output": _js.coalesce(classificado.get("tokensSaida"), 0),
            "total": _js.coalesce(classificado.get("tokensTotal"), 0),
        },
    }


async def concluir(state: PessoaPresaState) -> Atualizacao:
    if state.get("temProcesso") is False:
        return {
            "statusFinal": "handoff_humano",
            "motivoHandoff": "sem_numero_processo",
            "mensagemFinal": MENSAGEM_HANDOFF_SEM_NUMERO_PROCESSO,
        }
    if _js.opt(_ler(state, "dadosProcesso"), "origem") != ORIGEM_PROCESSO_SUPORTADA:
        return {
            "statusFinal": "handoff_humano",
            "motivoHandoff": "origem_processo_nao_suportada",
            "mensagemFinal": MENSAGEM_HANDOFF_ORIGEM_NAO_SUPORTADA,
        }
    if not dados_apenado_atendidos(state):
        # Sem mensagemFinal: a rota usa a mensagemHandoff do FluxoConfig.
        return {"statusFinal": "handoff_humano", "motivoHandoff": "dados_pessoa_nao_atendidos"}
    return {"statusFinal": "concluido"}


async def nao_confirmado(state: PessoaPresaState) -> Atualizacao:
    apenado = _ler(state, "dadosApenado")
    if _js.verdadeiro(_js.opt(apenado, "falhaInfra")):
        motivo = "falha_infra_verde"
    elif _js.verdadeiro(_js.opt(apenado, "encontrado")):
        motivo = "nome_nao_confirmado"
    else:
        motivo = "rg_nao_encontrado"
    return {"statusFinal": "handoff_humano", "motivoHandoff": motivo}


def depois_de_confirmar_nome(state: PessoaPresaState) -> str:
    return "concluir" if _js.verdadeiro(_ler(state, "confirmaNome")) else "naoConfirmado"


def depois_de_parentesco(state: PessoaPresaState) -> str:
    return "identificar" if _js.verdadeiro(_ler(state, "viaOrquestrador")) else "concluir"


def depois_de_identificar_assistido(state: PessoaPresaState) -> str:
    if state.get("confirmaAssistido") is False:
        return "assistidoNaoConfirmado"
    if _js.verdadeiro(_js.opt(_ler(state, "dadosPessoa"), "falhaInfra")):
        return "falhaInfraVerde"
    return "encontrado" if _js.verdadeiro(_js.opt(_ler(state, "dadosPessoa"), "encontrado")) else "cadastrar"


def depois_de_cadastrar_pessoa(state: PessoaPresaState) -> str:
    # `cadastroErro !== undefined`: develop nunca grava undefined no canal,
    # então o undefined é a chave ausente (regra de estado, tabela 0.2).
    if "cadastroErro" in state:
        return "falhou"
    if state.get("confirmaAssistido") is False:
        return "assistidoNaoConfirmado"
    return "continuar"


async def falha_cadastro(state: PessoaPresaState) -> Atualizacao:
    erro = _ler(state, "cadastroErro")
    mensagem = f"{MENSAGEM_FALHA_CADASTRO} ({_js.texto_template(erro)})" if _js.verdadeiro(erro) else MENSAGEM_FALHA_CADASTRO
    return {"statusFinal": "handoff_humano", "motivoHandoff": "falha_cadastro", "mensagemFinal": mensagem}


async def assistido_nao_confirmado(state: PessoaPresaState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "assistido_nao_confirmado"}


async def falha_infra_assistido(state: PessoaPresaState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "falha_infra_verde"}


_construtor = StateGraph(PessoaPresaState)
_construtor.add_node("prepararPerguntaLivre", preparar_pergunta_livre)
_construtor.add_node("pedirLivre", pedir_livre)
_construtor.add_node("prepararPerguntaTemProcesso", preparar_pergunta_tem_processo)
_construtor.add_node("pedirTemProcesso", pedir_tem_processo)
_construtor.add_node("prepararPerguntaNumeroProcesso", preparar_pergunta_numero_processo)
_construtor.add_node("pedirNumeroProcesso", pedir_numero_processo)
_construtor.add_node("consultarProcesso", consultar_processo)
_construtor.add_node("prepararPerguntaRg", preparar_pergunta_rg)
_construtor.add_node("pedirRg", pedir_rg)
_construtor.add_node("prepararPerguntaRgInvalido", preparar_pergunta_rg_invalido)
_construtor.add_node("consultarApenado", consultar_apenado)
_construtor.add_node("prepararPerguntaTentarNovamente", preparar_pergunta_tentar_novamente)
_construtor.add_node("perguntaTentarNovamente", pergunta_tentar_novamente)
_construtor.add_node("prepararPerguntaConfirmaNome", preparar_pergunta_confirma_nome)
_construtor.add_node("pedirConfirmaNome", pedir_confirma_nome)
_construtor.add_node("prepararPerguntaParentesco", preparar_pergunta_parentesco)
_construtor.add_node("pedirParentesco", pedir_parentesco)
_construtor.add_node("identificarAssistido", subgrafo_identificar_assistido)
_construtor.add_node("cadastroPessoa", subgrafo_cadastro_pessoa)
_construtor.add_node("falhaCadastro", falha_cadastro)
_construtor.add_node("assistidoNaoConfirmado", assistido_nao_confirmado)
_construtor.add_node("falhaInfraAssistido", falha_infra_assistido)
_construtor.add_node("concluir", concluir)
_construtor.add_node("naoConfirmado", nao_confirmado)
_construtor.add_conditional_edges(
    START, roteamento_inicial, {"comExtracao": "prepararPerguntaLivre", "semExtracao": "prepararPerguntaTemProcesso"}
)
_construtor.add_edge("prepararPerguntaLivre", "pedirLivre")
_construtor.add_edge("pedirLivre", "prepararPerguntaTemProcesso")
_construtor.add_edge("prepararPerguntaTemProcesso", "pedirTemProcesso")
_construtor.add_conditional_edges(
    "pedirTemProcesso", depois_de_tem_processo, {"pedirNumeroProcesso": "prepararPerguntaNumeroProcesso", "pedirRg": "prepararPerguntaRg"}
)
_construtor.add_edge("prepararPerguntaNumeroProcesso", "pedirNumeroProcesso")
_construtor.add_edge("pedirNumeroProcesso", "consultarProcesso")
_construtor.add_edge("consultarProcesso", "prepararPerguntaRg")
_construtor.add_edge("prepararPerguntaRg", "pedirRg")
_construtor.add_conditional_edges("pedirRg", depois_de_pedir_rg, {"valido": "consultarApenado", "invalido": "prepararPerguntaRgInvalido"})
_construtor.add_edge("prepararPerguntaRgInvalido", "pedirRg")
_construtor.add_conditional_edges(
    "consultarApenado",
    depois_de_consultar_apenado,
    {
        "pedirConfirmaNome": "prepararPerguntaConfirmaNome",
        "perguntaTentarNovamente": "prepararPerguntaTentarNovamente",
        "naoConfirmado": "naoConfirmado",
    },
)
_construtor.add_edge("prepararPerguntaTentarNovamente", "perguntaTentarNovamente")
_construtor.add_conditional_edges(
    "perguntaTentarNovamente",
    depois_de_pergunta_tentar,
    {"pedirRg": "prepararPerguntaRg", "naoConfirmado": "naoConfirmado", "consultarApenado": "consultarApenado"},
)
_construtor.add_edge("prepararPerguntaConfirmaNome", "pedirConfirmaNome")
_construtor.add_conditional_edges(
    "pedirConfirmaNome", depois_de_confirmar_nome, {"concluir": "prepararPerguntaParentesco", "naoConfirmado": "naoConfirmado"}
)
_construtor.add_edge("prepararPerguntaParentesco", "pedirParentesco")
_construtor.add_conditional_edges("pedirParentesco", depois_de_parentesco, {"identificar": "identificarAssistido", "concluir": "concluir"})
_construtor.add_conditional_edges(
    "identificarAssistido",
    depois_de_identificar_assistido,
    {
        "encontrado": "concluir",
        "cadastrar": "cadastroPessoa",
        "assistidoNaoConfirmado": "assistidoNaoConfirmado",
        "falhaInfraVerde": "falhaInfraAssistido",
    },
)
_construtor.add_conditional_edges(
    "cadastroPessoa",
    depois_de_cadastrar_pessoa,
    {"continuar": "concluir", "falhou": "falhaCadastro", "assistidoNaoConfirmado": "assistidoNaoConfirmado"},
)
_construtor.add_edge("falhaCadastro", END)
_construtor.add_edge("assistidoNaoConfirmado", END)
_construtor.add_edge("falhaInfraAssistido", END)
_construtor.add_edge("naoConfirmado", END)
_construtor.add_edge("concluir", END)

_fabrica = FabricaGrafo(_construtor)
criar_grafo = _fabrica.criar


def obter_grafo() -> GrafoCompilado:
    return _fabrica.obter()
