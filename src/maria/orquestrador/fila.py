"""Fila de assuntos do multi-fluxo (#435, fase 1a da #279): a ordem, os textos e a leitura da resposta.

Sem IA: a ordem e os textos são fixos, no padrão de linguagem acessível combinado com a Nicole
(28 e 29/10): frases curtas, nomes curtos e sempre os mesmos, pergunta de Sim ou Não.

Fase 1a: a Maria atende o primeiro assunto da fila. Os outros voltam à Tykhe em `assuntosPendentes`.
Por isso os textos não prometem "tudo aqui mesmo", como o protótipo fazia.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, NotRequired, TypedDict

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA
from maria.fluxos.tipos_tykhe import tipo_tykhe_por_id
from maria.ia.classificar_necessidades import FORA_DA_LISTA, Necessidade
from maria.shared.parentesco import atendimento_para_si, fala_como_vitima, quem_esta_preso
from maria.shared.pendentes_db import SUFIXO_ASSUNTO, chat_id_do_assunto
from maria.shared.respostas import normalizar_resposta, resposta_eh_nao, resposta_eh_sim

__all__ = ["SUFIXO_ASSUNTO", "chat_id_do_assunto"]

ID_OUTROS = "tykhe:outros"
ID_SAIR = "tykhe:sair"
ID_SAUDE = "tykhe:saude"

# Nomes curtos, iguais em todas as mensagens. A violência doméstica tem nome discreto, porque a
# mensagem pode ser lida por outra pessoa no celular (decisão da Nicole, 28/10).
NOME_SIMPLES: dict[str, str] = {
    ID_PESSOA_PRESA: "a pessoa presa",
    ID_VIOLENCIA_DOMESTICA: "a situação que você contou",
    ID_PROBLEMAS_PLANO_SAUDE: "o plano de saúde",
    ID_SAUDE: "a saúde",
    "tykhe:novo-processo": "o caso novo",
    "tykhe:andamento-processo": "o seu processo",
    "tykhe:agendamentos": "o seu horário marcado",
    "tykhe:ajuda-app": "o aplicativo",
    ID_OUTROS: "o outro assunto",
}

# Ordem padrão, com ou sem urgência. Decisão da Nicole (2026-11-13), invertendo a de 28 e 29/10 (saúde primeiro):
# a violência doméstica primeiro, depois a pessoa presa, depois a saúde e o plano de saúde; depois o resto, o
# urgente antes, o que a Maria conduz em seguida e o que é da Tykhe por último.
PRIORIDADE: dict[str, int] = {ID_VIOLENCIA_DOMESTICA: 0, ID_PESSOA_PRESA: 1, ID_SAUDE: 2, ID_PROBLEMAS_PLANO_SAUDE: 2}
CONDUZIDOS_PELA_MARIA = frozenset({ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, ID_PROBLEMAS_PLANO_SAUDE})

# #450 (decisão da Nicole, 2026-11-10): o parâmetro de urgência de cada assunto, que vai para a Tykhe em
# `assuntosPendentes[].urgencia` e muda as mensagens ao assistido. A tabela dá o padrão de cada assunto; o sinal de
# risco do relato (o `urgente` da classificação) sobe qualquer assunto para urgente. Assunto fora da tabela é
# menos urgente. Os urgentes são os mesmos que a ordem padrão põe na frente (`PRIORIDADE`).
Urgencia = Literal["urgente", "menos_urgente"]
URGENCIAS: tuple[Urgencia, ...] = ("urgente", "menos_urgente")
URGENCIA_DO_ASSUNTO: dict[str, Urgencia] = {
    ID_SAUDE: "urgente",
    ID_PROBLEMAS_PLANO_SAUDE: "urgente",
    ID_VIOLENCIA_DOMESTICA: "urgente",
    ID_PESSOA_PRESA: "urgente",
    "tykhe:novo-processo": "menos_urgente",
    "tykhe:andamento-processo": "menos_urgente",
    "tykhe:agendamentos": "menos_urgente",
    "tykhe:ajuda-app": "menos_urgente",
    ID_OUTROS: "menos_urgente",
}


def urgencia_do_assunto(id_assunto: str, sinal_de_risco: bool) -> Urgencia:
    if sinal_de_risco:
        return "urgente"
    return URGENCIA_DO_ASSUNTO.get(id_assunto, "menos_urgente")


# Palavras que ajudam a achar o assunto quando a pessoa responde com o nome dele ("a do meu filho",
# "o plano", "a da cadeia"). Além delas, vale qualquer palavra do trecho do relato.
PALAVRAS_DO_ASSUNTO: dict[str, frozenset[str]] = {
    ID_PESSOA_PRESA: frozenset({"preso", "presa", "prisao", "cadeia", "presidio", "processo"}),
    ID_VIOLENCIA_DOMESTICA: frozenset({"violencia", "situacao", "agressao", "ameaca", "bate", "medida"}),
    ID_PROBLEMAS_PLANO_SAUDE: frozenset({"plano", "convenio", "cirurgia", "operacao"}),
    ID_SAUDE: frozenset({"saude", "hospital", "posto", "remedio", "exame", "internacao", "uti"}),
}
# Palavras curtas e comuns que não identificam assunto nenhum.
PALAVRAS_VAZIAS = frozenset(
    {"para", "pela", "pelo", "dela", "dele", "minha", "meu", "essa", "esse", "isso", "quero", "primeiro", "favor", "sobre", "falar"}
)

# "Pode", "blz", "ok": formas de aceitar a ordem, além do Sim que os fluxos já entendem.
ACEITES = frozenset(
    {
        "pode",
        "pode ser",
        "pode sim",
        "ok",
        "okay",
        "blz",
        "beleza",
        "isso",
        "aham",
        "ss",
        "sim sim",
        "claro",
        "tudo bem",
        "certo",
        "ta bom",
        "ta",
        "bora",
    }
)

NUMERO_POR_EXTENSO = {2: "duas", 3: "três", 4: "quatro", 5: "cinco"}


class ItemFila(TypedDict):
    id: str
    nome: str
    urgente: bool
    evidencia: str


class AssuntoPendente(TypedDict):
    """O que a Tykhe recebe em `assuntosPendentes`: o bastante para seguir com o próximo assunto."""

    nome: str
    # O sinal de risco do relato, marcado pela classificação.
    urgente: bool
    # #450: o parâmetro de urgência (tabela por assunto, com o sinal de risco por cima).
    urgencia: Urgencia
    flowId: NotRequired[str]
    tipoCaso: NotRequired[str]
    # #442: o que a Maria já sabe para este assunto; a Tykhe repassa ao abrir o fluxo dele.
    dadosConhecidos: NotRequired[dict[str, Any]]


class AssuntoGuardado(TypedDict):
    """#450: um assunto pendente de outra conversa da mesma pessoa, como fica no estado do orquestrador.
    Só o que a pergunta e a abertura precisam: sem datas, sem relato e sem dado pessoal. O id do assunto é o
    `chatId` dele, `chat_id_do_assunto(chatIdOrigem, posicao)`."""

    chatIdOrigem: str
    posicao: int
    nome: str
    urgente: bool
    # Sem o campo nos guardados antes de 2026-11-10: vale a tabela (`urgencia_de`).
    urgencia: NotRequired[Urgencia]
    flowId: NotRequired[str]
    tipoCaso: NotRequired[str]


class AssuntoAberto(TypedDict):
    """#450: um assunto em aberto da pessoa (desta conversa ou guardado de outra). O `chatIdAssunto` é o id interno do
    assunto e não vai para a Tykhe (`para_a_tykhe`): para ela, o assunto é o `flowId` (fluxo da Maria) ou o
    `tipoCaso` (assunto da Tykhe), que aparecem uma vez só na lista."""

    nome: str
    urgente: bool
    urgencia: Urgencia
    chatIdAssunto: str
    # O código curto do assunto, para a pessoa citar à equipe (o chatId inteiro é longo e pode levar o telefone).
    codigo: str
    # Onde o assunto está na Maria: ainda não começou ou já começou e não terminou (#456).
    fase: Literal["nao_iniciado", "em_andamento"]
    # Até quando o assunto fica guardado (AAAA-MM-DD). Só nos guardados, com o idUsuario.
    venceEm: NotRequired[str]
    flowId: NotRequired[str]
    tipoCaso: NotRequired[str]


class ResumoDoAssunto(TypedDict):
    """#450 (2026-11-11): uma linha do resumo da conversa, sem nada do relato da pessoa."""

    nome: str
    desfecho: str
    codigo: str


