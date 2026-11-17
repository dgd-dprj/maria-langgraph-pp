"""As regras de tom da pergunta que a IA escreve para a pessoa (#508), medidas sem guardar o texto.

Decisão da Nicole (2026-11-17): o Visor mostra o tom da produção com números reais, e não só a comparação com
relatos inventados. A Maria mede cada pergunta de desambiguação na hora e registra só os números (evento
`desambiguacao_tom`): nunca a pergunta, nunca o relato. As mesmas regras servem à comparação
(`scripts/avaliacao/tom_desambiguacao.py`), para os dois números serem comparáveis.
"""

from __future__ import annotations

import re

# Os nomes internos do catálogo (com hífen) e as palavras do sistema. Hífen de pronome ("proteger-se") não conta.
NOMES_DO_CATALOGO = (
    "pessoa-presa",
    "violencia-domestica",
    "problemas-plano-de-saude",
    "questoes-de-saude",
    "iniciar-novo-processo",
    "ver-andamento-do-processo",
    "ver-meus-agendamentos",
    "ajuda-app-defensoria-rj",
    "outros-assuntos",
)
TERMOS_TECNICOS = re.compile(
    "|".join(re.escape(n) for n in NOMES_DO_CATALOGO) + r"|\btykhe\b|\bfluxo\b|\bcat[aá]logo\b|\bop[cç][aã]o \d", re.IGNORECASE
)
ACOLHIMENTO = re.compile(
    r"\b(você|vc|pode|por favor|pra te ajudar|para te ajudar|me conta|me conte|entendi|certo|claro|vamos|ajudar|tudo bem|obrigad[ao])\b",
    re.IGNORECASE,
)
TEM_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿]")
EMOJI_NO_FIM = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️‍\\s]+$")
LIMITE_DE_PALAVRAS = 25


def medir_tom(pergunta: str, sensivel: bool) -> dict[str, bool | int]:
    """As regras de tom de uma pergunta, em números e sim ou não. Nada do texto sai daqui."""
    sem_emoji_no_fim = EMOJI_NO_FIM.sub("", pergunta).strip()
    # O emoji não conta como palavra.
    palavras = len(TEM_EMOJI.sub(" ", pergunta).split())
    com_emoji = TEM_EMOJI.search(pergunta) is not None
    return {
        "palavras": palavras,
        "ateLimiteDePalavras": palavras <= LIMITE_DE_PALAVRAS,
        # O emoji depois do "?" ("…ou com a cirurgia? 😊") não tira a pergunta do fim.
        "terminaEmPergunta": sem_emoji_no_fim.endswith("?"),
        "semTermoTecnico": TERMOS_TECNICOS.search(pergunta) is None,
        "ofereceAlternativas": " ou " in f" {pergunta.lower()} ",
        "temAcolhimento": ACOLHIMENTO.search(pergunta) is not None,
        "comEmoji": com_emoji,
        "temaSensivel": sensivel,
        "semEmojiNoTemaSensivel": not (sensivel and com_emoji),
    }
