"""Fluxo Problemas com plano de saúde (NUDECON, issue #329).

Conversa: canal ("aqui", e-mail ou presencial), "para quem", imagens dos
documentos, renda, resumo e confirmação. Presencial encerra com a orientação;
"outra pessoa" encerra com o texto provisório e `atendimento_humano` (coleta dos
dados dela: #347). Quem confirma o resumo é encaminhado ao NUDECON; os dados
preenchidos saem em `metadados` e em `dadosColetados`, e a Tykhe envia o e-mail
(#345).

As imagens ficam com a Tykhe, que avisa pelo campo `imagensRecebidas` de
`dadosConhecidos` (formato a confirmar na #336). Sem o aviso, a Maria pergunta se
a pessoa já enviou. A Maria não consulta o Verde neste fluxo.

As perguntas de canal e de imagens são de texto ou sim/não escritas na própria
pergunta: o tipo `opcoes` ainda está por confirmar com a Tykhe (#336).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.fluxos._fabrica import FabricaGrafo, GrafoCompilado
from maria.fluxos.plano_saude.api import (
    HORARIO_NUDECON,
    MENSAGEM_CANAL_NAO_ENTENDIDO,
    MENSAGEM_CONCLUIDO,
    MENSAGEM_DADOS_NAO_CONFIRMADOS,
    MENSAGEM_IMAGENS_PENDENTES,
    MENSAGEM_OUTRA_PESSOA,
    MENSAGEM_PRESENCIAL,
    MENSAGEM_RENDA_NAO_INFORMADA,
)
from maria.fluxos.plano_saude.state import CanalAtendimento, PlanoSaudeState
from maria.ia.reescrever import preparar_pergunta
from maria.shared.respostas import resposta_eh_sim

MAXIMO_TENTATIVAS_CANAL = 3
MAXIMO_TENTATIVAS_IMAGENS = 3
MAXIMO_TENTATIVAS_RENDA = 3

TEXTO_CANAL = f"O NUDECON atende {HORARIO_NUDECON}. Como você prefere seguir o atendimento: por aqui, por e-mail ou presencialmente?"
TEXTO_CANAL_NOVAMENTE = "Não entendi. Você prefere seguir por aqui, por e-mail ou presencialmente?"
TEXTO_PARA_QUEM = "O atendimento é para você? Responda não se for para outra pessoa."
TEXTO_IMAGENS = (
    "Para analisar o seu caso, preciso das fotos dos documentos: carteirinha do plano de saúde (frente e verso), "
    "laudo médico e demais comprovantes. Você já enviou? Responda não se ainda faltar enviar."
)
TEXTO_IMAGENS_NOVAMENTE = "Ainda não recebi as fotos. Envie os documentos e responda sim quando terminar. Você já enviou?"
TEXTO_RENDA = "Qual é a sua renda mensal? Pode informar um valor aproximado."
TEXTO_RENDA_NOVAMENTE = "Não entendi. Qual é a sua renda mensal? Pode informar um valor aproximado."
# A pergunta passa pela IA de reescrita (quando ligada) e o resumo vem depois dela, para a IA nunca mexer nos dados.
TEXTO_CONFIRMACAO = "Confira os dados abaixo. Está tudo certo? Responda não se algo precisar de correção."

NAO_INFORMADO = "não informado"

Atualizacao = dict[str, Any]


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


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


def _texto_ou_nao_informado(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) and valor.strip() else NAO_INFORMADO


def _data_br(valor: Any) -> str:
    """AAAA-MM-DD vira DD/MM/AAAA; qualquer outro formato aparece como veio."""
    texto = _texto_ou_nao_informado(valor)
    partes = texto.split("-")
    if len(partes) == 3 and len(partes[0]) == 4 and all(p.isdigit() for p in partes):
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return texto


def _endereco(valor: Any) -> str:
    if isinstance(valor, str):
        return _texto_ou_nao_informado(valor)
    if not isinstance(valor, dict):
        return NAO_INFORMADO
    rua = ", ".join(p for p in (str(valor.get("logradouro") or "").strip(), str(valor.get("numero") or "").strip()) if p)
    complemento = str(valor.get("complemento") or "").strip()
    cidade = "/".join(p for p in (str(valor.get("municipio") or "").strip(), str(valor.get("uf") or "").strip()) if p)
    cep = str(valor.get("cep") or "").strip()
    partes = [rua, complemento, str(valor.get("bairro") or "").strip(), cidade, f"CEP {cep}" if cep else ""]
    return ", ".join(p for p in partes if p) or NAO_INFORMADO


def montar_resumo(state: PlanoSaudeState) -> str:
    """Os dados como vieram da Tykhe e da conversa; o que falta aparece como "não informado"."""
    linhas = [
        f"Nome: {_texto_ou_nao_informado(state.get('nome'))}",
        f"CPF: {_texto_ou_nao_informado(state.get('cpf'))}",
        f"Data de nascimento: {_data_br(state.get('dataNascimento'))}",
        f"E-mail: {_texto_ou_nao_informado(state.get('email'))}",
        f"Telefone: {_texto_ou_nao_informado(state.get('telefone'))}",
        f"Endereço: {_endereco(state.get('endereco'))}",
    ]
    situacao = state.get("situacao")
    if isinstance(situacao, str) and situacao.strip():
        linhas.append(f"Situação: {situacao.strip()}")
    linhas.append(f"Renda mensal: {_texto_ou_nao_informado(state.get('renda'))}")
    return "\n".join(linhas)


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
    # A Tykhe já avisou que guardou as imagens: não pergunta de novo.
    return "renda" if state.get("imagensRecebidas") is True else "imagens"


async def outra_pessoa(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "outra_pessoa", "mensagemFinal": MENSAGEM_OUTRA_PESSOA}


def texto_imagens(state: PlanoSaudeState) -> str:
    return TEXTO_IMAGENS if not state.get("tentativasImagens") else TEXTO_IMAGENS_NOVAMENTE


async def preparar_pergunta_imagens(state: PlanoSaudeState) -> Atualizacao:
    return dict(await preparar_pergunta("imagensRecebidas", texto_imagens(state)))


async def pedir_imagens(state: PlanoSaudeState) -> Atualizacao:
    resposta: str = interrupt(
        {"pergunta": state.get("perguntaAtualTexto") or texto_imagens(state), "tipo": "sim_nao", "opcoes": ["Sim", "Não"]}
    )
    if resposta_eh_sim(resposta):
        return {"imagensRecebidas": True}
    return {"imagensRecebidas": False, "tentativasImagens": (state.get("tentativasImagens") or 0) + 1}


def depois_das_imagens(state: PlanoSaudeState) -> str:
    if state.get("imagensRecebidas") is True:
        return "renda"
    if (state.get("tentativasImagens") or 0) >= MAXIMO_TENTATIVAS_IMAGENS:
        return "imagensPendentes"
    return "imagens"


async def imagens_pendentes(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "imagens_pendentes", "mensagemFinal": MENSAGEM_IMAGENS_PENDENTES}


def texto_renda(state: PlanoSaudeState) -> str:
    return TEXTO_RENDA if not state.get("tentativasRenda") else TEXTO_RENDA_NOVAMENTE


async def preparar_pergunta_renda(state: PlanoSaudeState) -> Atualizacao:
    return dict(await preparar_pergunta("renda", texto_renda(state)))


async def pedir_renda(state: PlanoSaudeState) -> Atualizacao:
    resposta: str = interrupt({"pergunta": state.get("perguntaAtualTexto") or texto_renda(state), "tipo": "texto"})
    renda = str(resposta).strip()
    if renda:
        return {"renda": renda}
    return {"renda": None, "tentativasRenda": (state.get("tentativasRenda") or 0) + 1}


def depois_da_renda(state: PlanoSaudeState) -> str:
    if state.get("renda"):
        return "confirmacao"
    if (state.get("tentativasRenda") or 0) >= MAXIMO_TENTATIVAS_RENDA:
        return "rendaNaoInformada"
    return "renda"


async def renda_nao_informada(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "renda_nao_informada", "mensagemFinal": MENSAGEM_RENDA_NAO_INFORMADA}


async def preparar_pergunta_confirmacao(state: PlanoSaudeState) -> Atualizacao:
    preparada = dict(await preparar_pergunta("confirmacao", TEXTO_CONFIRMACAO))
    # A IA só reescreve a pergunta; o resumo entra depois, sem passar por ela.
    preparada["perguntaAtualTexto"] = f"{preparada['perguntaAtualTexto']}\n\n{montar_resumo(state)}"
    return preparada


async def pedir_confirmacao(state: PlanoSaudeState) -> Atualizacao:
    pergunta = state.get("perguntaAtualTexto") or f"{TEXTO_CONFIRMACAO}\n\n{montar_resumo(state)}"
    resposta: str = interrupt({"pergunta": pergunta, "tipo": "sim_nao", "opcoes": ["Sim", "Não"]})
    return {"confirmou": resposta_eh_sim(resposta)}


def depois_da_confirmacao(state: PlanoSaudeState) -> str:
    return "encaminhar" if state.get("confirmou") else "dadosNaoConfirmados"


async def dados_nao_confirmados(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "handoff_humano", "motivoHandoff": "dados_nao_confirmados", "mensagemFinal": MENSAGEM_DADOS_NAO_CONFIRMADOS}


async def encaminhar(state: PlanoSaudeState) -> Atualizacao:
    return {"statusFinal": "concluido", "mensagemFinal": MENSAGEM_CONCLUIDO}


_construtor = StateGraph(PlanoSaudeState)
_construtor.add_node("prepararPerguntaCanal", preparar_pergunta_canal)
_construtor.add_node("pedirCanal", pedir_canal)
_construtor.add_node("presencial", presencial)
_construtor.add_node("canalNaoEntendido", canal_nao_entendido)
_construtor.add_node("prepararPerguntaParaQuem", preparar_pergunta_para_quem)
_construtor.add_node("pedirParaQuem", pedir_para_quem)
_construtor.add_node("outraPessoa", outra_pessoa)
_construtor.add_node("prepararPerguntaImagens", preparar_pergunta_imagens)
_construtor.add_node("pedirImagens", pedir_imagens)
_construtor.add_node("imagensPendentes", imagens_pendentes)
_construtor.add_node("prepararPerguntaRenda", preparar_pergunta_renda)
_construtor.add_node("pedirRenda", pedir_renda)
_construtor.add_node("rendaNaoInformada", renda_nao_informada)
_construtor.add_node("prepararPerguntaConfirmacao", preparar_pergunta_confirmacao)
_construtor.add_node("pedirConfirmacao", pedir_confirmacao)
_construtor.add_node("dadosNaoConfirmados", dados_nao_confirmados)
_construtor.add_node("encaminhar", encaminhar)
_construtor.add_edge(START, "prepararPerguntaCanal")
_construtor.add_edge("prepararPerguntaCanal", "pedirCanal")
_construtor.add_conditional_edges(
    "pedirCanal",
    depois_do_canal,
    {
        "presencial": "presencial",
        "paraQuem": "prepararPerguntaParaQuem",
        "canalNaoEntendido": "canalNaoEntendido",
        "canal": "prepararPerguntaCanal",
    },
)
_construtor.add_edge("prepararPerguntaParaQuem", "pedirParaQuem")
_construtor.add_conditional_edges(
    "pedirParaQuem",
    depois_de_para_quem,
    {"outraPessoa": "outraPessoa", "imagens": "prepararPerguntaImagens", "renda": "prepararPerguntaRenda"},
)
_construtor.add_edge("prepararPerguntaImagens", "pedirImagens")
_construtor.add_conditional_edges(
    "pedirImagens",
    depois_das_imagens,
    {"renda": "prepararPerguntaRenda", "imagensPendentes": "imagensPendentes", "imagens": "prepararPerguntaImagens"},
)
_construtor.add_edge("prepararPerguntaRenda", "pedirRenda")
_construtor.add_conditional_edges(
    "pedirRenda",
    depois_da_renda,
    {"confirmacao": "prepararPerguntaConfirmacao", "rendaNaoInformada": "rendaNaoInformada", "renda": "prepararPerguntaRenda"},
)
_construtor.add_edge("prepararPerguntaConfirmacao", "pedirConfirmacao")
_construtor.add_conditional_edges(
    "pedirConfirmacao", depois_da_confirmacao, {"encaminhar": "encaminhar", "dadosNaoConfirmados": "dadosNaoConfirmados"}
)
for _fim in (
    "presencial",
    "canalNaoEntendido",
    "outraPessoa",
    "imagensPendentes",
    "rendaNaoInformada",
    "dadosNaoConfirmados",
    "encaminhar",
):
    _construtor.add_edge(_fim, END)

_fabrica = FabricaGrafo(_construtor)
criar_grafo = _fabrica.criar


def obter_grafo() -> GrafoCompilado:
    return _fabrica.obter()