def _id_do_item(item: Mapping[str, Any]) -> str:
    if isinstance(item.get("flowId"), str):
        return str(item["flowId"])
    return f"tykhe:{item.get('tipoCaso') or 'outros'}"


def id_do_assunto(item: Mapping[str, Any]) -> str:
    """O id do tipo do assunto: o `flowId` (fluxo da Maria) ou `tykhe:<tipoCaso>` (assunto da Tykhe)."""
    return _id_do_item(item)


def para_a_tykhe(abertos: Sequence[AssuntoAberto]) -> list[dict[str, Any]]:
    """#450 (decisão da Nicole, 2026-11-13): `assuntosEmAberto` como vai para a Tykhe, sem o `chatIdAssunto`. O
    assunto é identificado pelo `flowId` ou pelo `tipoCaso`."""
    return [{chave: valor for chave, valor in aberto.items() if chave != "chatIdAssunto"} for aberto in abertos]


def chat_do_assunto_pelo_id(assunto: str, abertos: Sequence[AssuntoAberto]) -> str | None:
    """O `chatIdAssunto` interno do item de `assuntosEmAberto` cujo `flowId` ou `tipoCaso` é `assunto`. None quando
    nenhum assunto em aberto tem esse id."""
    for aberto in abertos:
        if assunto in (aberto.get("flowId"), aberto.get("tipoCaso")):
            return aberto["chatIdAssunto"]
    return None


