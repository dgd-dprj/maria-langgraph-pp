"""Atalho por palavra antes da IA (#553): a mensagem inteira é uma expressão curta que nomeia um destino só.

Achado da #553 (2026-11-25): a pessoa escreveu só "preso" e a conversa foi para "outros" da Tykhe. A IA do
multi-fluxo (release) leu a palavra sozinha como "prisão citada sem pedido" e devolveu nenhuma opção. Medido no
Bedrock (26/11): com o Qwen3 VL 235B, "preso." errou 5 de 5, "cadeia" 4 de 5, "detento" 3 de 5; com o Ministral
14B, todas as palavras soltas erraram. A produção (Haiku) acertou, mas o atalho vale nos dois caminhos: é 0 token e
não depende do modelo.

Segue o modelo do `parentesco_pela_resposta` (#212): lê pelas palavras o que não pede interpretação. Só a mensagem
inteira conta, depois de tirar caixa, acento, pontuação e espaços a mais: "Preso!" e "lei Maria da Penha" ativam;
"meu marido foi preso e quero me divorciar" continua com a IA, que separa o pedido do contexto.

Decisão da Nicole (26/11): pessoa presa com "preso", "presa", "cadeia", "detento" e "presidiário" (feminino e
plural); e atalho também para os outros destinos, com expressões curtas. Ficam FORA as que pedem a pergunta da
Maria para decidir: "cirurgia" (plano ou SUS, #386 e #419), "exame" (pode ser de DNA, processo novo), "audiência"
(pode ser de custódia), "processo" e "pensão" (novo ou andamento), "obrigado" (agradecimento no meio do relato).
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA


class Atalho(NamedTuple):
    destino: str  # flowId da Maria ou id de tipo da Tykhe (`tykhe:<tipoCaso>`)
    motivo: str  # vai no log, sem a mensagem
    expressoes: frozenset[str]  # sem acento, minúsculas, palavras separadas por um espaço


def _expressoes(*palavras: str) -> frozenset[str]:
    return frozenset(palavras)


ATALHOS: tuple[Atalho, ...] = (
    Atalho(
        ID_PESSOA_PRESA,
        "palavra_de_prisao",
        _expressoes(
            "preso", "presa", "presos", "presas",
            "cadeia",
            "detento", "detenta", "detentos", "detentas",
            "presidiario", "presidiaria", "presidiarios", "presidiarias",
        ),
    ),
    Atalho(
        ID_VIOLENCIA_DOMESTICA,
        "palavra_de_violencia_domestica",
        _expressoes(
            "violencia domestica",
            "maria da penha", "lei maria da penha",
            "medida protetiva", "medidas protetivas",
            "agressao", "agressoes", "agredida", "agressor",
            "espancada",
        ),
    ),
    Atalho(
        "tykhe:saude",
        "palavra_de_saude",
        _expressoes(
            "remedio", "remedios", "medicamento", "medicamentos",
            "internacao", "uti", "cti", "vaga na uti", "vaga de uti",
            "fralda", "fraldas", "leite especial", "cadeira de rodas",
            "erro medico", "prontuario", "prontuario medico",
        ),
    ),
    Atalho(
        "tykhe:novo-processo",
        "palavra_de_novo_processo",
        _expressoes(
            "novo processo", "processo novo", "abrir processo", "abrir um processo", "iniciar processo",
            "divorcio", "inventario", "pensao alimenticia",
        ),
    ),
    Atalho(
        "tykhe:andamento-processo",
        "palavra_de_andamento",
        _expressoes(
            "andamento", "andamento do processo", "andamento do meu processo", "andamento processo",
            "numero do processo", "consultar processo",
        ),
    ),
    Atalho(
        "tykhe:agendamentos",
        "palavra_de_agendamento",
        _expressoes(
            "agendamento", "agendamentos", "meu agendamento", "meus agendamentos",
            "remarcar", "remarcar agendamento", "cancelar agendamento",
        ),
    ),
    Atalho(
        "tykhe:ajuda-app",
        "palavra_de_aplicativo",
        _expressoes("aplicativo", "app", "senha", "esqueci a senha", "esqueci minha senha", "erro no app", "erro no aplicativo"),
    ),
    Atalho(
        "tykhe:sair",
        "palavra_de_sair",
        _expressoes("sair", "tchau", "encerrar", "finalizar", "nao quero mais"),
    ),
)  # fmt: skip

# O motivo de pessoa presa, usado nos testes e na documentação.
MOTIVO_PESSOA_PRESA = ATALHOS[0].motivo

_PALAVRAS = re.compile(r"[a-z0-9]+")
# A maior expressão da lista tem 4 palavras; mensagem maior nem é comparada.
MAXIMO_DE_PALAVRAS = max(len(e.split()) for a in ATALHOS for e in a.expressoes)


def expressao_normalizada(mensagem: str) -> str:
    """As palavras da mensagem, sem acento e em minúscula, separadas por um espaço.

    Pontuação, emoji e espaços a mais não contam ("Preso!", " lei  Maria da Penha. "). Hífen separa palavras."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", mensagem.lower()) if unicodedata.category(c) != "Mn")
    return " ".join(_PALAVRAS.findall(sem_acento))


def atalho_pela_palavra(mensagem: object) -> tuple[str, str] | None:
    """O destino e o motivo do atalho, ou None para a IA decidir."""
    if not isinstance(mensagem, str):
        return None
    expressao = expressao_normalizada(mensagem)
    if not expressao or len(expressao.split()) > MAXIMO_DE_PALAVRAS:
        return None
    for atalho in ATALHOS:
        if expressao in atalho.expressoes:
            return atalho.destino, atalho.motivo
    return None
