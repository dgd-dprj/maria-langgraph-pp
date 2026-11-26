"""Script de coleta (issue #20): roda sob demanda (não em request), varre a
árvore de perguntas do Verde (GET /integra/assunto/consultar-item-arvore)
categoria por categoria até achar os "assuntos" finais
(GET /integra/assunto/{idAssunto}), salvando tudo em `perguntas` +
`assuntos_verde` (shared/perguntas_db.py). Não incremental: recrawleia (limpa e
reinsere) cada flowId visitado, porque a árvore pode mudar de forma entre uma
rodada e outra.

Uso: `uv run python scripts/coletar_arvore_perguntas_verde.py` (precisa de
DATABASE_URL e de VERDE_JWT_TOKEN/VERDE_CLIENT_ID reais no .env; sem modo mock,
é um script de coleta de dado real, não faz sentido rodar contra dado inventado).

#251 (decisão da Nicole, 2026-11-18): cada categoria é varrida em memória, sem tocar no
banco. No fim, as categorias que deram certo trocam de árvore numa transação só. Uma
categoria que falhou fica com a árvore anterior, e o script sai com código 1. Em
develop, a categoria era apagada antes da varredura, e a falha saía com código 0.
"""

import asyncio
import io
import os
import sys
import traceback
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import httpx
from dotenv import load_dotenv

from maria.fluxos import ID_VIOLENCIA_DOMESTICA, fluxos_por_id
from maria.shared._js import (
    AUSENTE,
    coalesce,
    definir,
    json_parse,
    json_stringify_js,
    prop,
    texto_template,
    trim_js,
    verdadeiro,
)
from maria.shared.fluxos_planejados_db import fechar_fluxos_planejados_store, listar_fluxos_planejados
from maria.shared.perguntas_db import (
    ArvoreColetada,
    AssuntoVerde,
    FlowAssunto,
    PerguntaArvore,
    fechar_perguntas_store,
    obter_perguntas_store,
)

VERDE_API_URL_PADRAO = "https://homologacao.verde.rj.def.br/api/integra"

# Guarda contra árvore mal-formada/loop infinito: nenhuma árvore real do Verde
# deveria chegar nem perto disso (violência doméstica tem profundidade 1).
PROFUNDIDADE_MAXIMA = 12
PAUSA_ENTRE_CHAMADAS_MS = 120
TIMEOUT_MS = 20_000


class ErroJs(Exception):
    """Um `Error` (ou `TypeError`) de develop: `str()` é o `err.message` do JS."""

    def __init__(self, mensagem: str, nome: str = "Error") -> None:
        super().__init__(mensagem)
        self.nome = nome


@dataclass(frozen=True)
class ConfigVerde:
    api_url: str
    jwt_token: str
    client_id: str


def config_do_ambiente() -> ConfigVerde:
    # `process.env.X ?? padrão`: variável definida e vazia continua vazia.
    return ConfigVerde(
        api_url=os.environ.get("VERDE_API_URL", VERDE_API_URL_PADRAO),
        jwt_token=os.environ.get("VERDE_JWT_TOKEN", ""),
        client_id=os.environ.get("VERDE_CLIENT_ID", ""),
    )


async def pausa(ms: int) -> None:
    await asyncio.sleep(ms / 1000)


def _headers_verde(config: ConfigVerde) -> dict[str, str]:
    return {"accept": "application/json", "authorization": f"Bearer {config.jwt_token}", "x-client-id": config.client_id}


async def _fetch_json(cliente: httpx.AsyncClient, config: ConfigVerde, url: str) -> tuple[httpx.Response, Any]:
    """`fetch(url, { signal: AbortSignal.timeout(20_000) })` e, se `res.ok`, `res.json()`.
    O timeout cobre a requisição e a leitura do corpo, como o signal do fetch."""
    if not url.startswith(("http://", "https://")) and "://" not in url:
        raise ErroJs(f"Failed to parse URL from {url}", "TypeError")
    try:
        async with asyncio.timeout(TIMEOUT_MS / 1000):
            res = await cliente.get(url, headers=_headers_verde(config))
            corpo = json_parse(res.content) if res.is_success else None
    except TimeoutError:
        raise ErroJs("The operation was aborted due to timeout", "TimeoutError") from None
    except httpx.TransportError:
        raise ErroJs("fetch failed", "TypeError") from None
    return res, corpo


