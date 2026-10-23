"""Um fluxo mínimo no molde, para a verificação por mutação do teste de
conformidade (#323): `montar()` devolve o fluxo certo, e `montar(defeito)` o
mesmo fluxo com o defeito que quebra uma regra.

Uma pergunta sim/não (com o par que prepara e pede), um relato classificado
pela IA entre opções fixas, um subgrafo e uma consulta de pessoa ao Verde.
Termina concluído ou em atendimento humano com motivo. Fica nos testes e nunca
entra no registro de fluxos.
"""

from __future__ import annotations

import os
from collections.abc import Hashable
from types import ModuleType
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from maria.fluxos import FluxoConfig
from maria.fluxos._fabrica import FabricaGrafo
from maria.ia.classificar import classificar_entre_opcoes
from maria.ia.reescrever import preparar_pergunta
from maria.integracoes.verde import consultar_pessoa_por_cpf
from maria.shared import _js
from maria.shared.respostas import resposta_eh_sim
from maria.shared.tokens_acumulados import CanalTokensGastos
from maria.shared.types import DadosPessoa
from tests.fluxos.conformidade import FluxoSobConferencia, Roteiro

ID_DE_TESTE = "5f0c6a8e-2d1b-4c3a-9e7f-1a2b3c4d5e6f"
TEXTO_QUER_AJUDA = "Você quer ajuda com o caso de teste?"
TEXTO_RELATO = "Conte em poucas palavras o que aconteceu."
CATEGORIAS = ["moradia", "saude", "outro"]
CPF_DE_TESTE = "12345678909"
MENSAGEM_CONCLUIDO = "Pronto, caso de teste concluído."
MENSAGEM_HANDOFF = "Vou passar o caso de teste para uma pessoa da equipe."

ROTEIROS = (Roteiro({}, ((r"aconteceu", "fiquei sem casa"),)), Roteiro({"querAjuda": True}, ((r"aconteceu", "fiquei sem casa"),)))

# Defeito -> regra que ele quebra.
DEFEITOS = {
    "sem statusFinal": "A1",
    "sem tokensGastos": "A2",
    "sem mensagemFinal": "A3",
    "pausa sem tipo": "A4",
    "sim/não sem opções": "A5",
    "sim/não sem resposta_eh_sim": "A5",
    "pergunta sem o nó que prepara": "A6",
    "prepara e não pede": "A7",
    "compila na importação": "A8",
    "api sem MENSAGEM_HANDOFF": "A9",
    "descrição vazia": "A10",
    "encaminha sem motivo": "A11",
    "subgrafo com persistência própria": "A12",
    "subgrafo sem canal em comum": "A12",
    "IA sem conferir a lista": "A13",
    "falha de infra vira não encontrado": "A14",
    "nó que não chega ao fim": "fim",
    "metadados fora do contrato": "contrato",
}

Motivo = Literal["nao_quis_ajuda", "cpf_nao_encontrado", "falha_infra_verde"]
_CANAIS: dict[str, Any] = {
    "querAjuda": bool | None,
    "relato": str | None,
    "categoria": str | None,
    "dadosPessoa": DadosPessoa | None,
    "statusFinal": Literal["concluido", "handoff_humano"] | None,
    "motivoHandoff": Motivo | None,
    "mensagemFinal": str | None,
    "perguntaAtualTexto": str | None,
    "perguntaAtualViaIA": bool | None,
    "perguntaAtualTokensTotal": int | None,
    "tokensGastos": CanalTokensGastos,
}
_SEM_CANAL = {"sem statusFinal": "statusFinal", "sem tokensGastos": "tokensGastos", "sem mensagemFinal": "mensagemFinal"}


def _subgrafo(defeito: str | None) -> Any:
    canal = "outroCanal" if defeito == "subgrafo sem canal em comum" else "relato"
    estado = TypedDict("EstadoDoSubgrafoDeTeste", {canal: str | None}, total=False)  # type: ignore[misc]
    construtor = StateGraph(estado)
    construtor.add_node("aparar", lambda s: {canal: _js.coalesce(s.get(canal), "").strip()})
    construtor.add_edge(START, "aparar")
    construtor.add_edge("aparar", END)
    return construtor.compile(checkpointer=InMemorySaver() if defeito == "subgrafo com persistência própria" else None)


