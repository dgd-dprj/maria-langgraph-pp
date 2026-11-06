"""O parentesco de quem fala, tirado do relato pelas palavras, sem IA (#438, decisão da Nicole, 2026-11-06).

Achado do teste pela Tykhe: quem escrevia "Meu primo foi preso e quero saber quando sai" recebia depois
"Qual seu parentesco com a pessoa presa?", porque o fluxo não recebe o relato. Agora, quando o
orquestrador abre o fluxo, a Maria lê o parentesco no relato, e o fluxo pula a pergunta.

O parentesco é o de QUEM FALA em relação ao preso, como na pergunta do fluxo:
- "meu primo foi preso" → Primo(a);
- "meu tio foi preso" → Sobrinho(a);
- "sou a mãe dele" → Mãe.

Na dúvida, devolve None, e a Maria pergunta, como antes:
- "meu filho" (a mãe ou o pai?);
- parente que não está na lista do fluxo ("meu avô": quem fala é neto);
- mais de um parente no relato;
- erro de digitação ("mu imao").
"""

from __future__ import annotations

import re

from maria.shared.respostas import normalizar_resposta

# "meu X" / "minha X": quem fala é o INVERSO de X em relação ao preso.
_DO_PRESO_PARA_QUEM_FALA: dict[str, str] = {
    **dict.fromkeys(("primo", "prima", "primos", "primas"), "Primo(a)"),
    **dict.fromkeys(("irmao", "irma", "irmaos", "irmas"), "Irmão(a)"),
    **dict.fromkeys(("marido", "esposo", "esposa", "mulher"), "Esposo(a)"),
    **dict.fromkeys(("companheiro", "companheira"), "Companheiro(a)"),
    **dict.fromkeys(("tio", "tia", "tios"), "Sobrinho(a)"),
    **dict.fromkeys(("sobrinho", "sobrinha", "sobrinhos"), "Tio(a)"),
    **dict.fromkeys(("pai", "mae"), "Filho(a)"),
    **dict.fromkeys(("neto", "neta", "netos"), "Avô/Avó"),
    **dict.fromkeys(("genro", "nora"), "Sogro(a)"),
    **dict.fromkeys(("cunhado", "cunhada"), "Cunhado(a)"),
    **dict.fromkeys(("amigo", "amiga"), "Amigo(a)"),
}
# "sou a X dele": quem fala É X.
_QUEM_FALA_E: dict[str, str] = {
    "mae": "Mãe",
    "pai": "Pai",
    **dict.fromkeys(("irmao", "irma"), "Irmão(a)"),
    **dict.fromkeys(("esposa", "esposo", "mulher", "marido"), "Esposo(a)"),
    **dict.fromkeys(("companheira", "companheiro"), "Companheiro(a)"),
    **dict.fromkeys(("filho", "filha"), "Filho(a)"),
    **dict.fromkeys(("primo", "prima"), "Primo(a)"),
    **dict.fromkeys(("tio", "tia"), "Tio(a)"),
    **dict.fromkeys(("sobrinho", "sobrinha"), "Sobrinho(a)"),
    **dict.fromkeys(("avo", "avoa"), "Avô/Avó"),
    **dict.fromkeys(("cunhado", "cunhada"), "Cunhado(a)"),
    **dict.fromkeys(("sogro", "sogra"), "Sogro(a)"),
    **dict.fromkeys(("amigo", "amiga"), "Amigo(a)"),
}
# Parentes que tornam o relato duvidoso: "meu filho" (mãe ou pai?), "meu avô" (neto não está na lista),
# "meu sogro" (genro e nora não estão), "meu namorado" (não está), "meu enteado" (padrasto ou madrasta?).
_DUVIDOSOS = frozenset(
    {
        "filho",
        "filha",
        "filhos",
        "filhas",
        "enteado",
        "enteada",
        "avo",
        "avos",
        "sogro",
        "sogra",
        "namorado",
        "namorada",
        "padrasto",
        "madrasta",
        "neto",
    }
    - set(_DO_PRESO_PARA_QUEM_FALA)
)
_CONJUGES = frozenset({"marido", "esposo", "esposa", "mulher", "companheiro", "companheira"})

_MEU_X = re.compile(r"\b(?:meu|minha|meus|minhas)\s+(ex\s+)?([a-z]+)")
_SOU_X = re.compile(r"\bsou\s+(?:a\s+|o\s+)?(ex\s+)?([a-z]+)\s+(?:dele|dela)\b")


def _normalizado(relato: str) -> str:
    """Sem acento, minúsculo, com "ex-marido" e "ex marido" iguais."""
    return re.sub(r"[-‐‑–—]", " ", normalizar_resposta(relato))


def parentesco_do_relato(relato: str) -> str | None:
    """Um dos parentescos do fluxo (`PARENTESCOS_PERMITIDOS`), ou None quando não dá para saber."""
    if not isinstance(relato, str) or not relato.strip():
        return None
    texto = _normalizado(relato)
    achados: set[str] = set()
    for ex, palavra in _MEU_X.findall(texto):
        if palavra == "ex":
            achados.add("Ex-esposo(a)")
        elif ex:
            # "meu ex", "meu ex marido": ex-cônjuge. "meu ex cunhado" fica em dúvida.
            if palavra in _CONJUGES or (palavra not in _DO_PRESO_PARA_QUEM_FALA and palavra not in _DUVIDOSOS):
                achados.add("Ex-esposo(a)")
            else:
                return None
        elif palavra in _DUVIDOSOS:
            return None
        elif palavra in _DO_PRESO_PARA_QUEM_FALA:
            achados.add(_DO_PRESO_PARA_QUEM_FALA[palavra])
    for ex, palavra in _SOU_X.findall(texto):
        if ex or palavra == "ex":
            achados.add("Ex-esposo(a)")
        elif palavra in _QUEM_FALA_E:
            achados.add(_QUEM_FALA_E[palavra])
    return achados.pop() if len(achados) == 1 else None
