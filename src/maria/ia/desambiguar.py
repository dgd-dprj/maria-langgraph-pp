"""Gera 1 pergunta que ajuda a distinguir entre candidatos ambíguos (issue #28),
traduzido de `src/ia/desambiguar.ts`.

As OPÇÕES (nome de cada fluxo) são montadas pelo chamador; só o texto da
pergunta vem da IA, para nunca inventar uma opção que não existe no catálogo.
"""

from __future__ import annotations

import os
from typing import Any, NotRequired, TypedDict, cast

from maria.ia._estruturado import criar_modelo, definir_tokens, erro_para_log, esquema_objeto, invocar_estruturado
from maria.shared import _js
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
        opcoes = "\n".join(f"- {c['nome']}: {c['descricao']}" for c in candidatos)
        sistema = f"""Você ajuda a Defensoria Pública do RJ a esclarecer qual tipo de atendimento uma pessoa precisa, quando o relato dela bate com mais de uma opção.
Opções possíveis:
{opcoes}
Gere 1 pergunta curta, natural, em português, que ajude a pessoa a escolher entre essas opções — foque na diferença prática entre elas, sem citar nomes técnicos/internos."""  # noqa: E501
        # A Converse API exige que a conversa comece com "user" (achado ao
        # vivo em 2026-09-11): o relato vai como mensagem do usuário.
        resultado = await invocar_estruturado(modelo, ESQUEMA_PERGUNTA, sistema, relato)
        saida: dict[str, Any] = {}
        _js.definir(saida, "pergunta", _js.prop(resultado["parsed"], "pergunta"))
        saida["viaIA"] = True
        definir_tokens(saida, resultado["raw"])
        return cast(ResultadoDesambiguacao, saida)
    except Exception as erro:
        logger.error("[desambiguar] falha ao gerar pergunta, usando texto genérico", **contexto_atual(), err=erro_para_log(erro))
        return {"pergunta": TEXTO_FALLBACK, "viaIA": False}