def urgencia_de(item: Mapping[str, Any]) -> Urgencia:
    """A urgência de um pendente ou guardado. Os que vieram antes do campo usam a tabela e o sinal de risco."""
    urgencia = item.get("urgencia")
    if urgencia == "urgente":
        return "urgente"
    if urgencia == "menos_urgente":
        return "menos_urgente"
    return urgencia_do_assunto(_id_do_item(item), item.get("urgente") is True)


def montar_fila(necessidades: list[Necessidade]) -> list[ItemFila]:
    """Mesmo destino vira um item só; "fora da lista" vai para "outros" da Tykhe; "sair" sai da
    fila quando há outro assunto."""
    vistos: set[str] = set()
    itens: list[tuple[tuple[int, int, int], ItemFila]] = []
    for k, n in enumerate(necessidades):
        i = ID_OUTROS if n["id"] == FORA_DA_LISTA else n["id"]
        if i in vistos or (i == ID_SAIR and len(necessidades) > 1):
            continue
        vistos.add(i)
        prioridade = PRIORIDADE.get(i, 3)
        if prioridade < 3:
            chave = (prioridade, 0, k)
        else:
            chave = (3, 0 if n["urgente"] else 1 if i in CONDUZIDOS_PELA_MARIA else 2, k)
        itens.append(
            (chave, {"id": i, "nome": NOME_SIMPLES.get(i, "o outro assunto"), "urgente": n["urgente"], "evidencia": n["evidencia"]})
        )
    return [item for _, item in sorted(itens, key=lambda t: t[0])]


def _com_artigo(preposicao: str, nome: str) -> str:
    """("por", "a saúde") -> "pela saúde"; ("de", "o plano de saúde") -> "do plano de saúde"."""
    contracoes = {"por": ("pela ", "pelo "), "de": ("da ", "do ")}[preposicao]
    if nome.startswith("a "):
        return contracoes[0] + nome[2:]
    if nome.startswith("o "):
        return contracoes[1] + nome[2:]
    return f"{preposicao} {nome}"


def _lista(nomes: list[str]) -> str:
    return "\n".join(f"• {n}" for n in nomes)


