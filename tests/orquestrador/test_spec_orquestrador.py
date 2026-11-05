"""Testes novos da spec do módulo orquestrador (spec 06, seção 6).

Os comportamentos de develop marcados (lido) na spec vêm da leitura do código
@ 1157a6d e são confirmados na conferência diferencial antes do PR. Quando o
Python diverge de propósito (D-1), o teste fixa o comportamento escolhido e
cita o motivo.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from langgraph.types import Command

from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA
from maria.ia.desambiguar import TEXTO_FALLBACK
from maria.orquestrador import graph
from maria.orquestrador.graph import (
    LIMITE_RODADAS,
    TEXTO_PEDIR_DESAMBIGUACAO_PADRAO,
    buscar_pergunta_real_compartilhada,
    mesmo_conjunto_de_opcoes,
    obter_grafo,
)
from maria.shared.perguntas_db import PerguntaArvore
from tests.fluxos.conftest import novo_config, pergunta
from tests.ia.conftest import BedrockFalso, ferramenta
from tests.orquestrador.conftest import Modelo

DOIS = [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA]
TOKENS = {"tokensEntrada": 11, "tokensSaida": 7, "tokensTotal": 18}


class Conversa:
    def __init__(self) -> None:
        self.grafo = obter_grafo()
        self.config = novo_config("teste-orq-spec")

    async def iniciar(self, mensagem: str = "relato") -> dict[str, Any]:
        r: dict[str, Any] = await self.grafo.ainvoke({"mensagem": mensagem}, self.config)
        return r

    async def responder(self, *respostas: str) -> dict[str, Any]:
        r: dict[str, Any] = {}
        for resposta in respostas:
            r = await self.grafo.ainvoke(Command(resume=resposta), self.config)
        return r

    async def estado(self) -> dict[str, Any]:
        return dict((await self.grafo.aget_state(self.config)).values)


def _raiz(texto: str, *respostas: str) -> PerguntaArvore:
    return {
        "id": "p",
        "flowId": "f",
        "idItemCategoria": None,
        "veioDaRespostaId": None,
        "textoPergunta": texto,
        "tipo": "opcoes",
        "opcoes": [{"id": i, "resposta": r} for i, r in enumerate(respostas)],
        "ordem": 0,
    }


@dataclass
class StoreFalsa:
    raizes: dict[str, PerguntaArvore | None] = field(default_factory=dict)
    consultas: list[str] = field(default_factory=list)

    async def buscar_pergunta_raiz(self, flow_id: str) -> PerguntaArvore | None:
        self.consultas.append(flow_id)
        return self.raizes.get(flow_id)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> StoreFalsa:
    falsa = StoreFalsa()

    async def obter() -> StoreFalsa:
        return falsa

    monkeypatch.setattr(graph, "obter_perguntas_store", obter)
    return falsa


# ---- 1. topologia ---------------------------------------------------------------------


def test_1_topologia_igual_a_de_develop() -> None:
    desenho = obter_grafo().get_graph()
    assert set(desenho.nodes) == {
        "__start__",
        "classificar",
        "identificado",
        "naoIdentificado",
        "prepararPerguntaDesambiguacao",
        "pedirDesambiguacao",
        "__end__",
    }
    assert {(a.source, a.target, a.conditional) for a in desenho.edges} == {
        ("__start__", "classificar", False),
        ("classificar", "naoIdentificado", True),
        ("classificar", "identificado", True),
        ("classificar", "prepararPerguntaDesambiguacao", True),
        ("prepararPerguntaDesambiguacao", "pedirDesambiguacao", False),
        ("pedirDesambiguacao", "classificar", False),
        ("identificado", "__end__", False),
        ("naoIdentificado", "__end__", False),
    }


def test_1_constantes() -> None:
    # CANDIDATOS_MAXIMOS era 10 em develop; 15 desde a #353.
    assert (graph.CANDIDATOS_MAXIMOS, graph.LIMITE_RODADAS, graph.LIMITE_RODADAS_SUMARIZACAO) == (15, 5, 3)


# ---- 2. interrupt ---------------------------------------------------------------------


async def test_2_payload_do_interrupt_sem_opcoes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", ",".join(DOIS))
    r = await Conversa().iniciar()
    # APP_ENV=test: a desambiguação devolve o TEXTO_FALLBACK do ia (achado A1).
    assert pergunta(r) == {"pergunta": TEXTO_FALLBACK, "tipo": "texto"}
    assert "opcoes" not in (pergunta(r) or {})


async def test_2_pergunta_ausente_na_saida_da_ia_usa_o_texto_padrao(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    modelo.perguntas = [{"viaIA": True}]  # sem a chave `pergunta`: o undefined de develop
    c = Conversa()
    r = await c.iniciar()
    assert pergunta(r) == {"pergunta": TEXTO_PEDIR_DESAMBIGUACAO_PADRAO, "tipo": "texto"}
    estado = await c.estado()
    assert "perguntaAtualTexto" in estado and estado["perguntaAtualTexto"] is None


async def test_2_pergunta_null_tambem_usa_o_texto_padrao(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    modelo.perguntas = [{"pergunta": None, "viaIA": True}]
    r = await Conversa().iniciar()
    assert pergunta(r) == {"pergunta": TEXTO_PEDIR_DESAMBIGUACAO_PADRAO, "tipo": "texto"}


# ---- 3. regra de estado (tabela 0.2) --------------------------------------------------


async def test_3_pergunta_do_banco_nao_apaga_os_tokens_do_classificar(modelo: Modelo, store: StoreFalsa) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True, **TOKENS}]
    for flow_id in DOIS:
        store.raizes[flow_id] = _raiz("O ATENDIMENTO É PARA:", "Mim", "Outra pessoa")
    c = Conversa()
    r = await c.iniciar()
    assert pergunta(r) == {"pergunta": "O ATENDIMENTO É PARA:", "tipo": "texto"}
    estado = await c.estado()
    assert estado["tokensGastosRodada"] == 18
    assert estado["tokensGastosConversa"] == {"input": 11, "output": 7, "total": 18}
    assert modelo.textos_desambiguados == []


async def test_3_tokens_da_rodada_somam_classificacao_e_desambiguacao(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True, **TOKENS}]
    modelo.perguntas = [{"pergunta": "P?", "viaIA": True, "tokensEntrada": 1, "tokensSaida": 2, "tokensTotal": 3}]
    c = Conversa()
    await c.iniciar()
    estado = await c.estado()
    assert estado["tokensGastosRodada"] == 21
    assert estado["tokensGastosConversa"] == {"input": 12, "output": 9, "total": 21}


async def test_3_tokens_da_rodada_ficam_none_sem_nenhuma_chamada_real(monkeypatch: pytest.MonkeyPatch) -> None:
    # APP_ENV=test: nem a classificação nem a desambiguação devolvem tokens.
    # undefined + undefined = undefined (issue #34), e não 0.
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", ",".join(DOIS))
    c = Conversa()
    await c.iniciar()
    estado = await c.estado()
    assert "tokensGastosRodada" in estado and estado["tokensGastosRodada"] is None
    assert estado["tokensGastosConversa"] == {"input": 0, "output": 0, "total": 0}


async def test_3_retrieval_so_na_primeira_rodada(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    c = Conversa()
    await c.iniciar()
    await c.responder("mais detalhes", "ainda mais")
    assert modelo.retrievals == 1


async def test_3_candidatos_vazios_terminam_sem_novo_retrieval(modelo: Modelo) -> None:
    # `candidatosRestantes ?? buscar(...)`: a lista vazia não é nullish. O grafo
    # termina antes, mas o nó, chamado direto, não pode refazer o retrieval.
    modelo.classificacoes = [{"ids": [], "viaIA": True}]
    await graph.classificar({"mensagem": "x", "candidatosRestantes": []})
    assert modelo.retrievals == 0


# ---- 4. roteamento --------------------------------------------------------------------


async def test_4_nenhum_candidato_e_nao_identificado(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": [], "viaIA": True}]
    r = await Conversa().iniciar()
    assert r["statusFinal"] == "nao_identificado"
    assert "flowIdEscolhido" not in r


async def test_4_um_candidato_e_identificado(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": [ID_VIOLENCIA_DOMESTICA], "viaIA": True}]
    r = await Conversa().iniciar()
    assert (r["statusFinal"], r["flowIdEscolhido"]) == ("identificado", ID_VIOLENCIA_DOMESTICA)


async def test_4_tipo_da_tykhe_tambem_e_identificado(modelo: Modelo) -> None:
    # O desfecho "redirecionado" é da rota (api); o grafo só identifica.
    modelo.classificacoes = [{"ids": ["tykhe:saude"], "viaIA": True}]
    r = await Conversa().iniciar()
    assert (r["statusFinal"], r["flowIdEscolhido"]) == ("identificado", "tykhe:saude")


async def test_4_ambiguidade_ate_a_quinta_rodada_e_depois_nao_identificado(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    c = Conversa()
    await c.iniciar()
    r = await c.responder("1", "2", "3", "4")
    assert pergunta(r) is not None, "na 4ª resposta ainda pergunta"
    r = await c.responder("5")
    assert r["rodada"] == LIMITE_RODADAS
    assert r["statusFinal"] == "nao_identificado"


async def test_4_ambiguidade_que_converge_vira_identificado(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}, {"ids": [ID_PESSOA_PRESA], "viaIA": True}]
    c = Conversa()
    await c.iniciar()
    r = await c.responder("é sobre meu filho preso")
    assert (r["statusFinal"], r["flowIdEscolhido"]) == ("identificado", ID_PESSOA_PRESA)


# ---- 5. sumarização -------------------------------------------------------------------


async def test_5_primeira_passagem_pelo_limite_resume_o_bruto_e_as_seguintes_resumo_mais_ultima(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    modelo.resumos = [{"resumo": "R1", "viaIA": True}, {"resumo": "R2", "viaIA": True}]
    c = Conversa()
    await c.iniciar("relato")
    await c.responder("r1", "r2")
    assert modelo.textos_sumarizados == []
    await c.responder("r3")
    assert modelo.textos_sumarizados == ["relato\nr1\nr2"], "1ª vez: o bruto, sem a resposta atual"
    assert modelo.textos_classificados[-1] == "R1\nr3"
    await c.responder("r4")
    assert modelo.textos_sumarizados[-1] == "R1\nr3", "depois: resumo anterior + última resposta"
    assert modelo.textos_classificados[-1] == "R2\nr4"
    estado = await c.estado()
    assert estado["mensagem"] == "relato\nr1\nr2\nr3\nr4"


async def test_5_resumo_vazio_e_resumo_valido(modelo: Modelo) -> None:
    # `=== undefined`: "" é resumo. Truthiness trataria como "não sumarizou".
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    modelo.resumos = [{"resumo": "", "viaIA": True}]
    c = Conversa()
    await c.iniciar("relato")
    await c.responder("r1", "r2", "r3")
    assert modelo.textos_classificados[-1] == "\nr3"


async def test_5_resumo_ausente_volta_ao_bruto(modelo: Modelo) -> None:
    # Sem a chave `resumo`: develop grava undefined, e a classificação volta ao bruto.
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    modelo.resumos = [{"viaIA": True}]
    c = Conversa()
    await c.iniciar("relato")
    await c.responder("r1", "r2", "r3")
    assert modelo.textos_classificados[-1] == "relato\nr1\nr2\nr3"


async def test_5_resumo_null_volta_ao_bruto_divergencia_aceita_d1(modelo: Modelo) -> None:
    # D-1 (spec 06): develop guardaria null e mandaria "null\nr3", perdendo o
    # histórico. O Python trata null como undefined e manda o bruto.
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    modelo.resumos = [{"resumo": None, "viaIA": True}]
    c = Conversa()
    await c.iniciar("relato")
    await c.responder("r1", "r2", "r3")
    assert modelo.textos_classificados[-1] == "relato\nr1\nr2\nr3"


# ---- 6. saída do modelo sem validação (#212) -----------------------------------------


@pytest.mark.parametrize(
    ("saida", "mensagem"),
    [
        ({"viaIA": True}, "Cannot read properties of undefined (reading 'map')"),
        ({"ids": None, "viaIA": True}, "Cannot read properties of null (reading 'map')"),
        ({"ids": "abc", "viaIA": True}, "ids.map is not a function"),
        ({"ids": {ID_PESSOA_PRESA: 1}, "viaIA": True}, "ids.map is not a function"),
        ({"ids": 5, "viaIA": True}, "ids.map is not a function"),
        ({"ids": True, "viaIA": True}, "ids.map is not a function"),
    ],
)
async def test_6_ids_que_nao_e_lista_lanca_typeerror(modelo: Modelo, saida: dict[str, Any], mensagem: str) -> None:
    modelo.classificacoes = [saida]
    with pytest.raises(TypeError) as erro:
        await Conversa().iniciar()
    assert str(erro.value) == mensagem


async def test_6_ids_string_com_id_valido_nao_e_iterada(modelo: Modelo) -> None:
    # Iterar a string seria "dar sorte" com um caractere; develop lança antes.
    modelo.classificacoes = [{"ids": ID_PESSOA_PRESA, "viaIA": True}]
    with pytest.raises(TypeError):
        await Conversa().iniciar()


async def test_6_item_que_nao_e_string_e_filtrado_sem_lancar(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": [["x"], {"a": 1}, 5, None, True, ID_PESSOA_PRESA, "inventado"], "viaIA": True}]
    r = await Conversa().iniciar()
    assert (r["statusFinal"], r["flowIdEscolhido"]) == ("identificado", ID_PESSOA_PRESA)


async def test_6_id_repetido_vira_desambiguacao_achado_a3(modelo: Modelo) -> None:
    modelo.classificacoes = [{"ids": [ID_PESSOA_PRESA, ID_PESSOA_PRESA], "viaIA": True}]
    c = Conversa()
    r = await c.iniciar()
    assert pergunta(r) is not None
    assert [x["id"] for x in (await c.estado())["candidatosRestantes"]] == [ID_PESSOA_PRESA, ID_PESSOA_PRESA]


@pytest.mark.parametrize(
    ("resumo", "texto"),
    [(5, "5\nr3"), (True, "true\nr3"), ({"a": 1}, "[object Object]\nr3"), (["a", None, "b"], "a,,b\nr3"), (1.0, "1\nr3")],
)
async def test_6_resumo_de_outro_tipo_sai_como_template_literal(modelo: Modelo, resumo: Any, texto: str) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    modelo.resumos = [{"resumo": resumo, "viaIA": True}]
    c = Conversa()
    await c.iniciar("relato")
    await c.responder("r1", "r2", "r3")
    assert modelo.textos_classificados[-1] == texto


@pytest.mark.parametrize("valor", [5, {"a": 1}, ["x"], True])
async def test_6_pergunta_de_outro_tipo_vai_crua_no_interrupt(modelo: Modelo, valor: Any) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    modelo.perguntas = [{"pergunta": valor, "viaIA": True}]
    r = await Conversa().iniciar()
    assert pergunta(r) == {"pergunta": valor, "tipo": "texto"}


async def test_6_pergunta_vazia_vai_vazia_no_interrupt(modelo: Modelo) -> None:
    # `??` não troca "" pelo texto padrão.
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    modelo.perguntas = [{"pergunta": "", "viaIA": True}]
    r = await Conversa().iniciar()
    assert pergunta(r) == {"pergunta": "", "tipo": "texto"}


async def test_6_ids_string_pelo_bedrock_falso_chega_ao_grafo_e_lanca(bedrock: BedrockFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    # De ponta a ponta: o ia não valida (#212) e repassa a string; o grafo lança
    # como o `ids.map` de develop. O retrieval fica fora (chamaria o embedding).
    async def pool(mensagem: str, k: int, catalogo: Any) -> Any:
        return list(catalogo)[:k]

    monkeypatch.setattr(graph, "buscar_candidatos", pool)
    bedrock.roteirizar(ferramenta({"idsPlausiveis": ID_PESSOA_PRESA}))
    with pytest.raises(TypeError) as erro:
        await Conversa().iniciar()
    # O LangGraph anexa uma nota ("During task with name ..."); o str() fica igual ao de develop.
    assert str(erro.value) == "ids.map is not a function"
    assert len(bedrock.requisicoes) == 1


# ---- 7. pergunta real compartilhada (#32) --------------------------------------------


async def test_7_mesmas_opcoes_em_ordem_e_caixa_diferentes_usa_o_banco(modelo: Modelo, store: StoreFalsa) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    store.raizes[ID_PESSOA_PRESA] = _raiz("Para quem?", "Mim", "﻿Outra pessoa ")
    store.raizes[ID_VIOLENCIA_DOMESTICA] = _raiz("Para quem?", "OUTRA PESSOA", "mim")
    r = await Conversa().iniciar()
    assert pergunta(r) == {"pergunta": "Para quem?", "tipo": "texto"}
    assert modelo.textos_desambiguados == []


@pytest.mark.parametrize(
    ("raiz_vd"),
    [
        _raiz("Para quem?", "Mim", "Terceiro"),  # opções diferentes
        _raiz("Para quem?", "Mim"),  # quantidade diferente
        _raiz("Para QUEM?", "Mim", "Outra pessoa"),  # texto diferente (sem normalizar)
        None,  # sem pergunta raiz
    ],
)
async def test_7_sem_pergunta_comum_usa_a_ia(modelo: Modelo, store: StoreFalsa, raiz_vd: PerguntaArvore | None) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    store.raizes[ID_PESSOA_PRESA] = _raiz("Para quem?", "Mim", "Outra pessoa")
    store.raizes[ID_VIOLENCIA_DOMESTICA] = raiz_vd
    r = await Conversa().iniciar()
    assert pergunta(r) == {"pergunta": "Pergunta da IA?", "tipo": "texto"}


async def test_7_primeiro_sem_raiz_usa_a_ia(modelo: Modelo, store: StoreFalsa) -> None:
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    store.raizes[ID_VIOLENCIA_DOMESTICA] = _raiz("Para quem?", "Mim")
    r = await Conversa().iniciar()
    assert pergunta(r) == {"pergunta": "Pergunta da IA?", "tipo": "texto"}


async def test_7_texto_vazio_no_banco_cai_para_a_ia(modelo: Modelo, store: StoreFalsa) -> None:
    # `if (perguntaDoBanco)`: "" é falso.
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    for flow_id in DOIS:
        store.raizes[flow_id] = _raiz("", "Mim")
    r = await Conversa().iniciar()
    assert pergunta(r) == {"pergunta": "Pergunta da IA?", "tipo": "texto"}


async def test_7_menos_de_dois_candidatos_nem_consulta_o_banco(store: StoreFalsa) -> None:
    assert await buscar_pergunta_real_compartilhada([{"id": ID_PESSOA_PRESA, "nome": "n", "descricao": "d"}]) is None
    assert store.consultas == []


async def test_7_dez_candidatos_consultados_juntos(store: StoreFalsa) -> None:
    candidatos = [{"id": f"f{i}", "nome": "n", "descricao": "d"} for i in range(10)]
    for c in candidatos:
        store.raizes[c["id"]] = _raiz("Mesma?", "Sim", "Não")
    assert await buscar_pergunta_real_compartilhada(candidatos) == "Mesma?"  # type: ignore[arg-type]
    assert store.consultas == [c["id"] for c in candidatos]


def test_7_ordem_fora_do_bmp_nao_muda_o_resultado() -> None:
    # JS ordena por code units UTF-16 ("\U0001d538" < "￿"); Python por code
    # points (o contrário). Comparar multiconjuntos dá o mesmo resultado.
    a = [{"id": 1, "resposta": "\U0001d538"}, {"id": 2, "resposta": "￿"}]
    b = [{"id": 1, "resposta": "￿"}, {"id": 2, "resposta": "\U0001d538"}]
    assert mesmo_conjunto_de_opcoes(a, b)  # type: ignore[arg-type]
    assert not mesmo_conjunto_de_opcoes(a, [{"id": 1, "resposta": "￿"}, {"id": 2, "resposta": "￿"}])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("resposta", "mensagem"),
    [
        (None, "Cannot read properties of null (reading 'trim')"),
        (5, "o.resposta.trim is not a function"),
    ],
)
async def test_7_resposta_do_banco_que_nao_e_texto_lanca_como_develop(
    modelo: Modelo, store: StoreFalsa, resposta: Any, mensagem: str
) -> None:
    # Achado na varredura (conferência diferencial): o Python dava AttributeError
    # no strip; develop lança TypeError no .trim(). Confirmado em develop @ 1157a6d.
    modelo.classificacoes = [{"ids": DOIS, "viaIA": True}]
    for flow_id in DOIS:
        r = _raiz("Q?", "a")
        r["opcoes"][0]["resposta"] = resposta
        store.raizes[flow_id] = r
    with pytest.raises(TypeError) as erro:
        await Conversa().iniciar()
    assert str(erro.value) == mensagem


async def test_relato_vazio_nao_chama_o_bedrock_e_nao_identifica(bedrock: BedrockFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    # Achado na conferência diferencial: o SDK JS recusa a mensagem humana vazia
    # antes de enviar, e a classificação cai no fallback (nenhum candidato).
    async def pool(mensagem: str, k: int, catalogo: Any) -> Any:
        return list(catalogo)[:k]

    monkeypatch.setattr(graph, "buscar_candidatos", pool)
    bedrock.roteirizar(ferramenta({"idsPlausiveis": [ID_PESSOA_PRESA]}))
    r = await Conversa().iniciar("")
    assert r["statusFinal"] == "nao_identificado"
    assert bedrock.requisicoes == []


def test_7_trim_do_js_e_nao_o_strip() -> None:
    # trim() do JS remove U+FEFF e NÃO remove \x1c; strip() faz o contrário.
    assert mesmo_conjunto_de_opcoes([{"id": 1, "resposta": "﻿Sim"}], [{"id": 1, "resposta": "sim"}])
    assert not mesmo_conjunto_de_opcoes([{"id": 1, "resposta": "Sim\x1c"}], [{"id": 1, "resposta": "sim"}])
