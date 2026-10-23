"""Conferência de um fluxo contra as 14 regras do molde (#323).

`conferir` devolve as falhas de cada regra; quem decide o que vale é
`test_conformidade.py`, com as exceções registradas. Parte das regras é lida
sem executar o fluxo (A1, A2, A3, A8, A9, A10, A12 e "todo nó chega ao fim").
As outras saem de passeios pelo grafo, sem IA real e com o Verde simulado:

- **passeio estrutural** (`APP_ENV=test`, Verde em modo mock): responde "Sim"
  ou "Não" a toda pergunta sim/não e um texto fixo às de texto. Confere A1, A4,
  A5, A11 e o esquema do contrato a cada resposta montada;
- **passeio com IA simulada** (reescrita e extração ligadas, `invocar_estruturado`
  trocado): cada pergunta reescrita ganha uma marca `[n]`, o que mostra qual nó
  preparou o texto (A6 e A7), e toda saída de lista fechada vem com um valor
  inventado, que não pode chegar ao contrato (A13);
- **passeio com o Verde falhando** numa chamada de cada vez, com 503, tempo
  esgotado e 401, pelo caminho real de `integracoes/verde.py` sobre um
  transporte falso (A14).

O passeio não percorre todos os caminhos: só os das respostas que ele dá.
"""

from __future__ import annotations

import inspect
import re
import sys
import typing
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from maria.api.atendimentos import extrair_interrupt, montar_resposta_atendimento
from maria.api.esquemas import RESPOSTA_ATENDIMENTO, Schema
from maria.api.serializacao import serializar
from maria.fluxos import FluxoConfig
from maria.fluxos._fabrica import FabricaGrafo
from maria.ia import _estruturado
from maria.integracoes import verde
from maria.shared._js import AUSENTE
from maria.shared.tokens_acumulados import CanalTokensGastos
from tests.fluxos.conftest import Fluxo
from tests.integracoes.conftest import URL_VERDE, TransporteFalso

REGRAS = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12", "A13", "A14", "fim", "contrato")
STATUS_FINAIS = frozenset({"concluido", "handoff_humano"})
TIPOS_DE_PERGUNTA = frozenset({"texto", "sim_nao"})
OPCOES_SIM_NAO = ["Sim", "Não"]
MOTIVO_FALHA_INFRA = "falha_infra_verde"
INVENTADO = "valor-inventado-pela-ia"
# O grafo padrão não tem id próprio: a resposta montada usa um uuid fictício.
ID_FICTICIO = "00000000-0000-4000-8000-000000000000"
LIMITE_DE_PASSOS = 60
_KEBAB = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_MARCA = re.compile(r"\[(\d+)\] ")

# As chamadas ao Verde: as funções públicas de `integracoes/verde.py`, menos o
# retry que todas usam. Uma chamada nova entra sozinha na A14.
CHAMADAS_VERDE = tuple(
    nome
    for nome, funcao in vars(verde).items()
    if inspect.iscoroutinefunction(funcao)
    and funcao.__module__ == verde.__name__
    and not nome.startswith("_")
    and nome != "chamar_verde_com_retry"
)


async def _resposta_503(requisicao: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"mensagem": "indisponível (simulado)"})


async def _resposta_401(requisicao: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"mensagem": "token inválido (simulado)"})