def texto_ordem(fila: list[ItemFila]) -> str:
    nomes = [i["nome"] for i in fila]
    porque = ", porque parece mais urgente" if fila[0]["urgente"] else ""
    if len(fila) == 2:
        return (
            f"Entendi. Você falou de duas coisas: {nomes[0]} e {nomes[1]}.\n"
            f"Vou começar {_com_artigo('por', nomes[0])}{porque}.\n"
            f"Depois, falamos {_com_artigo('de', nomes[1])}.\n"
            "Pode ser assim?"
        )
    numero = NUMERO_POR_EXTENSO.get(len(fila), str(len(fila)))
    return (
        f"Entendi. Você falou de {numero} coisas:\n{_lista(nomes)}\n"
        f"Vou começar {_com_artigo('por', nomes[0])}{porque}.\n"
        "Depois, falamos das outras.\n"
        "Pode ser assim?"
    )


# Decisão da Nicole (2026-11-13): as listas em que a pessoa escolhe saem numeradas, com a legenda, e os botões levam
# o mesmo número ("1. A pessoa presa"). A resposta vale pelo número, pelo texto do botão ou pelo nome do assunto.
TEXTO_LEGENDA_NUMERO = "Responda com o número da opção."


def _numerada(nomes: Sequence[str], inicio: int = 1) -> list[str]:
    """ "1. A pessoa presa", "2. O plano de saúde"…"""
    return [f"{inicio + i}. {_maiuscula(nome)}" for i, nome in enumerate(nomes)]


def _numero_da_opcao(resposta: str) -> int | None:
    """O número de uma opção: "2", "2.", "2) O plano" ou o texto do botão "2. O plano de saúde"."""
    numero = re.fullmatch(r"\s*(\d{1,2})\s*(?:[.)\-–]\s*.*)?", resposta, flags=re.DOTALL)
    return int(numero.group(1)) if numero else None


def texto_qual_primeiro(fila: list[ItemFila]) -> str:
    lista = "\n".join(_numerada([i["nome"] for i in fila]))
    return f"Tudo bem. Qual você quer resolver primeiro?\n\n{lista}\n\n{TEXTO_LEGENDA_NUMERO}"


def opcoes_qual_primeiro(fila: list[ItemFila]) -> list[str]:
    return _numerada([i["nome"] for i in fila])


def texto_comecando(item: ItemFila) -> str:
    return f"Combinado. Vamos começar {_com_artigo('por', item['nome'])}."


def texto_proximo_assunto(item: Mapping[str, object]) -> str:
    """#450: a frase que abre o próximo assunto (ou um assunto guardado), antes da 1ª pergunta do fluxo dele."""
    return f"Agora vamos falar {_com_artigo('de', str(item['nome']))}."


def texto_fim_do_assunto(pendentes: list[AssuntoPendente], guardados: bool) -> str:
    """#450: no fim de um assunto, o que ainda falta, separado por urgência. O urgente é oferecido logo, e a Tykhe
    abre o próximo pela rota do próximo assunto; o menos urgente fica para depois. "Guardar por 30 dias" só aparece
    quando a Maria guardou mesmo (a Tykhe mandou o `idUsuario`)."""
    urgentes = [p["nome"] for p in pendentes if urgencia_de(p) == "urgente"]
    outros = [p["nome"] for p in pendentes if urgencia_de(p) == "menos_urgente"]
    partes: list[str] = []
    if len(urgentes) == 1:
        partes.append(f"Ainda falta um assunto urgente: {urgentes[0]}. Vamos falar dele agora.")
    elif urgentes:
        partes.append(f"Ainda faltam assuntos urgentes: {_nomes_juntos(urgentes)}. Vamos falar deles agora.")
    if outros:
        texto = f"{'Também ficou' if urgentes else 'Ficou'} para depois: {_nomes_juntos(outros)}."
        if guardados:
            quais = "esse assunto" if len(outros) == 1 else "esses assuntos"
            texto += f" Vou guardar {quais} por até 30 dias para a gente continuar depois."
        partes.append(texto)
    return "\n\n".join(partes)


def texto_pendentes_no_atendimento_humano(pendentes: Sequence[Mapping[str, Any]]) -> str:
    """Decisão da Nicole (2026-11-13): quando o assunto termina no atendimento humano, a Maria também avisa o que ficou
    para depois."""
    return f"Também ficou para depois: {_nomes_juntos([str(p['nome']) for p in pendentes])}."


