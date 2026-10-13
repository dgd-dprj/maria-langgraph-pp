"""Contexto de correlação do run atual do grafo, para os logs.

`get_config()` do LangGraph lê o contexto do run corrente, então dá para
chamar de qualquer ponto da execução de um nó (inclusive de dentro de
`integracoes/verde.py` ou `ia/*.py`) sem receber a config como parâmetro.

Diferença para develop: em JS, `getConfig()` devolve `undefined` fora de um
run; em Python, `get_config()` lança `RuntimeError`. Aqui a exceção é
absorvida para manter o contrato de nunca lançar: fora de um run (por exemplo,
no log de inicialização do checkpointer) o resultado vem sem as chaves.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.config import get_config


class Contexto(TypedDict, total=False):
    chatId: str
    fluxoId: str


def contexto_atual() -> Contexto:
    try:
        config = get_config()
    except RuntimeError:
        return {}
    configurable = config.get("configurable") or {}
    contexto: Contexto = {}
    thread_id = configurable.get("thread_id")
    if thread_id is not None:
        contexto["chatId"] = thread_id
    fluxo_id = configurable.get("fluxoId")
    if fluxo_id is not None:
        contexto["fluxoId"] = fluxo_id
    return contexto
