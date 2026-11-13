"""Quem é quem no relato, pelas palavras, sem IA (#438, decisões da Nicole de 2026-11-06).

Achado do teste pela Tykhe: quem escrevia "Meu primo foi preso e quero saber quando sai" recebia depois
"Qual seu parentesco com a pessoa presa?". Agora o orquestrador lê o relato e entrega aos fluxos o que
ele já diz:

- **pessoa presa** (`quem_esta_preso`): o parentesco de QUEM FALA em relação ao preso ("meu tio" é
  Sobrinho(a), "meu avô" é Neto(a), "sou a mãe dele" é Mãe). Com "meu filho", a Maria entende que o
  preso é o filho e pergunta só se a pessoa é a mãe ou o pai. Com dois parentes, ela reconhece qual
  está preso ("minha mãe disse que meu primo foi preso" é o primo) e, se forem dois presos, pergunta
  qual deles;
- **plano de saúde** (`atendimento_para_si`): "o plano da minha mãe negou a cirurgia" é para outra
  pessoa; "meu plano negou minha cirurgia" é para a própria pessoa;
- **violência doméstica** (`fala_como_vitima`): "meu marido me bate" é a vítima. Só o Sim é lido: o
  Não encerra o atendimento, então, quando a vítima parece ser outra pessoa, a Maria pergunta.

Na dúvida, devolve None, e o fluxo pergunta, como antes.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple, TypedDict

# Valores especiais do parentesco: o preso é filho ou filha de quem fala (falta saber se é a mãe ou o
# pai), ou um parente que não está na lista do fluxo.
MAE_OU_PAI_DELE = "mae_ou_pai:dele"
MAE_OU_PAI_DELA = "mae_ou_pai:dela"
# #212 (decisão da Nicole, 2026-11-13): "Irmão(a)" virou "Irmão" e "Irmã". Em "meu irmão foi preso" não dá para saber
# se quem fala é irmão ou irmã: a Maria pergunta, como faz com a mãe e o pai.
IRMAO_OU_IRMA_DELE = "irmao_ou_irma:dele"
IRMAO_OU_IRMA_DELA = "irmao_ou_irma:dela"
# Os valores que viram uma pergunta curta, e não um parentesco.
PEDEM_PERGUNTA = frozenset({MAE_OU_PAI_DELE, MAE_OU_PAI_DELA, IRMAO_OU_IRMA_DELE, IRMAO_OU_IRMA_DELA})
DUVIDA = "duvida"


class Parente(NamedTuple):
    nome: str  # como aparece nas mensagens: "seu primo", "sua avó"
    de_quem_fala: str  # o parentesco de quem fala em relação a esse parente


# "meu X" / "minha X" (a chave é a palavra sem acento): quem fala é o INVERSO de X.
PARENTES: dict[str, Parente] = {
    "primo": Parente("seu primo", "Primo(a)"),
    "prima": Parente("sua prima", "Primo(a)"),
    "irmao": Parente("seu irmão", IRMAO_OU_IRMA_DELE),
    "irma": Parente("sua irmã", IRMAO_OU_IRMA_DELA),
    "marido": Parente("seu marido", "Esposo(a)"),
    "esposo": Parente("seu esposo", "Esposo(a)"),
    "esposa": Parente("sua esposa", "Esposo(a)"),
    "mulher": Parente("sua mulher", "Esposo(a)"),
    "companheiro": Parente("seu companheiro", "Companheiro(a)"),
    "companheira": Parente("sua companheira", "Companheiro(a)"),
    "tio": Parente("seu tio", "Sobrinho(a)"),
    "tia": Parente("sua tia", "Sobrinho(a)"),
    "sobrinho": Parente("seu sobrinho", "Tio(a)"),
    "sobrinha": Parente("sua sobrinha", "Tio(a)"),
    "pai": Parente("seu pai", "Filho(a)"),
    "mae": Parente("sua mãe", "Filho(a)"),
    "avo": Parente("seu avô ou sua avó", "Neto(a)"),
    "neto": Parente("seu neto", "Avô/Avó"),
    "neta": Parente("sua neta", "Avô/Avó"),
    "genro": Parente("seu genro", "Sogro(a)"),
    "nora": Parente("sua nora", "Sogro(a)"),
    "cunhado": Parente("seu cunhado", "Cunhado(a)"),
    "cunhada": Parente("sua cunhada", "Cunhado(a)"),
    "amigo": Parente("seu amigo", "Amigo(a)"),
    "amiga": Parente("sua amiga", "Amigo(a)"),
    "filho": Parente("seu filho", MAE_OU_PAI_DELE),
    "filha": Parente("sua filha", MAE_OU_PAI_DELA),
    "ex": Parente("seu ex", "Ex-esposo(a)"),
    # #212 (decisão da Nicole, 2026-11-13): "Genro/Nora" entrou na lista; "meu sogro foi preso" é o genro ou a nora.
    "sogro": Parente("seu sogro", "Genro/Nora"),
    "sogra": Parente("sua sogra", "Genro/Nora"),
    # Fora da lista do fluxo: a Maria pergunta.
    "enteado": Parente("seu enteado", DUVIDA),
    "enteada": Parente("sua enteada", DUVIDA),
    "namorado": Parente("seu namorado", DUVIDA),
    "namorada": Parente("sua namorada", DUVIDA),
    "padrasto": Parente("seu padrasto", DUVIDA),
    "madrasta": Parente("sua madrasta", DUVIDA),
}
_PLURAIS = {"primos": "primo", "primas": "prima", "irmaos": "irmao", "irmas": "irma", "tios": "tio", "sobrinhos": "sobrinho",
            "filhos": "filho", "filhas": "filha", "netos": "neto", "avos": "avo", "amigos": "amigo"}  # fmt: skip
_CONJUGES = frozenset({"marido", "esposo", "esposa", "mulher", "companheiro", "companheira"})

# "sou a X dele": quem fala É X.
QUEM_FALA_E: dict[str, str] = {
    "mae": "Mãe",
    "pai": "Pai",
    "irmao": "Irmão",
    "irma": "Irmã",
    **dict.fromkeys(("esposa", "esposo", "mulher", "marido"), "Esposo(a)"),
    **dict.fromkeys(("companheira", "companheiro"), "Companheiro(a)"),
    **dict.fromkeys(("filho", "filha"), "Filho(a)"),
    **dict.fromkeys(("primo", "prima"), "Primo(a)"),
    **dict.fromkeys(("tio", "tia"), "Tio(a)"),
    **dict.fromkeys(("sobrinho", "sobrinha"), "Sobrinho(a)"),
    **dict.fromkeys(("avo",), "Avô/Avó"),
    **dict.fromkeys(("neto", "neta"), "Neto(a)"),
    **dict.fromkeys(("cunhado", "cunhada"), "Cunhado(a)"),
    **dict.fromkeys(("sogro", "sogra"), "Sogro(a)"),
    **dict.fromkeys(("genro", "nora"), "Genro/Nora"),
    **dict.fromkeys(("amigo", "amiga"), "Amigo(a)"),
}

# Palavras de prisão (sem acento), inclusive as populares.
_PRISAO = frozenset(
    {"preso", "presa", "presos", "presas", "prisao", "cadeia", "rodou", "rodaram", "cana", "bangu", "gericino", "detido",
     "detida", "detidos", "flagrante", "presidio", "custodia", "puxando", "sistema"}
)  # fmt: skip
_PRISAO_PLURAL = frozenset({"presos", "presas", "rodaram", "detidos"})
# Verbos que vêm ANTES do preso: "prenderam meu primo", "a polícia levou meu filho".
_PRENDER = frozenset({"prenderam", "prendeu", "pegaram", "pegou", "levaram", "levou", "detiveram", "deteve"})
_POSSESSIVOS = frozenset({"meu", "minha", "meus", "minhas"})


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _frases(relato: str) -> list[list[str]]:
    """Palavras sem acento, frase por frase ("ex-marido" vira "ex marido")."""
    texto = re.sub(r"[-‐‑–—]", " ", _sem_acento(relato))
    return [re.findall(r"[a-z0-9]+", frase) for frase in re.split(r"[.!?;\n]+", texto)]


class _Citacao(NamedTuple):
    posicao: int
    palavra: str  # chave de PARENTES


def _citacoes(palavras: list[str]) -> list[_Citacao]:
    """Cada "meu X" / "minha X" de parente, na ordem. "meu ex marido" é ex; "meu ex cunhado" fica em dúvida."""
    citacoes = []
    for i, palavra in enumerate(palavras[:-1]):
        if palavra not in _POSSESSIVOS:
            continue
        seguinte = _PLURAIS.get(palavras[i + 1], palavras[i + 1])
        if seguinte == "ex":
            depois = palavras[i + 2] if i + 2 < len(palavras) else ""
            depois = _PLURAIS.get(depois, depois)
            if depois in PARENTES and depois not in _CONJUGES:
                citacoes.append(_Citacao(i + 1, "enteado"))  # ex de outro parente: dúvida
            else:
                citacoes.append(_Citacao(i + 1, "ex"))
        elif seguinte in PARENTES:
            citacoes.append(_Citacao(i + 1, seguinte))
    return citacoes


def _presos(palavras: list[str], citacoes: list[_Citacao]) -> list[_Citacao]:
    """Os parentes ligados à prisão: o último citado antes da palavra de prisão ("minha mãe disse que meu
    primo foi preso" é o primo); com plural ("meu primo e meu irmão foram presos"), os da enumeração;
    depois de "prenderam"/"levaram", o parente logo em seguida."""
    ligados: list[_Citacao] = []
    for j, palavra in enumerate(palavras):
        if palavra in _PRENDER:
            seguinte = next((c for c in citacoes if j < c.posicao <= j + 4), None)
            if seguinte:
                ligados.append(seguinte)
        if palavra not in _PRISAO:
            continue
        antes = [c for c in citacoes if c.posicao < j]
        if not antes:
            continue
        ultimo = antes[-1]
        ligados.append(ultimo)
        if palavra in _PRISAO_PLURAL or (j > 0 and palavras[j - 1] in {"foram", "estao", "tao", "sao"}):
            # Volta pela enumeração: "meu primo e meu irmão", "meu primo, meu irmão".
            for anterior in reversed(antes[:-1]):
                entre = palavras[anterior.posicao + 1 : ultimo.posicao - 1]
                if entre not in ([], ["e"]):
                    break
                ligados.append(anterior)
                ultimo = anterior
    # Na ordem do relato, como a pessoa contou.
    return sorted(set(ligados), key=lambda c: c.posicao)


class AnaliseParentesco(TypedDict, total=False):
    """O que o fluxo de pessoa presa recebe: o parentesco pronto, ou uma pergunta mais curta."""

    parentesco: str
    perguntaParentesco: str
    opcoesParentesco: dict[str, str]  # palavra (sem acento) -> parentesco ou um valor de PEDEM_PERGUNTA


def texto_mae_ou_pai(valor: str) -> str:
    return f"Você é a mãe ou o pai {'dela' if valor == MAE_OU_PAI_DELA else 'dele'}?"


OPCOES_MAE_PAI = {"mae": "Mãe", "pai": "Pai"}
OPCOES_IRMAO_IRMA = {"irmao": "Irmão", "irma": "Irmã"}


def pergunta_curta(valor: str) -> AnaliseParentesco:
    """A pergunta curta de um valor de PEDEM_PERGUNTA: "Você é a mãe ou o pai dele?", "Você é irmão ou irmã dela?"."""
    if valor in (MAE_OU_PAI_DELE, MAE_OU_PAI_DELA):
        return {"perguntaParentesco": texto_mae_ou_pai(valor), "opcoesParentesco": dict(OPCOES_MAE_PAI)}
    de_quem = "dela" if valor == IRMAO_OU_IRMA_DELA else "dele"
    return {"perguntaParentesco": f"Você é irmão ou irmã {de_quem}?", "opcoesParentesco": dict(OPCOES_IRMAO_IRMA)}


def _juntar(nomes: list[str]) -> str:
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _do(nome: str) -> str:
    """ "seu primo" -> "do seu primo"; "sua prima" -> "da sua prima"."""
    return ("da " if nome.startswith("sua") else "do ") + nome


def quem_esta_preso(relato: str) -> AnaliseParentesco:
    """Para o fluxo de pessoa presa. Vazio quando não dá para saber: o fluxo faz a pergunta de sempre."""
    if not isinstance(relato, str) or not relato.strip():
        return {}
    frases = _frases(relato)
    # "sou a mãe dele" diz direto quem fala.
    diretos = {
        QUEM_FALA_E[_PLURAIS.get(m, m)]
        for palavras in frases
        for m in re.findall(r"\bsou (?:a |o )?([a-z]+) (?:dele|dela)\b", " ".join(palavras))
        if _PLURAIS.get(m, m) in QUEM_FALA_E
    }
    if len(diretos) == 1:
        return {"parentesco": diretos.pop()}

    citados: list[str] = []
    presos: list[str] = []
    for palavras in frases:
        citacoes = _citacoes(palavras)
        citados += [c.palavra for c in citacoes]
        presos += [c.palavra for c in _presos(palavras, citacoes)]
    candidatos = list(dict.fromkeys(presos or citados))
    if not candidatos:
        return {}
    valores = {PARENTES[p].de_quem_fala for p in candidatos}
    if len(valores) == 1:
        valor = valores.pop()
        if valor == DUVIDA:
            return {}
        if valor in PEDEM_PERGUNTA:
            return pergunta_curta(valor)
        return {"parentesco": valor}
    # Dois presos (ou dois parentes sem saber qual): pergunta qual deles.
    nomes = [PARENTES[p].nome for p in candidatos]
    return {
        "perguntaParentesco": f"Você falou {_juntar([_do(n) for n in nomes])}. Sobre qual deles é este atendimento?",
        "opcoesParentesco": {p: PARENTES[p].de_quem_fala for p in candidatos},
    }


def ler_resposta_parentesco(resposta: str, opcoes: dict[str, str]) -> str | None:
    """A resposta à pergunta curta: "o primo", "sou a mãe", "2". None quando não dá para saber."""
    palavras = [_PLURAIS.get(p, p) for p in re.findall(r"[a-z0-9]+", _sem_acento(resposta or ""))]
    chaves = list(opcoes)
    if len(palavras) == 1 and palavras[0].isdigit() and 1 <= int(palavras[0]) <= len(chaves):
        return opcoes[chaves[int(palavras[0]) - 1]]
    achados = {opcoes[p] for p in palavras if p in opcoes}
    return achados.pop() if len(achados) == 1 else None


# ── Pessoa presa: a resposta à pergunta "Qual seu parentesco com a pessoa presa?" ─────
# #212 (decisão da Nicole, 2026-11-13): as formas comuns de dizer o parentesco são lidas pelas palavras, sem IA, para
# todos os parentescos da lista. O Qwen lia "genro" e "sou casado com a filha dele" como "Sogro(a)" (#472). Só vale
# quando a resposta INTEIRA casa com uma das formas abaixo; o resto continua indo para a IA, como antes.

# "X", "sou o X", "X dele", "sou a X do preso": quem fala É X (a chave é a palavra sem acento).
_QUEM_E: dict[str, str] = {
    **QUEM_FALA_E,
    **dict.fromkeys(("mamae", "mainha", "maezinha"), "Mãe"),
    **dict.fromkeys(("papai", "painho"), "Pai"),
    **dict.fromkeys(("vo", "vovo", "vovoa"), "Avô/Avó"),
    # Parente fora da lista e quem não é parente.
    **dict.fromkeys(
        ("enteado", "enteada", "padrasto", "madrasta", "padrinho", "madrinha", "afilhado", "afilhada", "advogado",
         "advogada", "vizinho", "vizinha", "colega", "conhecido", "conhecida", "outro", "outra",
         # Decisão da Nicole (2026-11-13): namorado e namorada são "Outro" (não é "Companheiro(a)").
         "namorado", "namorada"),
        "Outro",
    ),
}  # fmt: skip

# "A do/da B dele": quem fala é A de um parente B da pessoa presa ("marido da filha dele" é o genro).
_GRUPO: dict[str, str] = {
    **dict.fromkeys(_CONJUGES, "conjuge"),
    **dict.fromkeys(("pai", "mae"), "pai_mae"),
    **dict.fromkeys(("filho", "filha"), "filho"),
    **dict.fromkeys(("irmao", "irma"), "irmao"),
    **dict.fromkeys(("tio", "tia"), "tio"),
}
_COMPOSTO: dict[tuple[str, str], str] = {
    ("conjuge", "filho"): "Genro/Nora",  # marido da filha, esposa do filho, casado com a filha
    ("pai_mae", "conjuge"): "Sogro(a)",  # mãe da esposa
    ("irmao", "conjuge"): "Cunhado(a)",  # irmão da esposa
    ("conjuge", "irmao"): "Cunhado(a)",  # esposa do irmão
    ("filho", "irmao"): "Sobrinho(a)",  # filho do irmão
    ("filho", "filho"): "Neto(a)",  # filha do filho
    ("filho", "tio"): "Primo(a)",  # filho do tio
    ("irmao", "pai_mae"): "Tio(a)",  # irmã da mãe
    ("pai_mae", "pai_mae"): "Avô/Avó",  # mãe da mãe
}

# "A do/da meu/minha B": a pessoa presa é A de um parente B de quem fala ("pai da minha esposa": quem fala é o genro).
# Medido em 2026-11-13 (#212): o Haiku e o Qwen liam "o pai da minha esposa" e "o preso é o meu sogro" como "Sogro(a)".
_COMPOSTO_INVERSO: dict[tuple[str, str], str] = {
    ("pai_mae", "conjuge"): "Genro/Nora",  # pai da minha esposa
    ("conjuge", "filho"): "Sogro(a)",  # marido da minha filha
    ("irmao", "conjuge"): "Cunhado(a)",  # irmão da minha esposa
    ("conjuge", "irmao"): "Cunhado(a)",  # esposa do meu irmão
    ("filho", "irmao"): "Tio(a)",  # filho do meu irmão
    ("filho", "filho"): "Avô/Avó",  # filho do meu filho
    ("filho", "tio"): "Primo(a)",  # filho do meu tio
    ("irmao", "pai_mae"): "Sobrinho(a)",  # irmão da minha mãe
    ("pai_mae", "pai_mae"): "Neto(a)",  # mãe do meu pai
}

_COMECO = r"(?:(?:eu )?(?:sou|seria) )?(?:(?:o|a|um|uma) )?"
_FIM = r"(?: (?:dele|dela|d[oa] (?:pres[oa]|detent[oa]|apenad[oa])))?"
# "ele é", "o preso é": quem é a pessoa presa, antes do "meu X".
_SUJEITO = r"(?:(?:o |a )?(?:ele|ela|pres[oa]|detent[oa]|apenad[oa]) e )?"
# "ex", "ex marido", "ex mulher": o ex-cônjuge.
_EX = rf"ex(?: (?:{'|'.join(sorted(_CONJUGES))}))?"
_DIRETO = re.compile(rf"{_COMECO}(?P<x>{_EX}|[a-z]+){_FIM}")
_COMPOSICAO = re.compile(rf"{_COMECO}(?P<a>[a-z]+) d[oa]s? (?P<b>[a-z]+){_FIM}")
_CASADO = re.compile(rf"{_COMECO}casad[oa] com (?:(?:o|a) )?(?P<b>[a-z]+){_FIM}")
_POSSE = re.compile(rf"{_SUJEITO}(?:(?:o|a) )?(?:meu|minha) (?P<y>{_EX}|[a-z]+)")
_POSSE_COMPOSTA = re.compile(rf"{_SUJEITO}(?:(?:o|a) )?(?P<a>[a-z]+) d[oa]s? (?:meus|minhas|meu|minha) (?P<b>[a-z]+)")
# Palavras de parentesco: num trecho que a leitura não entendeu, elas mandam a resposta inteira para a IA.
_PALAVRAS_DE_PARENTESCO = frozenset(QUEM_FALA_E) | frozenset(PARENTES) | {"mamae", "papai", "vo", "vovo"}


def _ex(palavras: str) -> bool:
    return palavras.split()[0] == "ex"


def parentesco_pela_resposta(resposta: str) -> str | None:
    """O parentesco lido pelas palavras, ou None para a IA decidir.

    Lê "genro", "sou a mãe dele", "irmã do preso", "marido da filha dele", "sou casado com a filha dele",
    "mãe da esposa dele", "meu genro", "ele é meu tio", "o preso é o meu sogro" e "pai da minha esposa". "Meu filho"
    e "meu irmão" voltam como um valor de PEDEM_PERGUNTA (mãe ou pai? irmão ou irmã?). Fica com a IA o que pede
    interpretação: frase longa, nome próprio e o que não está aqui.

    Resposta com vírgula ("ele é o pai da minha esposa, ela pediu pra eu ver"): vale o parentesco dos trechos lidos,
    se todos derem o mesmo, se a resposta não tiver "não" e se nenhum trecho não lido falar de outro parente.
    """
    if not isinstance(resposta, str):
        return None
    palavras = [p for frase in _frases(resposta) for p in frase]
    if not palavras:
        return None
    if len(palavras) <= 8 and (lido := _ler_trecho(" ".join(palavras))):
        return lido
    if "nao" in palavras or "," not in resposta:
        return None
    lidos: set[str] = set()
    for trecho in resposta.split(","):
        termos = [p for frase in _frases(trecho) for p in frase]
        if not termos:
            continue
        valor = _ler_trecho(" ".join(termos)) if len(termos) <= 8 else None
        if valor:
            lidos.add(valor)
        elif _PALAVRAS_DE_PARENTESCO & set(termos):
            return None  # "sogra, mas na verdade sou a mãe": a IA decide
    return lidos.pop() if len(lidos) == 1 else None


def _ler_trecho(texto: str) -> str | None:
    """Um trecho (sem vírgula, até 8 palavras sem acento) lido pelas formas conhecidas, ou None."""
    if direto := _DIRETO.fullmatch(texto):
        x = direto["x"]
        if _ex(x):
            return "Ex-esposo(a)"
        return _QUEM_E.get(_PLURAIS.get(x, x))
    if casado := _CASADO.fullmatch(texto):
        return _COMPOSTO.get(("conjuge", _GRUPO.get(casado["b"], "")))
    if composicao := _COMPOSICAO.fullmatch(texto):
        return _COMPOSTO.get((_GRUPO.get(composicao["a"], ""), _GRUPO.get(composicao["b"], "")))
    if inversa := _POSSE_COMPOSTA.fullmatch(texto):
        return _COMPOSTO_INVERSO.get((_GRUPO.get(inversa["a"], ""), _GRUPO.get(inversa["b"], "")))
    if posse := _POSSE.fullmatch(texto):
        y = posse["y"]
        if _ex(y):
            return "Ex-esposo(a)"
        parente = PARENTES.get(y)
        # "meu filho" e "meu irmão" voltam como um valor de PEDEM_PERGUNTA: o fluxo faz a pergunta curta.
        if parente and parente.de_quem_fala != DUVIDA:
            return parente.de_quem_fala
    return None


# ── Plano de saúde: o atendimento é para a própria pessoa? ─────────────────────────
_SAUDE = frozenset(
    {"plano", "convenio", "cirurgia", "operar", "operacao", "internar", "internacao", "internada", "internado", "exame",
     "remedio", "tratamento", "protese", "consulta", "hospital", "unimed", "amil", "hapvida", "bradesco", "sulamerica"}
)  # fmt: skip
_PACIENTE_EU = re.compile(
    r"\b(minha (cirurgia|operacao|internacao|protese|consulta)|meu (tratamento|exame|remedio)|me (operar|internar)"
    r"|preciso (operar|de uma cirurgia|fazer uma cirurgia|internar)|eu preciso|eu (to|estou) internad[ao])\b"
)
_MEU_PLANO = re.compile(r"\b(meu plano|meu convenio)\b")


def atendimento_para_si(relato: str) -> bool | None:
    """True: é para a própria pessoa; False: é para um parente ("o plano da minha mãe"); None: dúvida."""
    if not isinstance(relato, str) or not relato.strip():
        return None
    frases = _frases(relato)
    # Um parente citado na mesma frase que o assunto de saúde: "o plano da minha mãe", "meu pai precisa operar".
    parente_na_saude = any(_citacoes(palavras) and _SAUDE & set(palavras) for palavras in frases)
    texto = " ".join(" ".join(p) for p in frases)
    eu_paciente = _PACIENTE_EU.search(texto) is not None
    if parente_na_saude:
        return None if eu_paciente else False
    if eu_paciente or _MEU_PLANO.search(texto):
        return True
    return None


# ── Violência doméstica: quem fala é a vítima? ─────────────────────────────────────
_VIOLENCIA_EM_MIM = re.compile(
    r"\b(me|mim) (bate|bateu|batendo|agride|agrediu|agredindo|ameaca|ameacou|ameacando|ameacado|xinga|xingou|espanca|espancou"
    r"|empurrou|machuca|machucou|persegue|perseguindo|estuprou|violentou|humilha|forcou|enforcou|chutou|socou|deu um tapa)\b"
    r"|\b(eu )?(apanho|apanhei|apanhando)\b|\bfui (agredida|agredido|ameacada|ameacado|espancada|espancado)\b"
    r"|\b(sofro|sofri|sofrendo) (violencia|agressao)\b|\bbate em mim\b"
)


def fala_como_vitima(relato: str) -> bool | None:
    """True quando quem fala conta a violência contra si ("ele me bate"). Nunca devolve False: na
    violência doméstica, o Não encerra o atendimento, então a dúvida fica com a pergunta."""
    if not isinstance(relato, str) or not relato.strip():
        return None
    texto = " ".join(" ".join(p) for p in _frases(relato))
    return True if _VIOLENCIA_EM_MIM.search(texto) else None