async def _tempo_esgotado(requisicao: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("tempo esgotado (simulado)", request=requisicao)


FALHAS_DE_INFRA: dict[str, Callable[[httpx.Request], Awaitable[httpx.Response]]] = {
    "503": _resposta_503,
    "tempo esgotado": _tempo_esgotado,
    "401": _resposta_401,
}


@dataclass(frozen=True)
class Roteiro:
    """Uma conversa do passeio: o estado inicial (os `dadosConhecidos`) e as
    respostas às perguntas de texto, por padrão do texto da pergunta. A primeira
    que casa vale; sem nenhuma, a resposta é `TEXTO_PADRAO`."""

    entrada: dict[str, Any] = field(default_factory=dict)
    respostas_de_texto: tuple[tuple[str, str], ...] = ()


TEXTO_PADRAO = "texto do passeio de conformidade"


@dataclass(frozen=True)
class FluxoSobConferencia:
    nome: str
    # None no grafo padrão, que não é um registro: os planejados apontam para ele.
    fluxo_id: str | None
    config: FluxoConfig
    modulo_grafo: ModuleType
    modulo_api: ModuleType
    roteiros: tuple[Roteiro, ...] = (Roteiro(),)

    @classmethod
    def do_registro(cls, fluxo_id: str | None, config: FluxoConfig, roteiros: tuple[Roteiro, ...] = (Roteiro(),)) -> FluxoSobConferencia:
        return cls(
            nome=config.nome,
            fluxo_id=fluxo_id,
            config=config,
            modulo_grafo=sys.modules[config.obter_grafo.__module__],
            modulo_api=sys.modules[config.extrair_metadados.__module__],
            roteiros=roteiros,
        )


Falhas = dict[str, list[str]]


# --- Sem executar ----------------------------------------------------------------


def _anotacoes(esquema: Any) -> dict[str, Any]:
    return typing.get_type_hints(esquema, include_extras=True)


def _literais(tipo: Any) -> set[Any]:
    if typing.get_origin(tipo) is typing.Literal:
        return set(typing.get_args(tipo))
    return set().union(*(_literais(a) for a in typing.get_args(tipo))) if typing.get_args(tipo) else set()


def _subgrafos(
    construtor: StateGraph[Any, Any, Any, Any], caminho: str = ""
) -> Iterator[tuple[str, StateGraph[Any, Any, Any, Any], CompiledStateGraph[Any, Any, Any, Any]]]:
    """(caminho, construtor do pai, subgrafo compilado), também os aninhados."""
    for nome, especificacao in construtor.nodes.items():
        if isinstance(especificacao.runnable, CompiledStateGraph):
            sub = especificacao.runnable
            yield f"{caminho}{nome}", construtor, sub
            yield from _subgrafos(sub.builder, f"{caminho}{nome}/")


def _sem_executar(fluxo: FluxoSobConferencia, falhas: Falhas) -> None:
    grafo = fluxo.config.obter_grafo()
    construtor = grafo.builder
    estado = _anotacoes(construtor.state_schema)

    if "statusFinal" not in estado:
        falhas["A1"].append("o estado não tem statusFinal")
    elif not _literais(estado["statusFinal"]) or not _literais(estado["statusFinal"]) <= STATUS_FINAIS:
        falhas["A1"].append(f"statusFinal aceita {sorted(map(str, _literais(estado['statusFinal'])))}, e não só {sorted(STATUS_FINAIS)}")
    if estado.get("tokensGastos") != CanalTokensGastos:
        falhas["A2"].append("o estado não tem tokensGastos com o canal que soma (CanalTokensGastos)")
    if "mensagemFinal" not in estado:
        falhas["A3"].append("o estado não tem mensagemFinal")

    # Os subgrafos importados são compilados na importação, de propósito (A12);
    # o que não pode estar compilado é o grafo do próprio fluxo.
    compilados = [
        nome for nome, valor in vars(fluxo.modulo_grafo).items() if isinstance(valor, CompiledStateGraph) and valor.builder is construtor
    ]
    if compilados:
        falhas["A8"].append(f"o módulo do grafo compila o fluxo na importação: {compilados}")
    if not any(isinstance(valor, FabricaGrafo) for valor in vars(fluxo.modulo_grafo).values()):
        falhas["A8"].append("o módulo do grafo não usa FabricaGrafo")

    pacote = fluxo.modulo_api.__name__.split(".")[-2]
    extrair = getattr(fluxo.modulo_api, f"extrair_metadados_{pacote}", None)
    if not callable(extrair):
        falhas["A9"].append(f"o api.py não tem extrair_metadados_{pacote}")
    elif fluxo.config.extrair_metadados is not extrair:
        falhas["A9"].append(f"o registro não usa extrair_metadados_{pacote}")
    for constante, campo in (("MENSAGEM_CONCLUIDO", "mensagem_concluido"), ("MENSAGEM_HANDOFF", "mensagem_handoff")):
        valor = getattr(fluxo.modulo_api, constante, None)
        if not isinstance(valor, str) or not valor:
            falhas["A9"].append(f"o api.py não tem {constante}")
        elif getattr(fluxo.config, campo) != valor:
            falhas["A9"].append(f"o registro não usa {constante} em {campo}")

    # A A10 é sobre o registro. O grafo padrão não é um registro: os planejados
    # apontam para ele, e a descrição vazia é de propósito (fluxos/__init__.py).
    if fluxo.fluxo_id is not None:
        try:
            id_ = uuid.UUID(fluxo.fluxo_id)
            if id_.version != 4 or str(id_) != fluxo.fluxo_id:
                falhas["A10"].append(f"o id {fluxo.fluxo_id} não é um uuid4 em minúsculas")
        except ValueError:
            falhas["A10"].append(f"o id {fluxo.fluxo_id!r} não é um uuid")
        if not _KEBAB.fullmatch(fluxo.config.nome):
            falhas["A10"].append(f"o nome {fluxo.config.nome!r} não está em kebab-case")
        if not fluxo.config.descricao.strip():
            falhas["A10"].append("a descrição está vazia: a classificação do orquestrador depende dela")

    for caminho, pai, sub in _subgrafos(construtor):
        if sub.checkpointer is not None:
            falhas["A12"].append(f"o subgrafo {caminho} tem persistência própria")
        # Só o nome do canal liga o subgrafo ao pai. Sem nenhum em comum, o que o
        # subgrafo escreve não chega a lugar nenhum. Quais canais o pai precisa
        # ler, o teste não sabe: o passeio mostra o efeito, se o desfecho mudar.
        if not _anotacoes(pai.state_schema).keys() & _anotacoes(sub.builder.state_schema).keys():
            falhas["A12"].append(f"o subgrafo {caminho} não divide nenhum canal com o pai")

    desenho = grafo.get_graph()
    chegam = {"__end__"}
    mudou = True
    while mudou:
        mudou = False
        for aresta in desenho.edges:
            if aresta.target in chegam and aresta.source not in chegam:
                chegam.add(aresta.source)
                mudou = True
    presos = sorted(set(desenho.nodes) - chegam)
    if presos:
        falhas["fim"].append(f"nós que não chegam ao fim: {presos}")


# --- Passeios ---------------------------------------------------------------------


@dataclass
class Passeio:
    perguntas: list[Any]
    corpos: list[dict[str, Any]]
    valores: dict[str, Any]
    terminou: bool

    @property
    def desfecho(self) -> str:
        if not self.terminou:
            return f"não terminou em {LIMITE_DE_PASSOS} passos"
        return f"{self.valores.get('statusFinal')}/{self.valores.get('motivoHandoff')}"


def _resposta_de_texto(roteiro: Roteiro, pergunta: Any) -> str:
    texto = str(pergunta.get("pergunta")) if isinstance(pergunta, dict) else ""
    for padrao, resposta in roteiro.respostas_de_texto:
        if re.search(padrao, texto):
            return resposta
    return TEXTO_PADRAO


async def passear(fluxo: FluxoSobConferencia, roteiro: Roteiro, sim_nao: str) -> Passeio:
    """Uma conversa do começo ao fim, montando a resposta da rota a cada passo."""
    f = Fluxo(fluxo.config.obter_grafo(), f"conformidade-{fluxo.nome}")
    resultado = await f.iniciar(dict(roteiro.entrada))
    perguntas: list[Any] = []
    corpos: list[dict[str, Any]] = []
    for _ in range(LIMITE_DE_PASSOS):
        valores = await f.estado()
        pergunta = extrair_interrupt(resultado)
        corpos.append(montar_resposta_atendimento(fluxo.config, fluxo.fluxo_id or ID_FICTICIO, "chat-conformidade", pergunta, valores))
        if pergunta is None:
            return Passeio(perguntas, corpos, valores, True)
        perguntas.append(pergunta)
        eh_sim_nao = isinstance(pergunta, dict) and pergunta.get("tipo") == "sim_nao"
        resultado = await f.responder(sim_nao if eh_sim_nao else _resposta_de_texto(roteiro, pergunta))
    return Passeio(perguntas, corpos, await f.estado(), False)


def _erros_de_esquema(valor: Any, esquema: Schema, onde: str) -> list[str]:
    """O pedaço de JSON Schema que `esquemas.py` usa: type, enum, format uuid,
    properties e items."""
    tipos: dict[str, type | tuple[type, ...]] = {"object": dict, "array": list, "string": str, "number": (int, float), "boolean": bool}
    tipo = esquema.get("type")
    if (tipo and not isinstance(valor, tipos[tipo])) or (tipo == "number" and isinstance(valor, bool)):
        return [f"{onde}: {valor!r} não é {tipo}"]
    if "enum" in esquema and valor not in esquema["enum"]:
        return [f"{onde}: {valor!r} fora de {esquema['enum']}"]
    if esquema.get("format") == "uuid":
        try:
            uuid.UUID(valor)
        except ValueError:
            return [f"{onde}: {valor!r} não é uuid"]
    erros: list[str] = []
    if tipo == "object":
        for chave, sub in esquema.get("properties", {}).items():
            if chave in valor and valor[chave] is not AUSENTE:
                erros += _erros_de_esquema(valor[chave], sub, f"{onde}.{chave}")
    if tipo == "array" and "items" in esquema:
        for i, item in enumerate(valor):
            erros += _erros_de_esquema(item, esquema["items"], f"{onde}[{i}]")
    return erros


def _conferir_passeio(estado: dict[str, Any], passeio: Passeio, rotulo: str, falhas: Falhas) -> None:
    if not passeio.terminou:
        falhas["fim"].append(f"{rotulo}: {passeio.desfecho} (as respostas de texto do passeio ficam em ROTEIROS, test_conformidade.py)")
        return
    status = passeio.valores.get("statusFinal")
    if status not in STATUS_FINAIS:
        falhas["A1"].append(f"{rotulo}: terminou com statusFinal {status!r}")
    if status == "handoff_humano":
        motivos = _literais(estado.get("motivoHandoff", type(None)))
        motivo = passeio.valores.get("motivoHandoff")
        if motivo not in motivos:
            falhas["A11"].append(f"{rotulo}: encaminhou com motivoHandoff {motivo!r}, fora da lista do fluxo {sorted(motivos)}")
    for pergunta in passeio.perguntas:
        if not isinstance(pergunta, dict) or not isinstance(pergunta.get("pergunta"), str) or not pergunta["pergunta"]:
            falhas["A4"].append(f"{rotulo}: pausa sem pergunta: {pergunta!r}")
        elif pergunta.get("tipo") not in TIPOS_DE_PERGUNTA:
            falhas["A4"].append(f"{rotulo}: pausa com tipo {pergunta.get('tipo')!r}: {pergunta['pergunta']!r}")
        elif pergunta["tipo"] == "sim_nao" and pergunta.get("opcoes") != OPCOES_SIM_NAO:
            falhas["A5"].append(f"{rotulo}: pergunta sim/não com opções {pergunta.get('opcoes')!r}: {pergunta['pergunta']!r}")
    for i, corpo in enumerate(passeio.corpos):
        for erro in _erros_de_esquema(corpo, RESPOSTA_ATENDIMENTO, f"resposta {i + 1}"):
            falhas["contrato"].append(f"{rotulo}: {erro}")


def _assinatura(passeio: Passeio) -> tuple[Any, ...]:
    return (tuple(str(p.get("pergunta")) if isinstance(p, dict) else repr(p) for p in passeio.perguntas), passeio.desfecho)


async def _passeios_estruturais(fluxo: FluxoSobConferencia, falhas: Falhas) -> None:
    estado = _anotacoes(fluxo.config.obter_grafo().builder.state_schema)
    for n, roteiro in enumerate(fluxo.roteiros, 1):
        for sim_nao, equivalente in (("Sim", "s"), ("Não", "n")):
            rotulo = f"roteiro {n}, respondendo {sim_nao!r}"
            passeio = await passear(fluxo, roteiro, sim_nao)
            _conferir_passeio(estado, passeio, rotulo, falhas)
            # A5: a resposta passa por resposta_eh_sim, então "s" e "Sim" dão a mesma conversa.
            if _assinatura(await passear(fluxo, roteiro, equivalente)) != _assinatura(passeio):
                falhas["A5"].append(f"{rotulo}: responder {equivalente!r} muda a conversa; a resposta não passa por resposta_eh_sim")


# --- IA simulada --------------------------------------------------------------------


def _lista_fechada(propriedade: dict[str, Any]) -> bool:
    return "enum" in propriedade or (propriedade.get("type") == "array" and "enum" in propriedade.get("items", {}))


@contextmanager
def trocar_em_todo_lugar(original: Any, substituto: Any) -> Iterator[None]:
    """Troca uma função em todo módulo `maria.*` que a importou, com ou sem outro
    nome (`from ... import consultar_cep as consultar_cep_verde`)."""
    with pytest.MonkeyPatch.context() as m:
        for nome_modulo, modulo in list(sys.modules.items()):
            if nome_modulo == "maria" or nome_modulo.startswith("maria.") or nome_modulo.startswith("tests."):
                for atributo, valor in list(vars(modulo).items()):
                    if valor is original:
                        m.setattr(modulo, atributo, substituto)
        yield


class IASimulada:
    """Fica no lugar de `invocar_estruturado`. A reescrita (o único esquema com
    só `pergunta`) devolve o texto original com uma marca `[n]`, e toda
    propriedade de lista fechada vem com `INVENTADO`. As outras ficam ausentes,
    como quando o modelo não acha nada no texto."""

    def __init__(self) -> None:
        self.reescritas = 0

    async def __call__(self, modelo: Any, esquema: dict[str, Any], sistema: str, usuario: str) -> dict[str, Any]:
        propriedades: dict[str, Any] = esquema["properties"]
        if set(propriedades) == {"pergunta"}:
            self.reescritas += 1
            original = usuario.split("Pergunta original: ", 1)[-1].removesuffix("\nReescreva.")
            parsed: dict[str, Any] = {"pergunta": f"[{self.reescritas}] {original}"}
        else:
            parsed = {nome: [INVENTADO] if p.get("type") == "array" else INVENTADO for nome, p in propriedades.items() if _lista_fechada(p)}
        uso = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        return {"raw": AIMessage(content="", usage_metadata=uso), "parsed": parsed}


async def _passeios_com_ia(fluxo: FluxoSobConferencia, falhas: Falhas) -> None:
    for n, roteiro in enumerate(fluxo.roteiros, 1):
        for sim_nao in ("Sim", "Não"):
            rotulo = f"roteiro {n} com IA, respondendo {sim_nao!r}"
            ia = IASimulada()
            with pytest.MonkeyPatch.context() as m, trocar_em_todo_lugar(_estruturado.invocar_estruturado, ia):
                m.delenv("APP_ENV")
                m.setenv("REESCREVER_IA", "true")
                m.setenv("EXTRACAO_LIVRE_IA", "true")
                passeio = await passear(fluxo, roteiro, sim_nao)
            usadas: set[int] = set()
            for pergunta in passeio.perguntas:
                texto = str(pergunta.get("pergunta")) if isinstance(pergunta, dict) else ""
                marca = _MARCA.match(texto)
                if marca is None:
                    falhas["A6"].append(f"{rotulo}: a pergunta {texto!r} não passou pelo nó que prepara")
                elif int(marca.group(1)) in usadas or (usadas and int(marca.group(1)) < max(usadas)):
                    falhas["A6"].append(f"{rotulo}: a pergunta {texto!r} repete o texto preparado para uma pergunta anterior")
                else:
                    usadas.add(int(marca.group(1)))
            sobras = sorted(set(range(1, ia.reescritas + 1)) - usadas)
            if sobras:
                falhas["A7"].append(
                    f"{rotulo}: {len(sobras)} pergunta(s) preparada(s) e não feita(s): o nó que prepara e o que pede não pulam juntos"
                )
            for i, corpo in enumerate(passeio.corpos):
                # O corpo como a Tykhe o recebe, sem o texto livre da pergunta.
                enviado = serializar(RESPOSTA_ATENDIMENTO, {**corpo, "resposta": ""})
                if INVENTADO in enviado:
                    falhas["A13"].append(f"{rotulo}: um valor fora da lista, devolvido pela IA, chegou à resposta {i + 1}: {enviado}")
                    break


# --- Verde falhando ------------------------------------------------------------------


@contextmanager
def _registrar_chamadas() -> Iterator[list[str]]:
    feitas: list[str] = []
    with ExitStack() as pilha:
        for nome in CHAMADAS_VERDE:
            original = getattr(verde, nome)

            def registrar(nome: str = nome, original: Any = original) -> Any:
                async def chamada(*args: Any, **kwargs: Any) -> Any:
                    feitas.append(nome)
                    return await original(*args, **kwargs)

                return chamada

            pilha.enter_context(trocar_em_todo_lugar(original, registrar()))
        yield feitas


@contextmanager
def falhar_chamada(nome: str, falha: str, transporte: TransporteFalso) -> Iterator[None]:
    """A chamada `nome` sai do modo mock e encontra o Verde falhando; as outras
    continuam no mock. O transporte é o falso: nada sai para a rede."""
    original = getattr(verde, nome)

    async def chamada(*args: Any, **kwargs: Any) -> Any:
        salvos = (verde.VERDE_JWT_TOKEN, verde.VERDE_CLIENT_ID, verde.VERDE_API_URL, transporte.tratador)
        verde.VERDE_JWT_TOKEN, verde.VERDE_CLIENT_ID, verde.VERDE_API_URL = "token-de-conformidade", "cliente-de-conformidade", URL_VERDE
        transporte.tratador = FALHAS_DE_INFRA[falha]
        try:
            return await original(*args, **kwargs)
        finally:
            verde.VERDE_JWT_TOKEN, verde.VERDE_CLIENT_ID, verde.VERDE_API_URL, transporte.tratador = salvos

    with trocar_em_todo_lugar(original, chamada):
        yield


async def _passeios_com_verde_falhando(fluxo: FluxoSobConferencia, falhas: Falhas, transporte: TransporteFalso) -> None:
    for n, roteiro in enumerate(fluxo.roteiros, 1):
        for sim_nao in ("Sim", "Não"):
            with _registrar_chamadas() as feitas:
                await passear(fluxo, roteiro, sim_nao)
            for nome in dict.fromkeys(feitas):
                for falha in FALHAS_DE_INFRA:
                    with falhar_chamada(nome, falha, transporte):
                        passeio = await passear(fluxo, roteiro, sim_nao)
                    if (
                        not passeio.terminou
                        or passeio.valores.get("statusFinal") != "handoff_humano"
                        or passeio.valores.get("motivoHandoff") != MOTIVO_FALHA_INFRA
                    ):
                        falhas["A14"].append(f"roteiro {n}, respondendo {sim_nao!r}: {nome} com {falha} terminou em {passeio.desfecho}")


async def conferir(fluxo: FluxoSobConferencia, transporte: TransporteFalso) -> Falhas:
    falhas: Falhas = {regra: [] for regra in REGRAS}
    _sem_executar(fluxo, falhas)
    await _passeios_estruturais(fluxo, falhas)
    await _passeios_com_ia(fluxo, falhas)
    await _passeios_com_verde_falhando(fluxo, falhas, transporte)
    return falhas