async def consultar_item_arvore(cliente: httpx.AsyncClient, config: ConfigVerde, params: dict[str, Any]) -> Any:
    id_categoria = params.get("idCategoria", AUSENTE)
    if id_categoria is not AUSENTE:
        query = f"idCategoria={texto_template(id_categoria)}"
    else:
        query = f"idItemCategoria={texto_template(params.get('idItemCategoria', AUSENTE))}"
    res, corpo = await _fetch_json(cliente, config, f"{config.api_url}/assunto/consultar-item-arvore?{query}")
    if not res.is_success:
        raise ErroJs(f"consultar-item-arvore HTTP {res.status_code} ({json_stringify_js(params)})")
    dados = prop(corpo, "dados")
    if not verdadeiro(dados):
        raise ErroJs(f"consultar-item-arvore sem 'dados' ({json_stringify_js(params)})")
    return dados


async def consultar_assunto(cliente: httpx.AsyncClient, config: ConfigVerde, id_assunto: Any) -> Any:
    res, corpo = await _fetch_json(cliente, config, f"{config.api_url}/assunto/{texto_template(id_assunto)}")
    if not res.is_success:
        raise ErroJs(f"GET /assunto/{texto_template(id_assunto)} HTTP {res.status_code}")
    dados = prop(corpo, "dados")
    if not verdadeiro(dados):
        raise ErroJs(f"GET /assunto/{texto_template(id_assunto)} sem 'dados'")
    return dados


def tipo_da_pergunta(respostas: Any) -> str:
    """ "SIM"/"NÃO" (2 respostas, nada mais) é sim_nao; qualquer outra coisa
    (3+ opções, ou 2 opções que não são sim/não) é opcoes."""
    if not isinstance(respostas, list):
        raise ErroJs("respostas.map is not a function", "TypeError")
    normalizadas: list[str] = []
    for r in respostas:
        resposta = prop(r, "resposta")
        if not isinstance(resposta, str):
            prop(resposta, "trim")  # null/undefined: "Cannot read properties of ... (reading 'trim')"
            raise ErroJs("r.resposta.trim is not a function", "TypeError")
        normalizadas.append(trim_js(resposta).upper())
    eh_sim_nao = len(normalizadas) == 2 and "SIM" in normalizadas and "NÃO" in normalizadas
    return "sim_nao" if eh_sim_nao else "opcoes"


def _tamanho_zero(valor: Any) -> bool:
    """`valor.length === 0`: só lista e texto têm length."""
    return isinstance(valor, list | str) and len(valor) == 0


