"""Tradução de `src/shared/tokensAcumulados.test.ts` (3 testes), mais o default.

Testa o reducer com valores fixos num mini-grafo com o MESMO canal usado nos
estados dos fluxos. `marcador` existe para que algum canal seja escrito nos
testes que não mexem em `tokensGastos`.
"""

from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from maria.shared.tokens_acumulados import CanalTokensGastos, TokensGastos, TokensGastosZerados, somar_tokens


class _Estado(TypedDict):
    tokensGastos: NotRequired[CanalTokensGastos]
    marcador: NotRequired[bool]


def test_reducer_soma_os_deltas_de_varios_nos_campo_a_campo() -> None:
    grafo = (
        StateGraph(_Estado)
        .add_node("a", lambda _s: {"tokensGastos": {"input": 80, "output": 20, "total": 100}})
        .add_node("b", lambda _s: {"tokensGastos": {"input": 40, "output": 10, "total": 50}})
        .add_edge(START, "a")
        .add_edge("a", "b")
        .add_edge("b", END)
        .compile()
    )
    resultado = grafo.invoke({})
    assert resultado["tokensGastos"] == {"input": 120, "output": 30, "total": 150}


def test_reducer_soma_em_cima_de_um_valor_inicial_passado_no_invoke() -> None:
    grafo = (
        StateGraph(_Estado)
        .add_node("a", lambda _s: {"tokensGastos": {"input": 15, "output": 5, "total": 20}})
        .add_edge(START, "a")
        .add_edge("a", END)
        .compile()
    )
    resultado = grafo.invoke({"tokensGastos": {"input": 3000, "output": 1324, "total": 4324}})
    assert resultado["tokensGastos"] == {"input": 3015, "output": 1329, "total": 4344}


def test_sem_nenhum_delta_o_total_e_zero_zero_zero() -> None:
    # Ponto de atenção 2 da #208: com TypedDict puro, o canal começaria em {}.
    grafo = (
        StateGraph(_Estado)
        .add_node("semDelta", lambda _s: {"marcador": True})
        .add_edge(START, "semDelta")
        .add_edge("semDelta", END)
        .compile()
    )
    resultado = grafo.invoke({})
    assert resultado["tokensGastos"] == {"input": 0, "output": 0, "total": 0}


def test_valor_inicial_do_canal() -> None:
    assert TokensGastosZerados() == {"input": 0, "output": 0, "total": 0}


def test_somar_tokens_aceita_atual_vazio_ou_none() -> None:
    delta: TokensGastos = {"input": 1, "output": 2, "total": 3}
    assert somar_tokens(None, delta) == delta
    assert somar_tokens({}, delta) == delta