def origem_do_chat(chat_id: str) -> tuple[str, int]:
    """O `chatId` da conversa e a posição do assunto: (`x`, 1) para `x`; (`x`, 2) para `x-assunto-2`."""
    m = re.fullmatch(rf"(.+){re.escape(SUFIXO_ASSUNTO)}(\d+)", chat_id)
    if m and int(m.group(2)) >= 2:
        return m.group(1), int(m.group(2))
    return chat_id, 1


# #450 (decisão da Nicole, 2026-11-11): os assuntos em aberto. A pessoa vem resolver alguma coisa, então a conversa não
# começa com pergunta. No fim de cada assunto, a Maria oferece ver os assuntos em aberto ou falar de um assunto novo.
# No começo, só quando a pessoa pede ("quero ver meus assuntos"), a Maria mostra a lista; e, se o que ela contou é
# um assunto que já estava guardado, a Maria retoma esse assunto em vez de abrir outro igual.
TEXTO_OPCAO_NENHUM = "Nenhum, quero um assunto novo"
TEXTO_FALAR_DE_NOVO = "Falar de um assunto novo"
TEXTO_ENCERRAR = "Encerrar a conversa"
TEXTO_ENCERRADA = "Combinado. Quando quiser, é só voltar a falar com a gente."
TEXTO_ENCERRADA_GUARDADOS = (
    "Combinado. Seus assuntos em aberto ficam guardados por até 30 dias. Quando quiser, é só voltar a falar com a gente."
)
FASES = {"nao_iniciado": "ainda não começou", "em_andamento": "em andamento"}
TEXTO_ASSUNTO_NOVO = "Pode me contar o que você precisa?"
TEXTO_SEM_ABERTOS = "Você não tem assuntos em aberto. Pode me contar o que você precisa?"
NUMERO_MASCULINO = {2: "dois", 3: "três", 4: "quatro", 5: "cinco"}
# Pedidos de ver os assuntos, em frases inteiras: "andamento" sozinho não entra, porque é o assunto "andamento do
# processo" da Tykhe.
PEDIDOS_DE_VER = (
    "meus assuntos",
    "assuntos em aberto",
    "assunto em aberto",
    "assuntos pendentes",
    "assunto pendente",
    "minhas pendencias",
    "minha pendencia",
    "o que ficou pendente",
    "ficou para depois",
    "ficaram para depois",
    "ficou pra depois",
    "ficaram pra depois",
    "assuntos guardados",
    "assunto guardado",
    "de onde parei",
    "onde eu parei",
    "onde parei",
    "o que estava em aberto",
    "o que tinha ficado",
)
# Assuntos que não se retomam: "outros" e "sair" não dizem qual era o assunto.
NAO_RETOMA = frozenset({ID_OUTROS, ID_SAIR})


def _maiuscula(nome: str) -> str:
    return nome[:1].upper() + nome[1:]


def _nomes_juntos(nomes: list[str]) -> str:
    """ "a", "a e b", "a, b e c"."""
    return nomes[0] if len(nomes) == 1 else f"{', '.join(nomes[:-1])} e {nomes[-1]}"


def em_ordem_de_urgencia(guardados: list[AssuntoGuardado]) -> list[AssuntoGuardado]:
    """Os urgentes primeiro, cada grupo na ordem em que foi guardado. A pergunta e as opções usam esta ordem."""
    return sorted(guardados, key=lambda g: URGENCIAS.index(urgencia_de(g)))


def pediu_para_ver_assuntos(mensagem: str) -> bool:
    """ "Quero ver meus assuntos", "o que ficou pendente", "continuar de onde parei"."""
    limpa = _limpa(mensagem)
    return any(pedido in limpa for pedido in PEDIDOS_DE_VER)


def codigo_do_assunto(chat_id_assunto: str) -> str:
    """6 letras e números tirados do id do assunto, sempre os mesmos para o mesmo assunto. A equipe chega ao assunto
    pelo código; o id inteiro não aparece para a pessoa."""
    resumo = hashlib.sha256(chat_id_assunto.encode("utf-8")).digest()
    return base64.b32encode(resumo).decode("ascii")[:6]


