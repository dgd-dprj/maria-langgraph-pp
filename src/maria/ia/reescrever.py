"""Reescreve o TEXTO de uma pergunta sem mudar o que é perguntado, traduzido de
`src/ia/reescrever.ts`.

REESCREVER_IA está desligado por padrão desde 2026-08-31, depois de reescritas
com fraseado estranho em produção ("Essa é o Fulano presa?"). Religar com
REESCREVER_IA=true quando o prompt estiver mais confiável.
"""

from __future__ import annotations

import os
from typing import Any, NotRequired, TypedDict, cast

from maria.ia._estruturado import criar_modelo, definir_tokens, erro_para_log, esquema_objeto, invocar_estruturado
from maria.shared import _js
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger
from maria.shared.tokens_acumulados import TokensGastos

modelo = criar_modelo()

ESQUEMA_REESCRITA = esquema_objeto(
    {"pergunta": {"type": "string", "description": "a pergunta reescrita, curta e natural, em português do Brasil"}},
    ["pergunta"],
)

SISTEMA = """Você reescreve perguntas de um formulário jurídico da Defensoria Pública do RJ.
Regras: mantenha o MESMO significado — nunca invente informação nova, nunca mude o que está sendo pedido.
Tom acolhedor, claro, direto. Português do Brasil com emoji (se for possível). Uma frase só, terminada em "?".
Preserve a ordem natural das palavras perto de nomes próprios e do termo "pessoa presa" — nunca separe "presa"
do que ela qualifica (ex: NUNCA "Essa é o Fulano presa?"; prefira "Essa pessoa presa é o Fulano?" ou manter a
estrutura original). Reescreva o tom/fraseado, não a ordem das informações."""


class ResultadoReescrita(TypedDict):
    # Sem validação (#212): ausente se o modelo não devolver `pergunta`, e
    # NÃO o texto original.
    texto: NotRequired[Any]
    viaIA: bool
    tokensEntrada: NotRequired[int]
    tokensSaida: NotRequired[int]
    tokensTotal: NotRequired[int]


class CamposPerguntaPreparada(TypedDict):
    perguntaAtualTexto: Any
    perguntaAtualViaIA: bool
    # SEMPRE presente, com None quando não houve contagem: o resultado é
    # devolvido direto como atualização de estado pelos nós "preparar", e em
    # develop o `undefined` é gravado no canal (Object.entries mantém a chave;
    # LastValue guarda o valor). Omitir a chave manteria o valor da pergunta
    # anterior.
    perguntaAtualTokensTotal: int | None
    tokensGastos: TokensGastos


async def reescrever_pergunta(campo: str, objetivo_base: str) -> ResultadoReescrita:
    if os.environ.get("APP_ENV") == "test" or os.environ.get("REESCREVER_IA") != "true":
        return {"texto": objetivo_base, "viaIA": False}
    try:
        resultado = await invocar_estruturado(
            modelo, ESQUEMA_REESCRITA, SISTEMA, f"Campo: {campo}\nPergunta original: {objetivo_base}\nReescreva."
        )
        saida: dict[str, Any] = {}
        _js.definir(saida, "texto", _js.prop(resultado["parsed"], "pergunta"))
        saida["viaIA"] = True
        definir_tokens(saida, resultado["raw"])
        return cast(ResultadoReescrita, saida)
    except Exception as erro:
        # `campo` é o nome do campo, não o conteúdo.
        logger.error("[reescrever] falha ao reescrever, usando texto original", **contexto_atual(), campo=campo, err=erro_para_log(erro))
        return {"texto": objetivo_base, "viaIA": False}


async def preparar_pergunta(campo: str, texto_base: str) -> CamposPerguntaPreparada:
    """Nó "preparar" de cada pergunta dos fluxos: chama a IA 1x antes do nó que pausa.

    A IA não pode ficar no nó do interrupt(): o resume reexecuta o nó desde o
    início, e cada resposta da pessoa gastaria Bedrock de novo.
    """
    r = await reescrever_pergunta(campo, texto_base)
    tokens_total = r.get("tokensTotal")
    return {
        "perguntaAtualTexto": r.get("texto"),
        "perguntaAtualViaIA": r["viaIA"],
        "perguntaAtualTokensTotal": tokens_total,
        # `?? 0` de develop: só ausente vira zero.
        "tokensGastos": {
            "input": _js.coalesce(r.get("tokensEntrada"), 0),
            "output": _js.coalesce(r.get("tokensSaida"), 0),
            "total": _js.coalesce(tokens_total, 0),
        },
    }