async def varrer_flow(
    cliente: httpx.AsyncClient, config: ConfigVerde, flow_id: str, id_categoria_assunto_verde: int, nome: str
) -> ArvoreColetada:
    """Varre a árvore da categoria no Verde e devolve tudo em memória, sem tocar no banco (#251)."""
    arvore: ArvoreColetada = {"flowId": flow_id, "perguntas": [], "assuntos": [], "ligacoes": []}

    ordem = 0
    total_perguntas = 0
    total_assuntos = 0

    async def visitar(params: dict[str, Any], veio_da_resposta_id: Any, profundidade: int) -> None:
        nonlocal ordem, total_perguntas, total_assuntos
        if profundidade > PROFUNDIDADE_MAXIMA:
            raise ErroJs(f'profundidade máxima ({PROFUNDIDADE_MAXIMA}) excedida em "{nome}" — árvore maior que o esperado ou loop')
        await pausa(PAUSA_ENTRE_CHAMADAS_MS)
        dados = await consultar_item_arvore(cliente, config, params)

        if verdadeiro(prop(dados, "assuntoEncontrado")):
            id_assunto = prop(dados, "idAssunto")
            # `=== undefined`: só a chave ausente. `idAssunto: null` passa e vira GET /assunto/null.
            if id_assunto is AUSENTE:
                raise ErroJs(f'assuntoEncontrado sem idAssunto em "{nome}"')
            await pausa(PAUSA_ENTRE_CHAMADAS_MS)
            detalhe = await consultar_assunto(cliente, config, id_assunto)
            assunto: dict[str, Any] = {
                "idAssunto": id_assunto,
                "nome": coalesce(coalesce(prop(detalhe, "nome"), prop(dados, "nomeAssunto")), ""),
            }
            definir(assunto, "nomeMateria", prop(detalhe, "nomeMateria"))
            definir(assunto, "descricao", prop(detalhe, "descricao"))
            definir(assunto, "txDocumentosNecessarios", prop(detalhe, "txDocumentosNecessarios"))
            assunto["documentosNecessarios"] = coalesce(prop(detalhe, "documentosNecessarios"), [])
            assunto["urgente"] = coalesce(prop(detalhe, "urgente"), False)
            assunto["plantao"] = coalesce(prop(detalhe, "plantao"), False)
            # Detalhe do assunto é upsert por idAssunto (compartilhado entre
            # categorias); a ligação flow→assunto é sempre uma linha NOVA, mesmo
            # quando o idAssunto já existia de outra categoria.
            arvore["assuntos"].append(cast(AssuntoVerde, assunto))
            ligacao: FlowAssunto = {
                "id": str(uuid.uuid4()),
                "flowId": flow_id,
                "idAssunto": id_assunto,
                "veioDaRespostaId": None if veio_da_resposta_id is AUSENTE else veio_da_resposta_id,
            }
            arvore["ligacoes"].append(ligacao)
            total_assuntos += 1
            return

        pergunta = prop(dados, "pergunta")
        respostas = coalesce(prop(dados, "respostas"), [])
        if not verdadeiro(pergunta):
            raise ErroJs(f'nó sem pergunta e sem assuntoEncontrado em "{nome}" ({json_stringify_js(params)})')

        # Achado ao vivo em develop (2026-09-11): alguns nós do Verde têm `pergunta`
        # (na real, um aviso final) com `respostas: []` e `assuntoEncontrado: false`.
        # Vira nó informativo (tipo "texto", sem opções) e não desce mais; sem isso
        # o crawl inteiro da categoria abortava por causa de um nó sem saída.
        linha = {
            "id": str(uuid.uuid4()),
            "flowId": flow_id,
            "idItemCategoria": coalesce(params.get("idItemCategoria", AUSENTE), None),
            "veioDaRespostaId": None if veio_da_resposta_id is AUSENTE else veio_da_resposta_id,
            "textoPergunta": pergunta,
            "tipo": "texto" if _tamanho_zero(respostas) else tipo_da_pergunta(respostas),
            "opcoes": respostas,
            "ordem": ordem,
        }
        ordem += 1
        arvore["perguntas"].append(cast(PerguntaArvore, linha))
        total_perguntas += 1

        for resposta in respostas:
            id_resposta = prop(resposta, "id")
            await visitar({"idItemCategoria": id_resposta}, id_resposta, profundidade + 1)

    await visitar({"idCategoria": id_categoria_assunto_verde}, None, 0)
    print(f"[{nome}] {total_perguntas} pergunta(s), {total_assuntos} assunto(s)")
    return arvore