def desfecho_do_assunto(id_assunto: str | None, status: str | None) -> str:
    """O que aconteceu com o assunto, em palavras simples. A violência doméstica tem desfecho neutro, porque a mensagem
    pode ser lida por outra pessoa no celular."""
    if status == "redirecionado" or (id_assunto or "").startswith("tykhe:"):
        return "encaminhado para o atendimento certo"
    if id_assunto == ID_VIOLENCIA_DOMESTICA:
        return "encerrada" if status == "expirado" else "encaminhada" if status else "em andamento"
    if status == "concluido":
        return {ID_PESSOA_PRESA: "dados confirmados e encaminhados", ID_PROBLEMAS_PLANO_SAUDE: "pedido enviado à Defensoria"}.get(
            id_assunto or "", "resolvido aqui"
        )
    if status == "handoff_humano":
        return "encaminhado para a equipe da Defensoria"
    if status == "expirado":
        return "encerrado por falta de resposta"
    return "em andamento"


def _data_curta(data: str) -> str:
    return f"{data[8:10]}/{data[5:7]}" if len(data) >= 10 else data


def _detalhes_do_aberto(aberto: Mapping[str, Any]) -> str:
    """ "guardado até 13/12, ainda não começou": a urgência fica no título do grupo. Vai entre parênteses depois do nome
    (decisão da Nicole, 2026-11-13: no lugar do ponto do meio)."""
    detalhes = []
    if aberto.get("venceEm"):
        detalhes.append(f"guardado até {_data_curta(str(aberto['venceEm']))}")
    detalhes.append(FASES.get(str(aberto.get("fase")), "ainda não começou"))
    return ", ".join(detalhes)


def _grupos_por_urgencia(abertos: Sequence[Mapping[str, Any]], *, com_detalhes: bool) -> str:
    """Os assuntos em aberto numerados, em "Urgente:" e "Menos urgente:" (só os grupos que existem). A lista já vem com
    os urgentes primeiro (`assuntos_em_aberto`, `em_ordem_de_urgencia`), então a numeração segue a ordem dela, que é a
    mesma das opções e da leitura da resposta (`escolha_nos_abertos`)."""
    blocos: list[str] = []
    for urgencia, titulo in (("urgente", "Urgente:"), ("menos_urgente", "Menos urgente:")):
        linhas = []
        for numero, aberto in enumerate(abertos, start=1):
            if urgencia_de(aberto) != urgencia:
                continue
            linha = f"{numero}. {_maiuscula(str(aberto['nome']))}"
            linhas.append(f"{linha} ({_detalhes_do_aberto(aberto)})" if com_detalhes else linha)
        if linhas:
            blocos.append(titulo + "\n" + "\n".join(linhas))
    return "\n\n".join(blocos)


def _outras_opcoes(abertos: Sequence[Mapping[str, Any]], primeira: str) -> list[str]:
    """Depois dos assuntos: a opção de um assunto novo e a de encerrar, numeradas em seguida."""
    return _numerada([primeira, TEXTO_ENCERRAR], inicio=len(abertos) + 1)


def texto_fim_da_conversa(resumo: Sequence[ResumoDoAssunto], abertos: Sequence[Mapping[str, Any]], guardados: bool) -> str:
    """#450, no fim: o resumo da conversa, a pergunta e o que ainda está em aberto.

    Decisão da Nicole (2026-11-13): a pergunta fica antes; depois, "Ainda em aberto", com os assuntos numerados e
    separados por urgência; depois, as outras opções (assunto novo e encerrar) e a legenda do número. A frase muda com
    um assunto em aberto ou com vários."""
    partes = [
        "Resumo da nossa conversa:\n" + "\n".join(f"• {_maiuscula(r['nome'])}: {r['desfecho']} (código {r['codigo']})" for r in resumo)
    ]
    if not abertos:
        partes.append("Quer falar de um assunto novo ou encerrar a conversa?\n" + "\n".join(_outras_opcoes(abertos, TEXTO_FALAR_DE_NOVO)))
        partes.append(TEXTO_LEGENDA_NUMERO)
        return "\n\n".join(partes)
    if len(abertos) == 1:
        partes.append("Quer continuar com o assunto em aberto ou encerrar a conversa?")
    else:
        partes.append("Quer continuar com algum dos assuntos em aberto ou encerrar a conversa?")
    partes.append("Ainda em aberto:\n\n" + _grupos_por_urgencia(abertos, com_detalhes=True))
    partes.append("Outras opções:\n" + "\n".join(_outras_opcoes(abertos, TEXTO_FALAR_DE_NOVO)))
    legenda = TEXTO_LEGENDA_NUMERO
    if guardados:
        legenda += " Os assuntos em aberto ficam guardados por até 30 dias."
    partes.append(legenda)
    return "\n\n".join(partes)


