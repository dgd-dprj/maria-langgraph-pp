"""Fluxo Problemas com plano de saúde (NUDECON, issue #329).

Conversa: canal ("aqui", e-mail ou presencial), "para quem", imagens dos
documentos, situação (só quando o relato não veio), renda e confirmação do resumo. Presencial encerra com a orientação;
"outra pessoa" encerra com o texto provisório e `atendimento_humano` (coleta dos
dados dela: #347). Falta o encaminhamento ao NUDECON pelo Verde (#265, #345).

Antes da primeira pergunta, o fluxo confere no Verde (`GET /cep` com `endereco.cep`)
se o município é o Rio. Fora do Rio, conclui com a unidade que o Verde indica para a
pessoa (nome, endereço e horário). Sem a unidade, e em qualquer falha da conferência,
encerra com atendimento humano: o assistido não pode ficar sem atendimento (#331).

Premissas desta etapa, a confirmar: a Tykhe coleta as imagens e avisa com
`imagensRecebidas` em `dadosConhecidos` (#336); sem o aviso, a Maria pergunta se
a pessoa já enviou. O relato chega do orquestrador no canal
`relato` (#334, ainda não entregue pela rota); sem ele, a Maria pergunta a situação.

A pergunta do canal é de texto, com as opções escritas na própria pergunta: o
tipo `opcoes` ainda está por confirmar com a Tykhe (#336).
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Awaitable, Callable, Hashable, Mapping
from typing import Any

from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.fluxos._fabrica import FabricaGrafo, GrafoCompilado
from maria.fluxos.plano_saude.api import (
    HORARIO_NUDECON,
    HORARIO_UNIDADE_PADRAO,
    ID_ASSUNTO_UNIDADE_FORA_DO_RIO,
    ID_MUNICIPIO_RIO,
    MENSAGEM_CANAL_NAO_ENTENDIDO,
    MENSAGEM_CONCLUIDO,
    MENSAGEM_DADOS_NAO_CONFIRMADOS,
    MENSAGEM_ERRO_INTERNO,
    MENSAGEM_FALHA_INFRA_VERDE,
    MENSAGEM_FORA_DO_RIO,
    MENSAGEM_FORA_DO_RIO_COM_UNIDADE,
    MENSAGEM_IMAGENS_PENDENTES,
    MENSAGEM_MUNICIPIO_NAO_IDENTIFICADO,
    MENSAGEM_OUTRA_PESSOA,
    MENSAGEM_PRESENCIAL,
    MENSAGEM_RENDA_NAO_ENTENDIDA,
    MENSAGEM_SITUACAO_NAO_INFORMADA,
)
from maria.fluxos.plano_saude.state import CanalAtendimento, MotivoHandoffPlanoSaude, PlanoSaudeState
from maria.ia.reescrever import preparar_pergunta
from maria.integracoes.verde import consultar_cep, consultar_orgaos_primeiro_atendimento, consultar_pessoa_por_cpf
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger
from maria.shared.respostas import resposta_eh_sim
from maria.shared.types import OrgaoAtendimento

MAXIMO_TENTATIVAS_CANAL = 3
MAXIMO_TENTATIVAS_IMAGENS = 3
MAXIMO_TENTATIVAS_SITUACAO = 3
MAXIMO_TENTATIVAS_RENDA = 3
PALAVRAS_MINIMAS_SITUACAO = 3
MAXIMO_TENTATIVAS_CONFIRMACAO = 3
RENDA_MAXIMA = 10_000_000

TEXTO_CANAL = f"O NUDECON atende {HORARIO_NUDECON}. Como você prefere seguir o atendimento: por aqui, por e-mail ou presencialmente?"
TEXTO_CANAL_NOVAMENTE = "Não entendi. Você prefere seguir por aqui, por e-mail ou presencialmente?"
TEXTO_PARA_QUEM = "O atendimento é para você? Responda não se for para outra pessoa."
# Lista provisória de documentos: a definitiva é da #335.
TEXTO_IMAGENS = "Envie por aqui as fotos dos documentos: a carteirinha do plano, frente e verso. Já enviou?"
TEXTO_IMAGENS_NOVAMENTE = "Ainda não recebi as imagens. Envie as fotos da carteirinha do plano, frente e verso. Já enviou?"
TEXTO_SITUACAO = "Conte em poucas palavras o que aconteceu com o seu plano de saúde."
TEXTO_SITUACAO_NOVAMENTE = "Preciso de um pouco mais de detalhe. O que o plano de saúde negou ou deixou de fazer?"
TEXTO_RENDA = "Qual é a sua renda mensal, em reais? Se não tem renda, responda 0."
TEXTO_RENDA_NOVAMENTE = (
    "Não entendi o valor. Informe a sua renda mensal em reais, só o número (por exemplo, 2500). Se não tem renda, responda 0."
)
TEXTO_RENDA_CORRIGIR = "Vamos corrigir. Qual é a sua renda mensal, em reais?"
TEXTO_CONFIRMACAO = "Confira os dados do atendimento. Está tudo certo?"
NAO_INFORMADO = "não informado"

Atualizacao = dict[str, Any]


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


async def verificar_municipio(state: PlanoSaudeState) -> Atualizacao:
    """Só o Rio segue para a conversa. Fora do Rio, sem CEP, CEP que o Verde não resolve
    e falha do Verde encerram com atendimento humano, cada um com o seu motivo."""
    cep = _texto((state.get("endereco") or {}).get("cep"))
    if not cep:
        return _encerrar_por_municipio("municipio_nao_identificado", MENSAGEM_MUNICIPIO_NAO_IDENTIFICADO)
    dados = await consultar_cep(cep)
    if dados.get("falhaInfra"):
        return _encerrar_por_municipio("falha_infra_verde", MENSAGEM_FALHA_INFRA_VERDE)
    id_municipio = dados.get("idMunicipio") if dados.get("encontrado") else None
    if id_municipio is None:
        return _encerrar_por_municipio("municipio_nao_identificado", MENSAGEM_MUNICIPIO_NAO_IDENTIFICADO)
    if id_municipio != ID_MUNICIPIO_RIO:
        unidade = await _unidade_fora_do_rio(state)
        if unidade:
            return {
                "statusFinal": "concluido",
                "foraDoRio": True,
                "mensagemFinal": MENSAGEM_FORA_DO_RIO_COM_UNIDADE.format(unidade=unidade),
            }
        return _encerrar_por_municipio("fora_do_rio", MENSAGEM_FORA_DO_RIO)
    return {}


async def _unidade_fora_do_rio(state: PlanoSaudeState) -> str:
    """A unidade que o Verde habilita para a pessoa (pelo endereço cadastrado dela), ou vazio quando não dá para
    saber: sem CPF, pessoa fora do Verde, falha do Verde ou lista sem endereço. Aí o atendimento vai ao humano."""
    cpf = _texto(state.get("cpf"))
    if not cpf:
        return ""
    pessoa = await consultar_pessoa_por_cpf(cpf)
    id_pessoa = pessoa.get("idPessoa")
    if not pessoa.get("encontrado") or not isinstance(id_pessoa, int) or id_pessoa <= 0:
        return ""
    orgaos = await consultar_orgaos_primeiro_atendimento(id_pessoa, ID_ASSUNTO_UNIDADE_FORA_DO_RIO)
    return next((texto for orgao in orgaos["orgaos"] if (texto := _descrever_unidade(orgao))), "")


def _descrever_unidade(orgao: OrgaoAtendimento) -> str:
    """ "Nome, Rua X, 35 13º andar, Bairro, Município/UF. Horário: ..."; vazio quando o órgão não traz endereço.
    Sem horário no Verde, vale o padrão provisório."""
    enderecos = orgao.get("enderecos") or []
    endereco = enderecos[0] if enderecos else {}
    logradouro = _texto(endereco.get("logradouro"))
    if not logradouro:
        return ""
    numero = " ".join(p for p in (_texto(endereco.get("numero")), _texto(endereco.get("complemento"))) if p)
    cidade = "/".join(p for p in (_texto(endereco.get("municipio")), _texto(endereco.get("uf"))) if p)
    local = ", ".join(p for p in (f"{logradouro}, {numero}" if numero else logradouro, _texto(endereco.get("bairro")), cidade) if p)
    horario = (
        _texto(endereco.get("horariosUrgenciaFormatado")) or _texto(endereco.get("horariosAtendimentoFormatado")) or HORARIO_UNIDADE_PADRAO
    )
    return f"{_texto(orgao.get('nome'))}, {local}. Horário: {horario}"


def _encerrar_por_municipio(motivo: MotivoHandoffPlanoSaude, mensagem: str) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": motivo, "mensagemFinal": mensagem}


def depois_do_municipio(state: PlanoSaudeState) -> str:
    return "encerrar" if state.get("statusFinal") else "canal"


def interpretar_canal(resposta: str) -> CanalAtendimento | None:
    """O canal escolhido na resposta livre, ou `None` quando não dá para saber.
    Mais de um canal citado também é `None`: a pessoa precisa escolher um."""
    texto = _sem_acento(resposta)
    achados: set[CanalAtendimento] = set()
    if re.search(r"presenc|pessoalmente|ir ate|na sede|no local", texto):
        achados.add("presencial")
    if re.search(r"e-?mail|correio eletronico", texto):
        achados.add("email")
    if re.search(r"\baqui\b|whats|zap|mensagem|conversa|chat", texto):
        achados.add("aqui")
    return next(iter(achados)) if len(achados) == 1 else None


def texto_canal(state: PlanoSaudeState) -> str:
    return TEXTO_CANAL if not state.get("tentativasCanal") else TEXTO_CANAL_NOVAMENTE


async def preparar_pergunta_canal(state: PlanoSaudeState) -> Atualizacao:
    return dict(await preparar_pergunta("canal", texto_canal(state)))


async def pedir_canal(state: PlanoSaudeState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": state.get("perguntaAtualTexto") or texto_canal(state), "tipo": "texto"})
    canal = interpretar_canal(resposta)
    if canal is not None:
        return {"canal": canal}
    return {"canal": None, "tentativasCanal": (state.get("tentativasCanal") or 0) + 1}


def depois_do_canal(state: PlanoSaudeState) -> str:
    canal = state.get("canal")
    if canal == "presencial":
        return "presencial"
    if canal is not None:
        return "paraQuem"
    if (state.get("tentativasCanal") or 0) >= MAXIMO_TENTATIVAS_CANAL:
        return "canalNaoEntendido"
    return "canal"


async def presencial(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "concluido", "mensagemFinal": MENSAGEM_PRESENCIAL}


async def canal_nao_entendido(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "canal_nao_entendido", "mensagemFinal": MENSAGEM_CANAL_NAO_ENTENDIDO}


async def preparar_pergunta_para_quem(state: PlanoSaudeState) -> Atualizacao:
    return dict(await preparar_pergunta("paraSi", TEXTO_PARA_QUEM))


async def pedir_para_quem(state: PlanoSaudeState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": state.get("perguntaAtualTexto") or TEXTO_PARA_QUEM, "tipo": "sim_nao", "opcoes": ["Sim", "Não"]})
    return {"paraSi": resposta_eh_sim(resposta)}


def depois_de_para_quem(state: PlanoSaudeState) -> str:
    if not state.get("paraSi"):
        return "outraPessoa"
    return "imagens" if state.get("imagensRecebidas") is not True else _depois_das_imagens_enviadas(state)


def _depois_das_imagens_enviadas(state: PlanoSaudeState) -> str:
    """Sem relato (atendimento criado direto, sem orquestrador), a Maria pergunta a situação."""
    return "renda" if _texto(state.get("relato")) else "situacao"


def texto_imagens(state: PlanoSaudeState) -> str:
    return TEXTO_IMAGENS if not state.get("tentativasImagens") else TEXTO_IMAGENS_NOVAMENTE


async def preparar_pergunta_imagens(state: PlanoSaudeState) -> Atualizacao:
    return dict(await preparar_pergunta("imagens", texto_imagens(state)))


async def pedir_imagens(state: PlanoSaudeState) -> Atualizacao:
    resposta: str = interrupt(
        {"pergunta": state.get("perguntaAtualTexto") or texto_imagens(state), "tipo": "sim_nao", "opcoes": ["Sim", "Não"]}
    )
    if resposta_eh_sim(resposta):
        return {"imagensRecebidas": True}
    return {"tentativasImagens": (state.get("tentativasImagens") or 0) + 1}


def depois_das_imagens(state: PlanoSaudeState) -> str:
    if state.get("imagensRecebidas") is True:
        return _depois_das_imagens_enviadas(state)
    return "imagensPendentes" if (state.get("tentativasImagens") or 0) >= MAXIMO_TENTATIVAS_IMAGENS else "imagens"


async def imagens_pendentes(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "imagens_pendentes", "mensagemFinal": MENSAGEM_IMAGENS_PENDENTES}


def texto_situacao(state: PlanoSaudeState) -> str:
    return TEXTO_SITUACAO if not state.get("tentativasSituacao") else TEXTO_SITUACAO_NOVAMENTE


async def preparar_pergunta_situacao(state: PlanoSaudeState) -> Atualizacao:
    return dict(await preparar_pergunta("situacao", texto_situacao(state)))


async def pedir_situacao(state: PlanoSaudeState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": state.get("perguntaAtualTexto") or texto_situacao(state), "tipo": "texto"})
    relato = resposta.strip()
    if len(relato.split()) >= PALAVRAS_MINIMAS_SITUACAO:
        return {"relato": relato}
    return {"tentativasSituacao": (state.get("tentativasSituacao") or 0) + 1}


def depois_da_situacao(state: PlanoSaudeState) -> str:
    if _texto(state.get("relato")):
        return "renda"
    return "situacaoNaoInformada" if (state.get("tentativasSituacao") or 0) >= MAXIMO_TENTATIVAS_SITUACAO else "situacao"


async def situacao_nao_informada(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "situacao_nao_informada", "mensagemFinal": MENSAGEM_SITUACAO_NAO_INFORMADA}


def interpretar_renda(resposta: str) -> float | None:
    """A renda mensal em reais, ou `None` quando não dá para saber (sem número,
    negativa ou absurda). "Não tenho renda" vale 0: é uma resposta possível e
    quem não tem renda é justamente quem o NUDECON atende."""
    texto = _sem_acento(resposta).strip()
    if re.search(r"\b(sem renda|nao tenho renda|nenhuma|nenhum|zero)\b", texto):
        return 0.0
    achado = re.search(r"(-)?\s*(\d[\d.,]*)(\s*mil\b)?", texto)
    if achado is None or achado.group(1):
        return None
    numero = achado.group(2).rstrip(".,")
    if "," in numero:
        numero = numero.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", numero):
        numero = numero.replace(".", "")
    try:
        valor = float(numero)
    except ValueError:
        return None
    if achado.group(3):
        valor *= 1000
    return valor if 0 <= valor <= RENDA_MAXIMA else None


def texto_renda(state: PlanoSaudeState) -> str:
    if state.get("tentativasRenda"):
        return TEXTO_RENDA_NOVAMENTE
    return TEXTO_RENDA_CORRIGIR if state.get("tentativasConfirmacao") else TEXTO_RENDA


async def preparar_pergunta_renda(state: PlanoSaudeState) -> Atualizacao:
    return dict(await preparar_pergunta("renda", texto_renda(state)))


async def pedir_renda(state: PlanoSaudeState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": state.get("perguntaAtualTexto") or texto_renda(state), "tipo": "texto"})
    renda = interpretar_renda(resposta)
    if renda is not None:
        return {"renda": renda, "tentativasRenda": 0}
    return {"renda": None, "tentativasRenda": (state.get("tentativasRenda") or 0) + 1}


def depois_da_renda(state: PlanoSaudeState) -> str:
    if state.get("renda") is not None:
        return "confirmacao"
    return "rendaNaoEntendida" if (state.get("tentativasRenda") or 0) >= MAXIMO_TENTATIVAS_RENDA else "renda"


async def renda_nao_entendida(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "renda_nao_entendida", "mensagemFinal": MENSAGEM_RENDA_NAO_ENTENDIDA}


def _texto(valor: object) -> str:
    """Vazio e ausente valem o mesmo; o CPF pode chegar como número (#296)."""
    if valor is None or isinstance(valor, bool):
        return ""
    return str(valor).strip()


def _endereco(endereco: object) -> str:
    if not isinstance(endereco, dict):
        return _texto(endereco)
    cidade = "/".join(p for p in (_texto(endereco.get("municipio")), _texto(endereco.get("uf"))) if p)
    cep = _texto(endereco.get("cep"))
    partes = [
        _texto(endereco.get("logradouro")),
        _texto(endereco.get("numero")),
        _texto(endereco.get("complemento")),
        _texto(endereco.get("bairro")),
        cidade,
        f"CEP {cep}" if cep else "",
    ]
    return ", ".join(p for p in partes if p)


def _reais(valor: float) -> str:
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def montar_resumo(state: PlanoSaudeState) -> str:
    """Os dados da Tykhe como vieram, mais a renda. Dado ausente aparece como "não informado"."""
    renda = state.get("renda")
    linhas = [
        ("Nome", _texto(state.get("nome"))),
        ("CPF", _texto(state.get("cpf"))),
        ("Data de nascimento", _texto(state.get("dataNascimento"))),
        ("E-mail", _texto(state.get("email"))),
        ("Telefone", _texto(state.get("telefone"))),
        ("Endereço", _endereco(state.get("endereco"))),
        ("Situação", _texto(state.get("relato"))),
        ("Renda mensal", _reais(renda) if renda is not None else ""),
    ]
    return "\n".join(f"{rotulo}: {valor or NAO_INFORMADO}" for rotulo, valor in linhas)


async def preparar_pergunta_confirmacao(state: PlanoSaudeState) -> Atualizacao:
    # Só a pergunta passa pela IA: o resumo tem CPF, nome e endereço e é colado depois (LGPD).
    return dict(await preparar_pergunta("confirmacao", TEXTO_CONFIRMACAO))


async def pedir_confirmacao(state: PlanoSaudeState) -> Atualizacao:
    pergunta_texto = f"{state.get('perguntaAtualTexto') or TEXTO_CONFIRMACAO}\n\n{montar_resumo(state)}"
    resposta: str = interrupt({"pergunta": pergunta_texto, "tipo": "sim_nao", "opcoes": ["Sim", "Não"]})
    if resposta_eh_sim(resposta):
        return {"confirmado": True}
    return {"confirmado": False, "tentativasConfirmacao": (state.get("tentativasConfirmacao") or 0) + 1}


def depois_da_confirmacao(state: PlanoSaudeState) -> str:
    if state.get("confirmado"):
        return "concluir"
    # A correção por campo fica para outra issue (#329); por ora só a renda se refaz.
    return "naoConfirmado" if (state.get("tentativasConfirmacao") or 0) >= MAXIMO_TENTATIVAS_CONFIRMACAO else "renda"


async def nao_confirmado(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "dados_nao_confirmados", "mensagemFinal": MENSAGEM_DADOS_NAO_CONFIRMADOS}


async def outra_pessoa(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "outra_pessoa", "mensagemFinal": MENSAGEM_OUTRA_PESSOA}


async def concluir(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "concluido", "mensagemFinal": MENSAGEM_CONCLUIDO}


def _deu_erro(state: PlanoSaudeState) -> bool:
    return state.get("motivoHandoff") == "erro_interno"


def _protegido(no: Callable[[PlanoSaudeState], Awaitable[Atualizacao]]) -> Callable[..., Any]:
    """Falha inesperada em qualquer nó encerra com atendimento humano, e não com 500: o assistido não pode
    ficar sem atendimento. O interrupt do LangGraph passa (é um GraphBubbleUp). O log leva só o nome do nó
    e o tipo do erro, nunca a mensagem, que pode carregar dado da pessoa."""

    @functools.wraps(no)
    async def com_guarda(state: PlanoSaudeState) -> Atualizacao:
        try:
            return await no(state)
        except GraphBubbleUp:
            raise
        except Exception as erro:
            logger.error(
                "[plano-saude] falha inesperada no fluxo: encerra com atendimento humano",
                **contexto_atual(),
                no=no.__name__,
                tipoErro=type(erro).__name__,
            )
            return {"statusFinal": "handoff_humano", "motivoHandoff": "erro_interno", "mensagemFinal": MENSAGEM_ERRO_INTERNO}

    return com_guarda


def _seguir(origem: str, destino: str) -> None:
    """Aresta fixa que, depois de uma falha, vai ao fim em vez de seguir para o próximo nó."""
    _condicional(origem, lambda state: "seguir", {"seguir": destino})


def _condicional(origem: str, roteador: Callable[[PlanoSaudeState], str], destinos: Mapping[str, str]) -> None:
    def roteador_com_guarda(state: PlanoSaudeState) -> str:
        return "erroInterno" if _deu_erro(state) else roteador(state)

    caminhos: dict[Hashable, str] = {chave: destino for chave, destino in destinos.items()}
    caminhos["erroInterno"] = END
    _construtor.add_conditional_edges(origem, roteador_com_guarda, caminhos)


_construtor = StateGraph(PlanoSaudeState)
_construtor.add_node("verificarMunicipio", _protegido(verificar_municipio))
_construtor.add_node("prepararPerguntaCanal", _protegido(preparar_pergunta_canal))
_construtor.add_node("pedirCanal", _protegido(pedir_canal))
_construtor.add_node("presencial", _protegido(presencial))
_construtor.add_node("canalNaoEntendido", _protegido(canal_nao_entendido))
_construtor.add_node("prepararPerguntaParaQuem", _protegido(preparar_pergunta_para_quem))
_construtor.add_node("pedirParaQuem", _protegido(pedir_para_quem))
_construtor.add_node("outraPessoa", _protegido(outra_pessoa))
_construtor.add_node("prepararPerguntaImagens", _protegido(preparar_pergunta_imagens))
_construtor.add_node("pedirImagens", _protegido(pedir_imagens))
_construtor.add_node("imagensPendentes", _protegido(imagens_pendentes))
_construtor.add_node("prepararPerguntaSituacao", _protegido(preparar_pergunta_situacao))
_construtor.add_node("pedirSituacao", _protegido(pedir_situacao))
_construtor.add_node("situacaoNaoInformada", _protegido(situacao_nao_informada))
_construtor.add_node("prepararPerguntaRenda", _protegido(preparar_pergunta_renda))
_construtor.add_node("pedirRenda", _protegido(pedir_renda))
_construtor.add_node("rendaNaoEntendida", _protegido(renda_nao_entendida))
_construtor.add_node("prepararPerguntaConfirmacao", _protegido(preparar_pergunta_confirmacao))
_construtor.add_node("pedirConfirmacao", _protegido(pedir_confirmacao))
_construtor.add_node("naoConfirmado", _protegido(nao_confirmado))
_construtor.add_node("concluir", _protegido(concluir))
_construtor.add_edge(START, "verificarMunicipio")
_condicional("verificarMunicipio", depois_do_municipio, {"canal": "prepararPerguntaCanal", "encerrar": END})
_seguir("prepararPerguntaCanal", "pedirCanal")
_condicional(
    "pedirCanal",
    depois_do_canal,
    {
        "presencial": "presencial",
        "paraQuem": "prepararPerguntaParaQuem",
        "canalNaoEntendido": "canalNaoEntendido",
        "canal": "prepararPerguntaCanal",
    },
)
_seguir("prepararPerguntaParaQuem", "pedirParaQuem")
_condicional(
    "pedirParaQuem",
    depois_de_para_quem,
    {
        "imagens": "prepararPerguntaImagens",
        "situacao": "prepararPerguntaSituacao",
        "renda": "prepararPerguntaRenda",
        "outraPessoa": "outraPessoa",
    },
)
_seguir("prepararPerguntaImagens", "pedirImagens")
_condicional(
    "pedirImagens",
    depois_das_imagens,
    {
        "situacao": "prepararPerguntaSituacao",
        "renda": "prepararPerguntaRenda",
        "imagens": "prepararPerguntaImagens",
        "imagensPendentes": "imagensPendentes",
    },
)
_seguir("prepararPerguntaSituacao", "pedirSituacao")
_condicional(
    "pedirSituacao",
    depois_da_situacao,
    {"renda": "prepararPerguntaRenda", "situacao": "prepararPerguntaSituacao", "situacaoNaoInformada": "situacaoNaoInformada"},
)
_seguir("prepararPerguntaRenda", "pedirRenda")
_condicional(
    "pedirRenda",
    depois_da_renda,
    {"confirmacao": "prepararPerguntaConfirmacao", "renda": "prepararPerguntaRenda", "rendaNaoEntendida": "rendaNaoEntendida"},
)
_seguir("prepararPerguntaConfirmacao", "pedirConfirmacao")
_condicional(
    "pedirConfirmacao",
    depois_da_confirmacao,
    {"concluir": "concluir", "renda": "prepararPerguntaRenda", "naoConfirmado": "naoConfirmado"},
)
for _fim in (
    "presencial",
    "canalNaoEntendido",
    "outraPessoa",
    "imagensPendentes",
    "situacaoNaoInformada",
    "rendaNaoEntendida",
    "naoConfirmado",
    "concluir",
):
    _construtor.add_edge(_fim, END)

_fabrica = FabricaGrafo(_construtor)
criar_grafo = _fabrica.criar


def obter_grafo() -> GrafoCompilado:
    return _fabrica.obter()