async def coletar(cliente: httpx.AsyncClient, config: ConfigVerde) -> int:
    """Varre todas as categorias e troca as árvores das que deram certo numa transação só. Devolve o número de falhas."""
    alvos: list[tuple[str, int, str]] = []

    # Único fluxo IMPLEMENTADO com categoria do Verde equivalente; pessoa presa
    # não entra aqui, não existe categoria do Verde para ela.
    vd = fluxos_por_id.get(ID_VIOLENCIA_DOMESTICA)
    if vd is not None and vd.id_categoria_assunto_verde is not None:
        alvos.append((ID_VIOLENCIA_DOMESTICA, vd.id_categoria_assunto_verde, vd.nome))

    for f in await listar_fluxos_planejados():
        alvos.append((f["id"], f["idCategoriaAssuntoVerde"], f["nome"]))

    print(f"crawl iniciado — {len(alvos)} categorias")
    total_perguntas = 0
    total_assuntos = 0
    falhas: list[tuple[str, str, str]] = []
    coletadas: list[ArvoreColetada] = []

    for flow_id, id_categoria, nome in alvos:
        try:
            arvore = await varrer_flow(cliente, config, flow_id, id_categoria, nome)
        except Exception as err:
            erro = str(err)
            print(f"[{nome}] falhou: {erro}", file=sys.stderr)
            falhas.append((flow_id, nome, erro))
            continue
        coletadas.append(arvore)
        total_perguntas += len(arvore["perguntas"])
        total_assuntos += len(arvore["ligacoes"])

    # Uma transação só para todas as categorias que deram certo. Se ela falhar, nenhuma árvore muda,
    # e o erro sobe até o "crawl falhou:".
    store = await obter_perguntas_store()
    await store.substituir_arvores(coletadas)

    print(f"crawl concluído: {total_perguntas} pergunta(s), {total_assuntos} assunto(s), {len(falhas)} falha(s) em {len(alvos)} categorias")
    if falhas:
        # #526: com a data da última coleta bem-sucedida, uma categoria que falha em toda execução não passa despercebida.
        datas = await store.datas_das_coletas([flow_id for flow_id, _, _ in falhas])
        agora = datetime.now(UTC)
        print(
            "categorias com falha (a árvore anterior foi mantida):",
            ", ".join(f"{nome} ({descrever_ultima_coleta(datas.get(flow_id), agora)})" for flow_id, nome, _ in falhas),
        )
    return len(falhas)


# As datas do resumo saem no horário de Brasília (UTC-3, sem horário de verão desde 2019).
BRASILIA = timezone(timedelta(hours=-3))


def descrever_ultima_coleta(quando: datetime | None, agora: datetime) -> str:
    """#526: "última coleta em 02/11/2026, há 16 dias", ou "nunca coletada com sucesso"."""
    if quando is None:
        return "nunca coletada com sucesso"
    dias = (agora - quando).days
    data = quando.astimezone(BRASILIA).strftime("%d/%m/%Y")
    if dias <= 0:
        return f"última coleta em {data}, hoje"
    return f"última coleta em {data}, há {dias} dia{'s' if dias > 1 else ''}"


async def principal() -> int:
    """Devolve o número de categorias que falharam."""
    config = config_do_ambiente()
    if not config.jwt_token:
        raise ErroJs("VERDE_JWT_TOKEN obrigatório — este script fala com o Verde de verdade, sem modo mock")
    if not os.environ.get("DATABASE_URL"):
        raise ErroJs("DATABASE_URL obrigatório — sem isso o resultado do crawl não fica salvo em lugar nenhum")
    try:
        async with httpx.AsyncClient(timeout=None) as cliente:
            return await coletar(cliente, config)
    finally:
        await fechar_perguntas_store()
        await fechar_fluxos_planejados_store()


async def _executar() -> int:
    # #255 (decisão da Nicole, 2026-11-17): a coleta não inicializa mais o checkpointer do LangGraph. Em develop
    # (TypeScript), importar os fluxos já criava as tabelas de checkpoint e, com o banco fora, matava o processo
    # antes do "crawl falhou:"; a tradução reproduzia isso de propósito. Agora qualquer falha passa pelo prefixo.
    try:
        falhas = await principal()
    except Exception as erro:
        # `console.error("crawl falhou:", erro)` do Node: primeira linha `<nome>: <mensagem>`,
        # seguida da pilha. A pilha é a do Python (spec 08, D-4).
        nome = erro.nome if isinstance(erro, ErroJs) else type(erro).__name__
        print(f"crawl falhou: {nome}: {erro}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    # #251: categoria que falhou não passa mais como sucesso para quem roda nem para uma automação.
    return 1 if falhas else 0


def main() -> int:
    load_dotenv()
    return asyncio.run(_executar())


if __name__ == "__main__":
    # O console.* do Node escreve sempre em UTF-8; o Python, com a saída redirecionada no
    # Windows, usaria a página de código local e trocaria os acentos.
    for fluxo in (sys.stdout, sys.stderr):
        if isinstance(fluxo, io.TextIOWrapper):
            fluxo.reconfigure(encoding="utf-8")
    if sys.platform == "win32":
        # O psycopg assíncrono não funciona com o loop padrão do Windows (ver tests/conftest.py).
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(main())
