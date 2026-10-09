from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from maria.shared.contexto import Contexto, contexto_atual


def test_fora_de_um_run_devolve_vazio_sem_lancar() -> None:
    assert contexto_atual() == {}


class _Estado(TypedDict):
    contexto: NotRequired[Contexto]


def _grafo():
    return StateGraph(_Estado).add_node("no", lambda _s: {"contexto": contexto_atual()}).add_edge(START, "no").add_edge("no", END).compile()


def test_dentro_de_um_run_le_thread_id_como_chatId_e_fluxoId() -> None:
    resultado = _grafo().invoke({}, {"configurable": {"thread_id": "chat-1", "fluxoId": "fluxo-x"}})
    assert resultado["contexto"] == {"chatId": "chat-1", "fluxoId": "fluxo-x"}


def test_dentro_de_um_run_sem_fluxoId_omite_a_chave() -> None:
    resultado = _grafo().invoke({}, {"configurable": {"thread_id": "chat-2"}})
    assert resultado["contexto"] == {"chatId": "chat-2"}


async def test_dentro_de_um_run_assincrono() -> None:
    async def no_assincrono(_estado):
        return {"contexto": contexto_atual()}

    grafo = StateGraph(_Estado).add_node("no", no_assincrono).add_edge(START, "no").add_edge("no", END).compile()
    resultado = await grafo.ainvoke({}, {"configurable": {"thread_id": "chat-3", "fluxoId": "f"}})
    assert resultado["contexto"] == {"chatId": "chat-3", "fluxoId": "f"}