def opcoes_do_fim(abertos: Sequence[Mapping[str, Any]]) -> list[str]:
    """Um botão numerado para cada assunto em aberto (abre direto), mais o assunto novo e o encerrar."""
    return [*_numerada([str(a["nome"]) for a in abertos]), *_outras_opcoes(abertos, TEXTO_FALAR_DE_NOVO)]


def texto_abertos(abertos: Sequence[Mapping[str, Any]], *, com_encerrar: bool = False) -> str:
    """A lista dos assuntos em aberto, numerada e separada por urgência, mais o assunto novo (e o encerrar, quando a
    lista vem do fim da conversa) e a legenda do número."""
    if com_encerrar:
        outras = _outras_opcoes(abertos, TEXTO_OPCAO_NENHUM)
    else:
        outras = _numerada([TEXTO_OPCAO_NENHUM], inicio=len(abertos) + 1)
    return (
        f"Qual você quer resolver agora?\n\n{_grupos_por_urgencia(abertos, com_detalhes=False)}\n\n"
        f"Outras opções:\n" + "\n".join(outras) + f"\n\n{TEXTO_LEGENDA_NUMERO}"
    )


def opcoes_abertos(abertos: Sequence[Mapping[str, Any]], *, com_encerrar: bool = False) -> list[str]:
    nomes = _numerada([str(a["nome"]) for a in abertos])
    if com_encerrar:
        return [*nomes, *_outras_opcoes(abertos, TEXTO_OPCAO_NENHUM)]
    return [*nomes, *_numerada([TEXTO_OPCAO_NENHUM], inicio=len(abertos) + 1)]


def texto_retomada(item: Mapping[str, object]) -> str:
    """O que a pessoa contou é um assunto que já estava guardado: a Maria retoma esse, sem abrir outro igual."""
    return f"Você já tinha esse assunto com a gente: {item['nome']}. Vamos continuar."


def escolha_nos_abertos(resposta: str, abertos: Sequence[Mapping[str, Any]]) -> int | Literal["nenhum", "encerrar"] | None:
    """A posição do assunto escolhido, "nenhum" para um assunto novo, "encerrar" para encerrar a conversa, ou None
    quando não dá para saber.

    Vale o texto da opção, o número dela (1, 2… na ordem dos assuntos; depois deles, o assunto novo e o encerrar) e o
    nome do assunto numa resposta livre ("o da cadeia")."""
    numero = _numero_da_opcao(resposta)
    if numero is not None:
        posicao = numero - 1
        if posicao == len(abertos):
            return "nenhum"
        if posicao == len(abertos) + 1:
            return "encerrar"
        return posicao if 0 <= posicao < len(abertos) else None
    limpa = _limpa(resposta)
    if not limpa:
        return None
    if re.search(r"\bencerr(ar|a|o)\b", limpa) or "terminar a conversa" in limpa:
        return "encerrar"
    if limpa == _limpa(TEXTO_OPCAO_NENHUM) or limpa.startswith("nenhum") or "assunto novo" in limpa:
        return "nenhum"
    for indice, aberto in enumerate(abertos):
        nome = _limpa(aberto["nome"])
        sem_artigo = nome.split(" ", 1)[1] if nome[:2] in ("a ", "o ") else nome
        if limpa in (nome, sem_artigo):
            return indice
    itens: list[ItemFila] = [{"id": _id_do_item(a), "nome": a["nome"], "urgente": bool(a.get("urgente")), "evidencia": ""} for a in abertos]
    return assunto_escolhido(resposta, itens)


def _palavras(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9]+", normalizar_resposta(texto)) if len(p) > 3 and p not in PALAVRAS_VAZIAS}