def montar(defeito: str | None = None) -> FluxoSobConferencia:
    assert defeito is None or defeito in DEFEITOS, defeito
    canais = {k: v for k, v in _CANAIS.items() if k != _SEM_CANAL.get(defeito or "")}
    estado = TypedDict("EstadoDeTeste", canais, total=False)  # type: ignore[misc]

    # Os dois pulam quando a Tykhe já mandou a resposta em `dadosConhecidos`.
    async def preparar_quer_ajuda(state: Any) -> dict[str, Any]:
        if "querAjuda" in state and defeito != "prepara e não pede":
            return {}
        return dict(await preparar_pergunta("querAjuda", TEXTO_QUER_AJUDA))

    async def pedir_quer_ajuda(state: Any) -> dict[str, Any]:
        if "querAjuda" in state:
            return {}
        pausa: dict[str, Any] = {
            "pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_QUER_AJUDA),
            "tipo": "sim_nao",
            "opcoes": ["Sim", "Não"],
        }
        if defeito == "pausa sem tipo":
            del pausa["tipo"]
        if defeito == "sim/não sem opções":
            del pausa["opcoes"]
        resposta: str = interrupt(pausa)
        return {"querAjuda": resposta == "Sim" if defeito == "sim/não sem resposta_eh_sim" else resposta_eh_sim(resposta)}

    async def preparar_relato(state: Any) -> dict[str, Any]:
        return dict(await preparar_pergunta("relato", TEXTO_RELATO))

    async def pedir_relato(state: Any) -> dict[str, Any]:
        resposta: str = interrupt({"pergunta": _js.coalesce(state.get("perguntaAtualTexto"), TEXTO_RELATO), "tipo": "texto"})
        if os.environ.get("APP_ENV") == "test":
            return {"relato": resposta, "categoria": "outro"}
        escolha = (await classificar_entre_opcoes(resposta, "Classifique o relato.", CATEGORIAS)).get("escolhaId")
        if defeito != "IA sem conferir a lista" and escolha not in CATEGORIAS:
            escolha = "outro"
        return {"relato": resposta, "categoria": escolha}

    async def consultar_pessoa(state: Any) -> dict[str, Any]:
        return {"dadosPessoa": await consultar_pessoa_por_cpf(CPF_DE_TESTE)}

    def depois_da_consulta(state: Any) -> str:
        dados = state.get("dadosPessoa") or {}
        if dados.get("falhaInfra") and defeito != "falha de infra vira não encontrado":
            return "falhaInfra"
        return "concluir" if dados.get("encontrado") else "naoEncontrado"

    def fim(status: str, motivo: str | None = None) -> Any:
        async def no(state: Any) -> dict[str, Any]:
            saida: dict[str, Any] = {} if defeito == "sem statusFinal" else {"statusFinal": status}
            if motivo is not None and not (defeito == "encaminha sem motivo" and motivo == "nao_quis_ajuda"):
                saida["motivoHandoff"] = motivo
            return saida

        return no

    construtor = StateGraph(estado)
    construtor.add_node("prepararQuerAjuda", preparar_quer_ajuda)
    construtor.add_node("pedirQuerAjuda", pedir_quer_ajuda)
    construtor.add_node("naoQuisAjuda", fim("handoff_humano", "nao_quis_ajuda"))
    construtor.add_node("prepararRelato", preparar_relato)
    construtor.add_node("pedirRelato", pedir_relato)
    construtor.add_node("aparar", _subgrafo(defeito))
    construtor.add_node("consultarPessoa", consultar_pessoa)
    construtor.add_node("falhaInfra", fim("handoff_humano", "falha_infra_verde"))
    construtor.add_node("naoEncontrado", fim("handoff_humano", "cpf_nao_encontrado"))
    construtor.add_node("concluir", fim("concluido"))
    if defeito == "pergunta sem o nó que prepara":
        construtor.add_edge(START, "pedirQuerAjuda")
    else:
        construtor.add_edge(START, "prepararQuerAjuda")
    construtor.add_edge("prepararQuerAjuda", "pedirQuerAjuda")
    destinos: dict[Hashable, str] = {"sim": "prepararRelato", "nao": "naoQuisAjuda"}
    if defeito == "nó que não chega ao fim":
        construtor.add_node("laco", lambda s: {})
        construtor.add_edge("laco", "laco")
        destinos["nunca"] = "laco"
    construtor.add_conditional_edges("pedirQuerAjuda", lambda s: "sim" if s.get("querAjuda") else "nao", destinos)
    construtor.add_edge("prepararRelato", "pedirRelato")
    construtor.add_edge("pedirRelato", "aparar")
    construtor.add_edge("aparar", "consultarPessoa")
    construtor.add_conditional_edges("consultarPessoa", depois_da_consulta, ["falhaInfra", "naoEncontrado", "concluir"])
    for terminal in ("naoQuisAjuda", "falhaInfra", "naoEncontrado", "concluir"):
        construtor.add_edge(terminal, END)

    modulo_grafo = ModuleType("maria.fluxos.de_teste.graph")
    fabrica = FabricaGrafo(construtor)
    modulo_grafo._fabrica = fabrica  # type: ignore[attr-defined]
    modulo_grafo.obter_grafo = fabrica.obter  # type: ignore[attr-defined]
    if defeito == "compila na importação":
        modulo_grafo.grafo = construtor.compile()  # type: ignore[attr-defined]

    def extrair_metadados_de_teste(valores: Any) -> Any:
        metadados = {"querAjuda": valores.get("querAjuda"), "categoria": valores.get("categoria")}
        return list(metadados.items()) if defeito == "metadados fora do contrato" else metadados

    modulo_api = ModuleType("maria.fluxos.de_teste.api")
    modulo_api.extrair_metadados_de_teste = extrair_metadados_de_teste  # type: ignore[attr-defined]
    modulo_api.MENSAGEM_CONCLUIDO = MENSAGEM_CONCLUIDO  # type: ignore[attr-defined]
    if defeito != "api sem MENSAGEM_HANDOFF":
        modulo_api.MENSAGEM_HANDOFF = MENSAGEM_HANDOFF  # type: ignore[attr-defined]

    config = FluxoConfig(
        nome="fluxo-de-teste",
        descricao="" if defeito == "descrição vazia" else "Fluxo mínimo do teste de conformidade.",
        obter_grafo=fabrica.obter,
        extrair_metadados=extrair_metadados_de_teste,
        mensagem_concluido=MENSAGEM_CONCLUIDO,
        mensagem_handoff=MENSAGEM_HANDOFF,
    )
    return FluxoSobConferencia("fluxo-de-teste", ID_DE_TESTE, config, modulo_grafo, modulo_api, ROTEIROS)
