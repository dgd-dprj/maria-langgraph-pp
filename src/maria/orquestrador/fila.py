"""Fila de assuntos do multi-fluxo (#435, fase 1a da #279): a ordem, os textos e a leitura da resposta.

Sem IA: a ordem e os textos são fixos, no padrão de linguagem acessível combinado com a Nicole
(28 e 29/10): frases curtas, nomes curtos e sempre os mesmos, pergunta de Sim ou Não.

Fase 1a: a Maria atende o primeiro assunto da fila. Os outros voltam à Tykhe em `assuntosPendentes`.
Por isso os textos não prometem "tudo aqui mesmo", como o protótipo fazia.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, NotRequired, TypedDict

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA
from maria.fluxos.tipos_tykhe import tipo_tykhe_por_id
from maria.ia.classificar_necessidades import FORA_DA_LISTA, Necessidade
from maria.shared.parentesco import atendimento_para_si, fala_como_vitima, quem_esta_preso
from maria.shared.respostas import normalizar_resposta, resposta_eh_nao, resposta_eh_sim

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

# Ordem padrão (Nicole, 28 e 29/10), com ou sem urgência: saúde primeiro, porque risco à saúde não
# espera; depois a violência doméstica; depois a pessoa presa; depois o resto, o urgente antes, o
# que a Maria conduz em seguida e o que é da Tykhe por último.
PRIORIDADE: dict[str, int] = {ID_SAUDE: 0, ID_PROBLEMAS_PLANO_SAUDE: 0, ID_VIOLENCIA_DOMESTICA: 1, ID_PESSOA_PRESA: 2}
CONDUZIDOS_PELA_MARIA = frozenset({ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, ID_PROBLEMAS_PLANO_SAUDE})

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
    urgente: bool
    flowId: NotRequired[str]
    tipoCaso: NotRequired[str]
    # #442: o que a Maria já sabe para este assunto; a Tykhe repassa ao abrir o fluxo dele.
    dadosConhecidos: NotRequired[dict[str, Any]]


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


def texto_qual_primeiro(fila: list[ItemFila]) -> str:
    return f"Tudo bem. Qual você quer resolver primeiro?\n{_lista([i['nome'] for i in fila])}"


def texto_comecando(item: ItemFila) -> str:
    return f"Combinado. Vamos começar {_com_artigo('por', item['nome'])}."


def _palavras(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9]+", normalizar_resposta(texto)) if len(p) > 3 and p not in PALAVRAS_VAZIAS}


def assunto_escolhido(resposta: str, fila: list[ItemFila]) -> int | None:
    """A posição do assunto que a pessoa escolheu: pelo número da lista ("2"), pelo nome ("o plano")
    ou por uma palavra do que ela contou ("a do meu filho"). None quando não dá para saber."""
    numero = re.fullmatch(r"\s*(\d+)\s*", resposta)
    if numero:
        posicao = int(numero.group(1)) - 1
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
    saida: AssuntoPendente = {"nome": item["nome"], "urgente": item["urgente"]}
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
