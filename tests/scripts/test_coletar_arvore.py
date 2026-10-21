"""`coletar_arvore_perguntas_verde.py` (spec 08, seção 3.1 e testes 2 e 3 da seção 6).

Develop não tem teste deste script. O Verde é falso (`httpx.MockTransport`) e as árvores são
inventadas; as stores ficam em memória (sem DATABASE_URL).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest

import coletar_arvore_perguntas_verde as crawler
from maria.fluxos import ID_VIOLENCIA_DOMESTICA
from maria.shared.fluxos_planejados_db import adicionar_planejado_de_teste
from maria.shared.perguntas_db import obter_perguntas_store

URL = "https://verde.teste/api/integra"
CONFIG = crawler.ConfigVerde(api_url=URL, jwt_token="token-falso", client_id="cliente-falso")

Resposta = tuple[int, Any] | Callable[[], Awaitable[tuple[int, Any]]]


def _no(pergunta: str, *respostas: tuple[int, str]) -> tuple[int, Any]:
    return 200, {"dados": {"pergunta": pergunta, "respostas": [{"id": i, "resposta": r} for i, r in respostas], "assuntoEncontrado": False}}


def _folha(id_assunto: Any, nome: str = "assunto inventado") -> tuple[int, Any]:
    return 200, {"dados": {"assuntoEncontrado": True, "idAssunto": id_assunto, "nomeAssunto": nome}}


def _detalhe(nome: Any = "Detalhe inventado", **extra: Any) -> tuple[int, Any]:
    return 200, {"dados": {"nome": nome, **extra}}


# Árvore inventada da categoria 9001.
ARVORE_9001: dict[str, Resposta] = {
    "/assunto/consultar-item-arvore?idCategoria=9001": _no("A SITUAÇÃO É URGENTE?", (11, "Sim"), (12, " não ")),
    "/assunto/consultar-item-arvore?idItemCategoria=11": _no("QUAL O TIPO?", (21, "Cível"), (22, "Criminal"), (23, "Outro")),
    "/assunto/consultar-item-arvore?idItemCategoria=21": _folha(501),
    "/assunto/consultar-item-arvore?idItemCategoria=22": _no("AVISO: PROCURE O ÓRGÃO RESPONSÁVEL"),
    "/assunto/consultar-item-arvore?idItemCategoria=23": _folha(502),
    "/assunto/consultar-item-arvore?idItemCategoria=12": _no("SIM OU TALVEZ?", (31, "SIM"), (32, "TALVEZ")),
    "/assunto/consultar-item-arvore?idItemCategoria=31": _folha(501),
    "/assunto/consultar-item-arvore?idItemCategoria=32": _folha(503, "nome da árvore"),
    "/assunto/501": _detalhe("Assunto 501", nomeMateria="Matéria", urgente=True),
    "/assunto/502": _detalhe("Assunto 502", documentosNecessarios=[{"id": 1, "nomeDocumento": "Documento", "basico": True}]),
    "/assunto/503": _detalhe(None),
}


class VerdeFalso:
    def __init__(self, rotas: dict[str, Resposta]) -> None:
        self.rotas = rotas
        self.chamadas: list[str] = []
        self.headers: list[httpx.Headers] = []

    async def __call__(self, requisicao: httpx.Request) -> httpx.Response:
        caminho = requisicao.url.raw_path.decode()
        assert caminho.startswith("/api/integra/")
        chave = caminho.removeprefix("/api/integra")
        self.chamadas.append(chave)
        self.headers.append(requisicao.headers)
        if chave not in self.rotas:
            return httpx.Response(404, json={"erro": "rota não existe no Verde falso"})
        resposta = self.rotas[chave]
        status, corpo = await resposta() if callable(resposta) else resposta
        if isinstance(corpo, bytes):
            return httpx.Response(status, content=corpo)
        return httpx.Response(status, content=json.dumps(corpo).encode())


@pytest.fixture(autouse=True)
async def ambiente(monkeypatch: pytest.MonkeyPatch, stores_limpas: None) -> AsyncIterator[None]:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(crawler, "PAUSA_ENTRE_CHAMADAS_MS", 0)
    yield


async def _crawlear(rotas: dict[str, Resposta], flow_id: str = "flow-a", categoria: int = 9001, nome: str = "categoria a") -> VerdeFalso:
    verde = VerdeFalso(rotas)
    async with httpx.AsyncClient(transport=httpx.MockTransport(verde)) as cliente:
        await crawler.crawlear_flow(cliente, CONFIG, flow_id, categoria, nome)
    return verde


async def _falha(rotas: dict[str, Resposta]) -> str:
    with pytest.raises(Exception) as erro:
        await _crawlear(rotas)
    return str(erro.value)


async def test_arvore_inteira(capsys: pytest.CaptureFixture[str]) -> None:
    verde = await _crawlear(ARVORE_9001)
    store = await obter_perguntas_store()
    perguntas = await store.listar_perguntas_por_flow("flow-a")

    # Pré-ordem; `ordem` só conta pergunta.
    assert [(p["textoPergunta"], p["ordem"], p["tipo"]) for p in perguntas] == [
        ("A SITUAÇÃO É URGENTE?", 0, "sim_nao"),
        ("QUAL O TIPO?", 1, "opcoes"),
        ("AVISO: PROCURE O ÓRGÃO RESPONSÁVEL", 2, "texto"),
        ("SIM OU TALVEZ?", 3, "opcoes"),
    ]
    assert [(p["idItemCategoria"], p["veioDaRespostaId"]) for p in perguntas] == [(None, None), (11, 11), (22, 22), (12, 12)]
    assert perguntas[0]["opcoes"] == [{"id": 11, "resposta": "Sim"}, {"id": 12, "resposta": " não "}]
    assert perguntas[2]["opcoes"] == []

    assuntos = await store.listar_assuntos_por_flow("flow-a")
    assert [(a["idAssunto"], a["veioDaRespostaId"], a["nome"]) for a in assuntos] == [
        (501, 21, "Assunto 501"),
        (502, 23, "Assunto 502"),
        (501, 31, "Assunto 501"),
        (503, 32, "nome da árvore"),  # `detalhe.nome ?? dados.nomeAssunto`: null cai no nome da árvore
    ]
    assert assuntos[0]["nomeMateria"] == "Matéria" and assuntos[0]["urgente"] is True and assuntos[0]["plantao"] is False
    assert "nomeMateria" not in assuntos[1] and assuntos[1]["documentosNecessarios"][0]["nomeDocumento"] == "Documento"

    assert capsys.readouterr().out == "[categoria a] 4 pergunta(s), 4 assunto(s)\n"
    assert verde.chamadas[:3] == [
        "/assunto/consultar-item-arvore?idCategoria=9001",
        "/assunto/consultar-item-arvore?idItemCategoria=11",
        "/assunto/consultar-item-arvore?idItemCategoria=21",
    ]
    assert verde.headers[0]["authorization"] == "Bearer token-falso"
    assert verde.headers[0]["x-client-id"] == "cliente-falso"
    assert verde.headers[0]["accept"] == "application/json"


async def test_nova_rodada_limpa_a_categoria_antes() -> None:
    await _crawlear(ARVORE_9001)
    await _crawlear(ARVORE_9001)
    store = await obter_perguntas_store()
    assert len(await store.listar_perguntas_por_flow("flow-a")) == 4
    assert len(await store.listar_assuntos_por_flow("flow-a")) == 4


async def test_assunto_compartilhado_entre_categorias() -> None:
    outra: dict[str, Resposta] = {
        "/assunto/consultar-item-arvore?idCategoria=9002": _no("OUTRA?", (41, "x")),
        "/assunto/consultar-item-arvore?idItemCategoria=41": _folha(501),
        "/assunto/501": _detalhe("Assunto 501, versão nova"),
    }
    await _crawlear(ARVORE_9001)
    await _crawlear(outra, "flow-b", 9002, "categoria b")
    store = await obter_perguntas_store()
    # Upsert do detalhe por idAssunto: a outra categoria vê a versão nova; cada flow tem a própria ligação.
    assert [a["nome"] for a in await store.listar_assuntos_por_flow("flow-a") if a["idAssunto"] == 501] == ["Assunto 501, versão nova"] * 2
    assert len(await store.listar_assuntos_por_flow("flow-b")) == 1


async def test_pausa_antes_de_cada_chamada_inclusive_a_primeira(monkeypatch: pytest.MonkeyPatch) -> None:
    pausas: list[int] = []

    async def registrar(ms: int) -> None:
        pausas.append(ms)

    monkeypatch.setattr(crawler, "PAUSA_ENTRE_CHAMADAS_MS", 120)
    monkeypatch.setattr(crawler, "pausa", registrar)
    verde = await _crawlear(ARVORE_9001)
    assert pausas == [120] * len(verde.chamadas)


@pytest.mark.parametrize(
    ("respostas", "tipo"),
    [
        ([" sim ", "não"], "sim_nao"),
        (["NÃO", "SIM"], "sim_nao"),
        (["SIM", "SIM"], "opcoes"),
        (["SIM", "NÃO", "TALVEZ"], "opcoes"),
        (["SIM", "NAO"], "opcoes"),
        (["﻿SIM", "NÃO"], "sim_nao"),  # o trim do JS tira o BOM
        (["\x1cSIM", "NÃO"], "opcoes"),  # e não tira o separador \x1c
    ],
)
def test_tipo_da_pergunta(respostas: list[str], tipo: str) -> None:
    assert crawler.tipo_da_pergunta([{"id": i, "resposta": r} for i, r in enumerate(respostas)]) == tipo


@pytest.mark.parametrize(
    ("respostas", "mensagem"),
    [
        ([{"id": 1, "resposta": 7}], "r.resposta.trim is not a function"),
        ([{"id": 1}], "Cannot read properties of undefined (reading 'trim')"),
        ([None], "Cannot read properties of null (reading 'resposta')"),
        ({"id": 1}, "respostas.map is not a function"),
    ],
)
def test_tipo_da_pergunta_com_dado_fora_do_formato(respostas: Any, mensagem: str) -> None:
    with pytest.raises(Exception, match=mensagem.replace("(", r"\(").replace(")", r"\)")):
        crawler.tipo_da_pergunta(respostas)


async def test_falha_http_na_raiz() -> None:
    assert await _falha({"/assunto/consultar-item-arvore?idCategoria=9001": (500, {})}) == (
        'consultar-item-arvore HTTP 500 ({"idCategoria":9001})'
    )


async def test_falha_sem_dados() -> None:
    rotas = {**ARVORE_9001, "/assunto/consultar-item-arvore?idItemCategoria=12": (200, {"dados": None})}
    assert await _falha(rotas) == "consultar-item-arvore sem 'dados' ({\"idItemCategoria\":12})"


async def test_falha_http_no_detalhe() -> None:
    rotas: dict[str, Resposta] = {**ARVORE_9001, "/assunto/502": (404, {})}
    assert await _falha(rotas) == "GET /assunto/502 HTTP 404"


async def test_falha_detalhe_sem_dados() -> None:
    rotas = {**ARVORE_9001, "/assunto/502": (200, {"dados": ""})}
    assert await _falha(rotas) == "GET /assunto/502 sem 'dados'"


async def test_assunto_sem_id() -> None:
    rotas = {**ARVORE_9001, "/assunto/consultar-item-arvore?idItemCategoria=21": (200, {"dados": {"assuntoEncontrado": True}})}
    assert await _falha(rotas) == 'assuntoEncontrado sem idAssunto em "categoria a"'


async def test_assunto_com_id_null_vira_get_assunto_null() -> None:
    rotas = {**ARVORE_9001, "/assunto/consultar-item-arvore?idItemCategoria=21": _folha(None)}
    with pytest.raises(Exception, match=r"^GET /assunto/null HTTP 404$"):
        verde = VerdeFalso(rotas)
        async with httpx.AsyncClient(transport=httpx.MockTransport(verde)) as cliente:
            await crawler.crawlear_flow(cliente, CONFIG, "flow-a", 9001, "categoria a")
    assert verde.chamadas[-1] == "/assunto/null"


async def test_assunto_encontrado_como_texto_false_conta_como_verdadeiro() -> None:
    folha: Resposta = (200, {"dados": {"assuntoEncontrado": "false", "idAssunto": 502}})
    rotas = {**ARVORE_9001, "/assunto/consultar-item-arvore?idItemCategoria=22": folha}
    await _crawlear(rotas)
    store = await obter_perguntas_store()
    assert len(await store.listar_assuntos_por_flow("flow-a")) == 5


@pytest.mark.parametrize("valor", [[], {}])
async def test_assunto_encontrado_lista_ou_objeto_vazio_conta_como_verdadeiro(valor: Any) -> None:
    # Verdade do JS: `[]` e `{}` são verdadeiros; no Python, bool([]) e bool({}) são falsos.
    folha: Resposta = (200, {"dados": {"assuntoEncontrado": valor, "idAssunto": 502}})
    rotas: dict[str, Resposta] = {**ARVORE_9001, "/assunto/consultar-item-arvore?idItemCategoria=22": folha}
    await _crawlear(rotas)
    store = await obter_perguntas_store()
    assert len(await store.listar_assuntos_por_flow("flow-a")) == 5


async def test_pergunta_lista_vazia_conta_como_pergunta() -> None:
    # `if (!pergunta)` com `pergunta: []`: no JS a lista vazia é verdadeira, e o nó é gravado.
    no_lista: Resposta = (200, {"dados": {"pergunta": [], "respostas": []}})
    rotas: dict[str, Resposta] = {**ARVORE_9001, "/assunto/consultar-item-arvore?idItemCategoria=22": no_lista}
    await _crawlear(rotas)
    store = await obter_perguntas_store()
    textos: list[Any] = [p["textoPergunta"] for p in await store.listar_perguntas_por_flow("flow-a")]
    assert textos.count([]) == 1


async def test_profundidade_no_limite_passa() -> None:
    # Profundidade 12 é permitida (`profundidade > 12` só falha na 13ª).
    rotas: dict[str, Resposta] = {"/assunto/consultar-item-arvore?idCategoria=9001": _no("NÍVEL 0", (1, "segue"))}
    for nivel in range(1, 12):
        rotas[f"/assunto/consultar-item-arvore?idItemCategoria={nivel}"] = _no(f"NÍVEL {nivel}", (nivel + 1, "segue"))
    rotas["/assunto/consultar-item-arvore?idItemCategoria=12"] = _folha(502)
    rotas["/assunto/502"] = _detalhe("Assunto 502")
    await _crawlear(rotas)
    store = await obter_perguntas_store()
    assert len(await store.listar_perguntas_por_flow("flow-a")) == 12


async def test_no_sem_pergunta() -> None:
    rotas = {**ARVORE_9001, "/assunto/consultar-item-arvore?idItemCategoria=22": (200, {"dados": {"pergunta": "", "respostas": []}})}
    assert await _falha(rotas) == 'nó sem pergunta e sem assuntoEncontrado em "categoria a" ({"idItemCategoria":22})'


async def test_respostas_null_vira_no_texto() -> None:
    rotas = {**ARVORE_9001, "/assunto/consultar-item-arvore?idItemCategoria=22": (200, {"dados": {"pergunta": "AVISO", "respostas": None}})}
    await _crawlear(rotas)
    store = await obter_perguntas_store()
    aviso = [p for p in await store.listar_perguntas_por_flow("flow-a") if p["textoPergunta"] == "AVISO"]
    assert aviso[0]["tipo"] == "texto" and aviso[0]["opcoes"] == []


async def test_profundidade_maxima() -> None:
    # Cadeia de 14 níveis: o nível 13 passa do limite de 12.
    rotas: dict[str, Resposta] = {"/assunto/consultar-item-arvore?idCategoria=9001": _no("NÍVEL 0", (1, "segue"))}
    for nivel in range(1, 14):
        rotas[f"/assunto/consultar-item-arvore?idItemCategoria={nivel}"] = _no(f"NÍVEL {nivel}", (nivel + 1, "segue"))
    mensagem = await _falha(rotas)
    assert mensagem == 'profundidade máxima (12) excedida em "categoria a" — árvore maior que o esperado ou loop'


async def test_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def lento() -> tuple[int, Any]:
        await asyncio.sleep(1)
        return _no("NUNCA CHEGA")

    monkeypatch.setattr(crawler, "TIMEOUT_MS", 50)
    assert await _falha({"/assunto/consultar-item-arvore?idCategoria=9001": lento}) == "The operation was aborted due to timeout"


async def test_falha_de_rede() -> None:
    async def recusar(requisicao: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusada", request=requisicao)

    async with httpx.AsyncClient(transport=httpx.MockTransport(recusar)) as cliente:
        with pytest.raises(crawler.ErroJs) as erro:
            await crawler.crawlear_flow(cliente, CONFIG, "flow-a", 9001, "categoria a")
    assert str(erro.value) == "fetch failed"


async def test_url_do_verde_vazia() -> None:
    config = crawler.ConfigVerde(api_url="", jwt_token="t", client_id="")
    async with httpx.AsyncClient(transport=httpx.MockTransport(VerdeFalso({}))) as cliente:
        with pytest.raises(crawler.ErroJs) as erro:
            await crawler.crawlear_flow(cliente, config, "flow-a", 9001, "categoria a")
    assert str(erro.value) == "Failed to parse URL from /assunto/consultar-item-arvore?idCategoria=9001"


async def test_json_invalido_falha_a_categoria() -> None:
    # D-4: a mensagem é a do Python, e não a do V8.
    await _falha({"/assunto/consultar-item-arvore?idCategoria=9001": (200, b"{nao e json")})


def test_url_vazia_no_ambiente_nao_cai_no_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERDE_API_URL", "")
    assert crawler.config_do_ambiente().api_url == ""
    monkeypatch.delenv("VERDE_API_URL")
    assert crawler.config_do_ambiente().api_url == "https://homologacao.verde.rj.def.br/api/integra"


ARVORE_VD: dict[str, Resposta] = {
    "/assunto/consultar-item-arvore?idCategoria=10113": _no("É COM VOCÊ?", (71, "x")),
    "/assunto/consultar-item-arvore?idItemCategoria=71": _folha(701),
    "/assunto/701": _detalhe("Assunto VD"),
}


async def _coletar(rotas: dict[str, Resposta]) -> VerdeFalso:
    await adicionar_planejado_de_teste(
        {"id": "planejado-a", "nome": "categoria a", "descricao": "d", "idCategoriaAssuntoVerde": 9001, "palavrasChave": []}
    )
    await adicionar_planejado_de_teste(
        {"id": "planejado-b", "nome": "categoria b", "descricao": "d", "idCategoriaAssuntoVerde": 9002, "palavrasChave": []}
    )
    verde = VerdeFalso(rotas)
    async with httpx.AsyncClient(transport=httpx.MockTransport(verde)) as cliente:
        await crawler.coletar(cliente, CONFIG)
    return verde


async def test_coletar_segue_depois_de_categoria_com_falha(capsys: pytest.CaptureFixture[str]) -> None:
    rotas: dict[str, Resposta] = {**ARVORE_VD, **ARVORE_9001, "/assunto/consultar-item-arvore?idCategoria=9002": (503, {})}
    verde = await _coletar(rotas)
    captura = capsys.readouterr()
    assert captura.out.splitlines() == [
        "crawl iniciado — 3 categorias",
        "[violencia-domestica] 1 pergunta(s), 1 assunto(s)",
        "[categoria a] 4 pergunta(s), 4 assunto(s)",
        "crawl concluído: 5 pergunta(s), 5 assunto(s), 1 falha(s) em 3 categorias",
        "categorias com falha (revisar manualmente — pode ser categoria sem árvore no Verde): categoria b",
    ]
    assert captura.err.splitlines() == ['[categoria b] falhou: consultar-item-arvore HTTP 503 ({"idCategoria":9002})']
    # Ordem dos alvos: violência doméstica primeiro, depois os planejados.
    assert verde.chamadas[0] == "/assunto/consultar-item-arvore?idCategoria=10113"


async def test_b1_falha_na_raiz_apaga_a_arvore_anterior() -> None:
    # Achado #251, reproduzido de propósito: a régua é develop.
    await _coletar({**ARVORE_VD, **ARVORE_9001, **_categoria_b_boa()})
    store = await obter_perguntas_store()
    assert len(await store.listar_perguntas_por_flow("planejado-b")) == 1

    await _coletar({**ARVORE_VD, **ARVORE_9001, "/assunto/consultar-item-arvore?idCategoria=9002": (500, {})})
    assert await store.listar_perguntas_por_flow("planejado-b") == []
    assert await store.listar_assuntos_por_flow("planejado-b") == []


async def test_b1_falha_no_meio_deixa_a_arvore_parcial() -> None:
    rotas: dict[str, Resposta] = {**ARVORE_VD, **ARVORE_9001, "/assunto/consultar-item-arvore?idItemCategoria=12": (500, {})}
    rotas.update(_categoria_b_boa())
    await _coletar(rotas)
    store = await obter_perguntas_store()
    perguntas = await store.listar_perguntas_por_flow("planejado-a")
    assert [p["ordem"] for p in perguntas] == [0, 1, 2]  # a raiz e o ramo 11 ficaram; o ramo 12 não
    assert len(await store.listar_assuntos_por_flow("planejado-a")) == 2


def _categoria_b_boa() -> dict[str, Resposta]:
    return {
        "/assunto/consultar-item-arvore?idCategoria=9002": _no("B?", (81, "x")),
        "/assunto/consultar-item-arvore?idItemCategoria=81": _folha(801),
        "/assunto/801": _detalhe("Assunto B"),
    }


def _checkpointer_falso(monkeypatch: pytest.MonkeyPatch, ordem: list[str], erro: Exception | None = None) -> None:
    async def inicializar() -> None:
        ordem.append("checkpointer")
        if erro is not None:
            raise erro

    async def fechar() -> None:
        ordem.append("fechar checkpointer")

    monkeypatch.setattr(crawler, "inicializar_checkpointer", inicializar)
    monkeypatch.setattr(crawler, "fechar_checkpointer", fechar)


def test_sem_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    ordem: list[str] = []
    _checkpointer_falso(monkeypatch, ordem)
    monkeypatch.setenv("VERDE_JWT_TOKEN", "")
    monkeypatch.setenv("DATABASE_URL", "postgresql://ninguem@127.0.0.1:1/nada")
    assert crawler.main() == 1
    assert ordem == ["checkpointer", "fechar checkpointer"]
    captura = capsys.readouterr()
    assert captura.out == ""
    assert captura.err.splitlines()[0] == (
        "crawl falhou: Error: VERDE_JWT_TOKEN obrigatório — este script fala com o Verde de verdade, sem modo mock"
    )


def test_sem_database_url(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("VERDE_JWT_TOKEN", "t")
    monkeypatch.setenv("DATABASE_URL", "")
    assert crawler.main() == 1
    captura = capsys.readouterr()
    # B5: o checkpointer nasce antes das guardas do script e loga o aviso do MemorySaver.
    (linha,) = captura.out.splitlines()
    assert json.loads(linha)["msg"] == "[checkpoint] DATABASE_URL ausente — usando MemorySaver (não persiste)"
    assert captura.err.splitlines()[0] == (
        "crawl falhou: Error: DATABASE_URL obrigatório — sem isso o resultado do crawl não fica salvo em lugar nenhum"
    )


def test_falha_do_checkpointer_vem_antes_da_guarda_do_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # B5: em develop, a importação dos fluxos falha antes de o main() checar o token.
    ordem: list[str] = []
    _checkpointer_falso(monkeypatch, ordem, ConnectionRefusedError("connect ECONNREFUSED 127.0.0.1:1"))
    monkeypatch.setenv("VERDE_JWT_TOKEN", "")
    with pytest.raises(ConnectionRefusedError):
        crawler.main()
    assert ordem == ["checkpointer"]
    assert "crawl falhou" not in capsys.readouterr().err


def test_fluxo_de_violencia_domestica_tem_categoria() -> None:
    from maria.fluxos import fluxos_por_id

    assert fluxos_por_id[ID_VIOLENCIA_DOMESTICA].id_categoria_assunto_verde == 10113