def assunto_escolhido(resposta: str, fila: list[ItemFila]) -> int | None:
    """A posição do assunto que a pessoa escolheu: pelo número da lista ("2"), pelo nome ("o plano")
    ou por uma palavra do que ela contou ("a do meu filho"). None quando não dá para saber."""
    numero = _numero_da_opcao(resposta)
    if numero is not None:
        posicao = numero - 1
        return posicao if 0 <= posicao < len(fila) else None
    ditas = _palavras(resposta)
    if not ditas:
        return None
    pontos = []
    for item in fila:
        chaves = _palavras(item["nome"]) | _palavras(item["evidencia"]) | PALAVRAS_DO_ASSUNTO.get(item["id"], frozenset())
        pontos.append(len(ditas & chaves))
    melhor = max(pontos)
    # Empate ou nenhuma palavra em comum: não dá para saber.
    return pontos.index(melhor) if melhor > 0 and pontos.count(melhor) == 1 else None


def _limpa(resposta: str) -> str:
    """Sem acento, sem pontuação e com um espaço só: "Pode!" e "pode" são a mesma resposta."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", normalizar_resposta(resposta)).split())


def aceitou(resposta: str) -> bool:
    return resposta_eh_sim(resposta) or _limpa(resposta) in ACEITES or resposta_eh_sim(_limpa(resposta))


def recusou(resposta: str) -> bool:
    """ "Não", "não quero", "prefiro não"... "Não sei" não é recusa: segue a ordem proposta."""
    limpa = _limpa(resposta)
    if limpa.startswith("nao sei"):
        return False
    return resposta_eh_nao(resposta) or limpa == "nao" or limpa.startswith("nao ") or limpa.endswith(" nao")


def para_frente(fila: list[ItemFila], posicao: int) -> list[ItemFila]:
    return [fila[posicao], *fila[:posicao], *fila[posicao + 1 :]]


def dados_do_relato(flow_id: str, relato: str, ja_conhecidos: Mapping[str, Any]) -> dict[str, Any]:
    """#438: o que o relato já diz, pelas palavras, sem IA, para o fluxo não perguntar de novo.

    Nunca troca o que já se sabe (`dadosConhecidos` da Tykhe). Na dúvida, nada: o fluxo pergunta."""
    if flow_id == ID_PESSOA_PRESA and "parentesco" not in ja_conhecidos:
        return dict(quem_esta_preso(relato))
    if flow_id == ID_PROBLEMAS_PLANO_SAUDE and "paraSi" not in ja_conhecidos:
        para_si = atendimento_para_si(relato)
        return {} if para_si is None else {"paraSi": para_si, "paraSiPeloRelato": True}
    if flow_id == ID_VIOLENCIA_DOMESTICA and "ehVitima" not in ja_conhecidos:
        return {"ehVitima": True, "vitimaPeloRelato": True} if fala_como_vitima(relato) else {}
    return {}


def pendente(item: ItemFila) -> AssuntoPendente:
    saida: AssuntoPendente = {
        "nome": item["nome"],
        "urgente": item["urgente"],
        "urgencia": urgencia_do_assunto(item["id"], item["urgente"]),
    }
    tipo = tipo_tykhe_por_id(item["id"])
    if tipo is not None:
        saida["tipoCaso"] = tipo.tipo_caso
    else:
        saida["flowId"] = item["id"]
        # #442: o que o trecho deste assunto já diz fica guardado para quando ele for aberto.
        lido = dados_do_relato(item["id"], item["evidencia"], {})
        if lido:
            saida["dadosConhecidos"] = lido
    return saida


def com_dados_do_fim(pendentes: list[AssuntoPendente], dados_coletados: Any) -> list[AssuntoPendente]:
    """#442: no fim do 1º assunto, o CPF que a pessoa informou nele vai junto para os próximos fluxos."""
    cpf = dados_coletados.get("cpf") if isinstance(dados_coletados, Mapping) else None
    if not isinstance(cpf, str) or not cpf:
        return pendentes
    saida: list[AssuntoPendente] = []
    for p in pendentes:
        p = dict(p)  # type: ignore[assignment]
        if "flowId" in p:
            p["dadosConhecidos"] = {"cpf": cpf, **p.get("dadosConhecidos", {})}
        saida.append(p)
    return saida
