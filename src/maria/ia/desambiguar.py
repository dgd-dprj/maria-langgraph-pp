"""Gera 1 pergunta que ajuda a distinguir entre candidatos ambíguos (issue #28),
traduzido de `src/ia/desambiguar.ts`.

As OPÇÕES (nome de cada fluxo) são montadas pelo chamador; só o texto da
pergunta vem da IA, para nunca inventar uma opção que não existe no catálogo.
"""

from __future__ import annotations

import os
import re
from typing import Any, NotRequired, TypedDict, cast

from maria.ia._estruturado import avisar_saida_invalida, criar_modelo, definir_tokens, erro_para_log, esquema_objeto, invocar_estruturado
from maria.ia.ajuste_qwen import SUFIXO_DESAMBIGUAR, SUFIXO_TOM_DESAMBIGUAR, com_ajuste_qwen
from maria.ia.tom import medir_tom
from maria.shared import _js
from maria.shared._js import AUSENTE
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger

modelo = criar_modelo()

TEXTO_FALLBACK = "Pra te ajudar melhor, qual dessas opções descreve o que você precisa?"

ESQUEMA_PERGUNTA = esquema_objeto(
    {
        "pergunta": {
            "type": "string",
            "description": (
                "pergunta curta, natural, em português do Brasil, que ajuda a pessoa a escolher entre as opções"
                " — sem citar nomes técnicos/internos"
            ),
        }
    },
    ["pergunta"],
)


class CandidatoParaDesambiguar(TypedDict):
    id: str
    nome: str
    descricao: str


# #508: temas sensíveis, em que a pergunta nunca leva emoji (decisão da Nicole, 2026-11-16). Pelo nome e pela
# descrição da opção no catálogo ("pessoa-presa", "violencia-domestica", "prisão em flagrante"), e não pelo id:
# importar os ids de maria.fluxos aqui traria os grafos dos fluxos para dentro da IA. \b evita "empresa".
TEMA_SENSIVEL = re.compile(r"\b(pessoa[- ]presa|pres[oa]s?|pris[aã]o|viol[eê]ncia[- ]dom[eé]stica)\b", re.IGNORECASE)
# Emoji e o que vem colado nele: seletor de variação (FE0F), junção (200D) e tom de pele.
EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️‍\U0001f3fb-\U0001f3ff]+")


def tem_tema_sensivel(candidatos: list[CandidatoParaDesambiguar]) -> bool:
    return any(TEMA_SENSIVEL.search(f"{c['nome']} {c['descricao']}") for c in candidatos)


def sem_emoji(texto: str) -> str:
    """O texto sem emoji, com os espaços que sobram arrumados ("Certo 😊, você…" → "Certo, você…")."""
    limpo = EMOJI.sub("", texto)
    limpo = re.sub(r"\s+([,.!?;:])", r"\1", limpo)
    return re.sub(r"\s{2,}", " ", limpo).strip()


def montar_sistema(candidatos: list[CandidatoParaDesambiguar]) -> str:
    """O prompt de sistema da desambiguação. Com o Qwen, ganha as regras dele: citar as opções em dúvida
    (2026-11-12) e o tom acolhedor (#508). Com outro modelo, fica idêntico ao de antes."""
    opcoes = "\n".join(f"- {c['nome']}: {c['descricao']}" for c in candidatos)
    sistema = f"""Você ajuda a Defensoria Pública do RJ a esclarecer qual tipo de atendimento uma pessoa precisa, quando o relato dela bate com mais de uma opção.
Opções possíveis:
{opcoes}
Gere 1 pergunta curta, natural, em português, que ajude a pessoa a escolher entre essas opções — foque na diferença prática entre elas, sem citar nomes técnicos/internos."""  # noqa: E501
    return com_ajuste_qwen(sistema, SUFIXO_DESAMBIGUAR + SUFIXO_TOM_DESAMBIGUAR)


class ResultadoDesambiguacao(TypedDict):
    # Sem validação (#212): pode vir de outro tipo, ou ausente.
    pergunta: NotRequired[Any]
    viaIA: bool
    tokensEntrada: NotRequired[int]
    tokensSaida: NotRequired[int]
    tokensTotal: NotRequired[int]


async def gerar_pergunta_desambiguacao(relato: str, candidatos: list[CandidatoParaDesambiguar]) -> ResultadoDesambiguacao:
    # Em develop, este guard fica FORA do try.
    if os.environ.get("APP_ENV") == "test":
        return {"pergunta": TEXTO_FALLBACK, "viaIA": False}
    try:
        # A Converse API exige que a conversa comece com "user" (achado ao
        # vivo em 2026-09-11): o relato vai como mensagem do usuário.
        resultado = await invocar_estruturado(modelo, ESQUEMA_PERGUNTA, montar_sistema(candidatos), relato)
        saida: dict[str, Any] = {}
        pergunta = _js.prop(resultado["parsed"], "pergunta")
        # #212: pergunta que não é texto (ou vazia) não vai para a pessoa; vale o texto genérico das falhas, e os
        # tokens continuam contados, porque a chamada aconteceu.
        if not isinstance(pergunta, str) or not pergunta.strip():
            avisar_saida_invalida("gerar_pergunta_desambiguacao", "chave_ausente" if pergunta is AUSENTE else "tipo_errado")
            pergunta = TEXTO_FALLBACK
        sensivel = tem_tema_sensivel(candidatos)
        # #508: nos temas sensíveis, a pergunta sai sem emoji, mesmo que o modelo ponha um.
        emoji_tirado = False
        if isinstance(pergunta, str) and sensivel:
            limpa = sem_emoji(pergunta)
            emoji_tirado = limpa != pergunta
            pergunta = limpa
        if isinstance(pergunta, str):
            # #508 (2026-11-17): o tom da pergunta que a pessoa recebe, só em números, para o Visor. Sem o texto.
            # Sim e não vão como 1 e 0: o Logs Insights do Visor soma os campos direto (`sum(temAcolhimento)`).
            # Cada campo vai por nome: o contrato do Visor (scripts/extrair_contrato_da_maria.py) lê os nomes daqui.
            tom = {campo: int(valor) for campo, valor in medir_tom(pergunta, sensivel).items()}
            logger.info(
                "[desambiguar] tom da pergunta",
                **contexto_atual(),
                evento="desambiguacao_tom",
                modelo=os.environ.get("BEDROCK_MODEL_ID", ""),
                emojiTirado=int(emoji_tirado),
                palavras=tom["palavras"],
                ateLimiteDePalavras=tom["ateLimiteDePalavras"],
                terminaEmPergunta=tom["terminaEmPergunta"],
                semTermoTecnico=tom["semTermoTecnico"],
                ofereceAlternativas=tom["ofereceAlternativas"],
                temAcolhimento=tom["temAcolhimento"],
                comEmoji=tom["comEmoji"],
                temaSensivel=tom["temaSensivel"],
                semEmojiNoTemaSensivel=tom["semEmojiNoTemaSensivel"],
            )
        _js.definir(saida, "pergunta", pergunta)
        saida["viaIA"] = True
        definir_tokens(saida, resultado["raw"])
        return cast(ResultadoDesambiguacao, saida)
    except Exception as erro:
        logger.error("[desambiguar] falha ao gerar pergunta, usando texto genérico", **contexto_atual(), err=erro_para_log(erro))
        return {"pergunta": TEXTO_FALLBACK, "viaIA": False}
