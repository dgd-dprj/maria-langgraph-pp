"""Cliente do Verde, o sistema da Defensoria (tradução de `integracoes/verde.ts`).

Sem VERDE_JWT_TOKEN (dev local e testes), toda função cai num mock com
sentinelas fixas e nunca chama o Verde.

Fidelidade a develop que não é óbvia (spec do módulo integracoes, #219):
- Cada leitura de resposta usa `_js.prop`/`_js.opt`, porque o código de develop
  distingue chave ausente de null, trata `{}` como verdadeiro e LANÇA TypeError
  em `null.campo` (o que vira 500 na rota).
- Prazo total de 30 s por tentativa (TIMEOUT_VERDE_MS), também sobre a leitura
  do corpo. Nos três POST, o corpo é lido FORA do retry, como em develop: um
  timeout lendo o corpo nunca reenvia um encaminhamento ou um cadastro. Nos seis
  GET, a leitura fica dentro do retry (divergência aceita).
- URLs montadas à mão, com `true`/`false` e escape igual ao encodeURIComponent.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast
from urllib.parse import quote

import httpx

from maria.integracoes import _js
from maria.integracoes._js import AUSENTE
from maria.integracoes.cliente_http import obter_cliente_http
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger
from maria.shared.types import (
    DadosApenado,
    DadosCep,
    DadosPessoa,
    DadosProcesso,
    OrgaoAtendimento,
    OrgaosViolenciaDomestica,
    Plantao,
    ResultadoCadastroPessoa,
    ResultadoEncaminhamento,
)

# TODO herdado de develop, atualizado: o VERDE_JWT_TOKEN é renovado pelo workflow
# verificar-token-verde.yml (docs/integracao-verde.md); a aplicação só o lê no boot.
# Lidos na importação, como em develop (verde.ts:17-19): sem fail-fast.
VERDE_API_URL = os.environ.get("VERDE_API_URL", "https://homologacao.verde.rj.def.br/api/integra")
VERDE_JWT_TOKEN = os.environ.get("VERDE_JWT_TOKEN", "")
VERDE_CLIENT_ID = os.environ.get("VERDE_CLIENT_ID", "")
# Issue #196: um RG real voltou "não encontrado" porque o Verde de homologação
# levou 13,5 s e o timeout antigo era de 20 s.
TIMEOUT_VERDE_S = 30.0
TENTATIVAS_RETRY_VERDE = 3

MENSAGEM_MOCK = "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)"
MENSAGEM_CRC_MOCK = (
    "Para dar continuidade ao seu atendimento, favor entrar em contato com a Central de Relacionamento com o Cidadão ligando 129"
)


def _agora_ms() -> int:
    return time.time_ns() // 1_000_000


def _escapar(valor: str) -> str:
    """encodeURIComponent: só A-Z a-z 0-9 - _ . ! ~ * ' ( ) ficam sem codificar."""
    return quote(valor, safe="!*'()")


# --- Retry de infra (issue #172) ---------------------------------------------


def _eh_auth_ou_infra(status: int) -> bool:
    return status in (401, 403) or status >= 500


def _log_http_nao_ok(chamada: str, status: int, duracao_ms: int, **extra: Any) -> None:
    """Issue #112: 401/403/5xx (auth_ou_infra, nível error) separados de 404/422
    (nao_encontrado, nível warn)."""
    tipo_erro = "auth_ou_infra" if _eh_auth_ou_infra(status) else "nao_encontrado"
    registrar = logger.error if tipo_erro == "auth_ou_infra" else logger.warn
    registrar(
        f"[verde] {chamada}: HTTP não-ok",
        **contexto_atual(),
        status=status,
        tipoErro=tipo_erro,
        evento="verde_chamada",
        chamada=chamada,
        resultado="nao_ok",
        duracaoMs=duracao_ms,
        **extra,
    )


@dataclass
class ResultadoChamadaVerde:
    """`{ok: true, res}` ou `{ok: false, res?, falhaInfra}` de develop."""

    ok: bool
    res: httpx.Response | None = None
    falha_infra: bool = False


async def chamar_verde_com_retry(chamada: str, montar_requisicao: Callable[[], Awaitable[httpx.Response]]) -> ResultadoChamadaVerde:
    """401/403/5xx e exceções (rede, timeout) são retentados até 3 vezes, sem
    espera; 404/422 saem na primeira tentativa. `res` vem na falha de negócio e
    na última falha de infra por status, nunca numa exceção."""
    for tentativa in range(1, TENTATIVAS_RETRY_VERDE + 1):
        inicio = _agora_ms()
        try:
            res = await montar_requisicao()
            duracao_ms = _agora_ms() - inicio
            if res.is_success:
                return ResultadoChamadaVerde(ok=True, res=res)
            if not _eh_auth_ou_infra(res.status_code):
                _log_http_nao_ok(chamada, res.status_code, duracao_ms)
                return ResultadoChamadaVerde(ok=False, res=res, falha_infra=False)
            _log_http_nao_ok(
                chamada, res.status_code, duracao_ms, tentativa=tentativa, tentativasRestantes=TENTATIVAS_RETRY_VERDE - tentativa
            )
            if tentativa == TENTATIVAS_RETRY_VERDE:
                return ResultadoChamadaVerde(ok=False, res=res, falha_infra=True)
            await res.aclose()
        except Exception as erro:
            duracao_ms = _agora_ms() - inicio
            logger.error(
                f"[verde] {chamada}: falha na chamada (tentativa {tentativa})",
                **contexto_atual(),
                err=erro,
                evento="verde_chamada",
                chamada=chamada,
                resultado="erro",
                duracaoMs=duracao_ms,
                tentativa=tentativa,
                tipoErro="auth_ou_infra",
            )
            if tentativa == TENTATIVAS_RETRY_VERDE:
                return ResultadoChamadaVerde(ok=False, falha_infra=True)
    return ResultadoChamadaVerde(ok=False, falha_infra=True)  # inalcançável, como em develop


# --- Requisição com o prazo do AbortSignal -------------------------------------

_PRAZO = "maria_prazo"


def _cabecalhos(*, com_accept: bool, com_corpo: bool) -> dict[str, str]:
    cabecalhos: dict[str, str] = {}
    if com_corpo:
        cabecalhos["content-type"] = "application/json"
    if com_accept:
        cabecalhos["accept"] = "application/json"
    cabecalhos["authorization"] = f"Bearer {VERDE_JWT_TOKEN}"
    cabecalhos["x-client-id"] = VERDE_CLIENT_ID
    return cabecalhos


def _requisicao(
    metodo: str, url: str, *, com_accept: bool, corpo: object = AUSENTE, ler_corpo: bool
) -> Callable[[], Awaitable[httpx.Response]]:
    """Uma tentativa, com o próprio prazo de 30 s (o AbortSignal é criado por
    tentativa em develop). Com `ler_corpo` (os GET), o corpo de uma resposta 2xx é
    lido aqui, dentro do retry. Sem ele (os POST), a resposta volta em modo stream
    e o corpo é lido depois, fora do retry, sob o mesmo prazo."""

    async def montar() -> httpx.Response:
        prazo = asyncio.get_running_loop().time() + TIMEOUT_VERDE_S
        cliente = obter_cliente_http()
        conteudo = None if corpo is AUSENTE else _js.json_stringify(corpo).encode("utf-8")
        requisicao = cliente.build_request(
            metodo, url, headers=_cabecalhos(com_accept=com_accept, com_corpo=conteudo is not None), content=conteudo
        )
        async with asyncio.timeout_at(prazo):
            res = await cliente.send(requisicao, stream=True)
            if ler_corpo and res.is_success:
                await res.aread()
        res.extensions[_PRAZO] = prazo
        return res

    return montar


async def _ler_json(res: httpx.Response) -> Any:
    """`await res.json()` de develop: lê sob o prazo da tentativa e lança se falhar."""
    async with asyncio.timeout_at(res.extensions[_PRAZO]):
        bruto = await res.aread()
    return _js.json_parse(bruto)


async def _ler_json_ou_vazio(res: httpx.Response) -> Any:
    """`res.json().catch(() => ({}))` de develop: qualquer falha (timeout, conexão
    cortada, JSON inválido) vira {}."""
    try:
        return await _ler_json(res)
    except Exception:
        return {}


async def _fechar(resultado: ResultadoChamadaVerde) -> None:
    if resultado.res is not None:
        await resultado.res.aclose()


def _sucesso(chamada: str, inicio: int, **extra: Any) -> None:
    logger.info(
        f"[verde] {chamada}: chamada concluída",
        **contexto_atual(),
        **extra,
        evento="verde_chamada",
        chamada=chamada,
        resultado="sucesso",
        duracaoMs=_agora_ms() - inicio,
    )


def _com_falha_infra(base: dict[str, Any], falha_infra: bool) -> dict[str, Any]:
    if falha_infra:
        base["falhaInfra"] = True
    return base


# --- Apenado (POST /apenado) ---------------------------------------------------


def _apenado_mock(rg: str) -> DadosApenado:
    # "000000000": não encontrado. "66666666666": falha de infra esgotada (#172).
    # Sentinelas da #57 com situação/tipo/regime fora do permitido; os valores não
    # têm "(mock)" porque concluir() compara por igualdade estrita.
    if rg == "000000000":
        return {"encontrado": False}
    if rg == "66666666666":
        return {"encontrado": False, "falhaInfra": True}
    variacoes = {
        "22222222222": ("LIBERTADO", "CONDENADO", "SEMIABERTO"),
        "33333333333": ("ATIVO", "PROVISÓRIO", "SEMIABERTO"),
        "44444444444": ("ATIVO", "CONDENADO", "ABERTO"),
        "55555555555": ("EM RESDOM", "CONDENADO", "FECHADO"),
    }
    situacao, tipo_preso, regime = variacoes.get(rg, ("ATIVO", "CONDENADO", "SEMIABERTO"))
    return {
        "encontrado": True,
        "idSeap": 999999,
        "idPessoa": 999999,
        "nome": "Pessoa de Teste (mock)",
        "situacao": situacao,
        "tipoPreso": tipo_preso,
        "regime": regime,
    }


async def consultar_apenado_por_rg(rg: str) -> DadosApenado:
    if not VERDE_JWT_TOKEN:
        logger.warn(MENSAGEM_MOCK, **contexto_atual())
        return _apenado_mock(rg)
    inicio = _agora_ms()
    resultado = await chamar_verde_com_retry(
        "apenado", _requisicao("POST", f"{VERDE_API_URL}/apenado", com_accept=False, corpo={"rg": rg}, ler_corpo=False)
    )
    if not resultado.ok or resultado.res is None:
        await _fechar(resultado)
        return cast(DadosApenado, _com_falha_infra({"encontrado": False}, resultado.falha_infra))
    corpo = await _ler_json(resultado.res)
    _sucesso("apenado", inicio)
    # RG não encontrado: o Verde devolve "dados": {} (objeto vazio, verdadeiro em
    # JS). O teste é pela CHAVE idPessoa, que só existe se achou.
    dados = _js.prop(corpo, "dados")
    if not _js.verdadeiro(dados) or _js.prop(dados, "idPessoa") is AUSENTE:
        return {"encontrado": False}
    saida: dict[str, Any] = {"encontrado": True}
    for chave in ("idSeap", "idPessoa", "nome", "situacao", "tipoPreso", "regime"):
        _js.definir(saida, chave, _js.prop(dados, chave))
    return cast(DadosApenado, saida)


# --- Processo (GET /processo/consultar/{numero}) --------------------------------


async def consultar_processo(numero: str) -> DadosProcesso:
    if not VERDE_JWT_TOKEN:
        logger.warn(MENSAGEM_MOCK, **contexto_atual())
        # Issue #51: só origem "SEEU" é resolvida pelo bot.
        if numero == "000000000":
            return {"encontrado": False}
        if numero == "0000000-00.0000.0.00.0000":
            return {"encontrado": True, "id": 999999, "origem": "e-Proc (mock)", "nomeAssunto": "Processo de Teste (mock)"}
        return {"encontrado": True, "id": 999999, "origem": "SEEU", "nomeAssunto": "Processo de Teste (mock)"}
    inicio = _agora_ms()
    url = f"{VERDE_API_URL}/processo/consultar/{_escapar(numero)}"
    resultado = await chamar_verde_com_retry("processo", _requisicao("GET", url, com_accept=True, ler_corpo=True))
    if not resultado.ok or resultado.res is None:
        await _fechar(resultado)
        return {"encontrado": False}
    corpo = _js.json_parse(resultado.res.content)
    _sucesso("processo", inicio)
    dados = _js.prop(corpo, "dados")
    if not _js.verdadeiro(dados) or _js.prop(dados, "id") is AUSENTE:
        return {"encontrado": False}
    saida: dict[str, Any] = {"encontrado": True}
    for chave in ("id", "origem", "instancia", "nomeAssunto", "nomeOrgaoJulgador", "movimentos"):
        _js.definir(saida, chave, _js.prop(dados, chave))
    return cast(DadosProcesso, saida)


# --- Pessoa (GET /pessoa?cpf=) ---------------------------------------------------


async def consultar_pessoa_por_cpf(cpf: str) -> DadosPessoa:
    if not VERDE_JWT_TOKEN:
        logger.warn(MENSAGEM_MOCK, **contexto_atual())
        if cpf == "00000000000":
            return {"encontrado": False}
        if cpf == "66666666666":
            return {"encontrado": False, "falhaInfra": True}
        return {
            "encontrado": True,
            "idPessoa": 999999,
            "nome": "Pessoa de Teste (mock)",
            "genero": "Feminino",
            "endereco": "Rua de Teste, 123 (mock)",
            "enderecoDetalhado": {"cep": "20000-000"},
        }
    inicio = _agora_ms()
    # 404 (não encontrado) e 422 (mais de uma pessoa) caem no mesmo encontrado: False.
    url = f"{VERDE_API_URL}/pessoa?cpf={_escapar(cpf)}"
    resultado = await chamar_verde_com_retry("pessoa", _requisicao("GET", url, com_accept=True, ler_corpo=True))
    if not resultado.ok or resultado.res is None:
        await _fechar(resultado)
        return cast(DadosPessoa, _com_falha_infra({"encontrado": False}, resultado.falha_infra))
    corpo = _js.json_parse(resultado.res.content)
    _sucesso("pessoa", inicio)
    dados = _js.prop(corpo, "dados")
    if not _js.verdadeiro(dados) or _js.prop(dados, "idPessoa") is AUSENTE:
        return {"encontrado": False}
    saida: dict[str, Any] = {"encontrado": True}
    for chave in ("idPessoa", "nome", "nomeSocial", "genero", "endereco", "enderecoDetalhado"):
        _js.definir(saida, chave, _js.prop(dados, chave))
    return cast(DadosPessoa, saida)


# --- CEP (GET /cep/{cep}) ---------------------------------------------------------


def _id_de_campo_cep(campo: Any) -> Any:
    # `campo && typeof campo === "object" ? campo.id : undefined`
    return _js.prop(campo, "id") if _js.verdadeiro(campo) and isinstance(campo, dict | list) else AUSENTE


def _nome_de_campo_cep(campo: Any) -> Any:
    return _js.prop(campo, "nome") if _js.verdadeiro(campo) and isinstance(campo, dict | list) else AUSENTE


async def consultar_cep(cep: str) -> DadosCep:
    if not VERDE_JWT_TOKEN:
        logger.warn(MENSAGEM_MOCK, **contexto_atual())
        # [^0-9], e não \D: em Python, \D casa dígitos Unicode como "٠".
        if re.sub(r"[^0-9]", "", cep) == "00000000":
            return {"encontrado": False}
        # Lida a cada chamada (interruptor de teste), como em develop.
        if os.environ.get("MOCK_CEP_INCOMPLETO") == "true":
            return {"encontrado": True, "idUf": 19, "uf": "RJ"}
        return {
            "encontrado": True,
            "idUf": 19,
            "idBairro": 9948,
            "idMunicipio": 3643,
            "uf": "RJ",
            "bairro": "Bairro de Teste (mock)",
            "municipio": "Rio de Janeiro (mock)",
            "logradouro": "Rua de Teste (mock)",
        }
    inicio = _agora_ms()
    url = f"{VERDE_API_URL}/cep/{_escapar(cep)}"
    resultado = await chamar_verde_com_retry("cep", _requisicao("GET", url, com_accept=True, ler_corpo=True))
    if not resultado.ok or resultado.res is None:
        await _fechar(resultado)
        return {"encontrado": False}
    corpo = _js.json_parse(resultado.res.content)
    _sucesso("cep", inicio)
    dados = _js.prop(corpo, "dados")
    # Só `!corpo.dados`: aqui, `dados: {}` conta como encontrado, sem campos.
    if not _js.verdadeiro(dados):
        return {"encontrado": False}
    saida: dict[str, Any] = {"encontrado": True}
    _js.definir(saida, "idUf", _id_de_campo_cep(_js.prop(dados, "uf")))
    _js.definir(saida, "idBairro", _id_de_campo_cep(_js.prop(dados, "bairro")))
    _js.definir(saida, "idMunicipio", _id_de_campo_cep(_js.prop(dados, "municipio")))
    _js.definir(saida, "uf", _js.opt(_js.prop(dados, "uf"), "sigla"))
    _js.definir(saida, "bairro", _nome_de_campo_cep(_js.prop(dados, "bairro")))
    _js.definir(saida, "municipio", _nome_de_campo_cep(_js.prop(dados, "municipio")))
    # `logradouro ?? undefined`: null vira ausente.
    logradouro = _js.prop(dados, "logradouro")
    _js.definir(saida, "logradouro", AUSENTE if logradouro is None else logradouro)
    return cast(DadosCep, saida)


# --- Órgãos de violência doméstica ----------------------------------------------


def _orgaos(lista: Any) -> list[OrgaoAtendimento]:
    """`lista.map(o => ({id: o.id ?? 0, nome: o.nome ?? "", enderecos: o.enderecos}))`.
    Lança TypeError, como em develop, se `lista` não for array ou se um item for null."""
    if not isinstance(lista, list):
        raise TypeError("corpo.dados.map is not a function")
    orgaos: list[OrgaoAtendimento] = []
    for o in lista:
        orgao: dict[str, Any] = {"id": _js.coalesce(_js.prop(o, "id"), 0), "nome": _js.coalesce(_js.prop(o, "nome"), "")}
        _js.definir(orgao, "enderecos", _js.prop(o, "enderecos"))
        orgaos.append(cast(OrgaoAtendimento, orgao))
    return orgaos


def _contactar_crc(mensagem: Any) -> OrgaosViolenciaDomestica:
    saida: dict[str, Any] = {"encontrado": False, "orgaos": [], "contactarCrc": True}
    _js.definir(saida, "mensagemCrc", mensagem)
    return cast(OrgaosViolenciaDomestica, saida)


async def consultar_orgaos_violencia_domestica(indicacao_ro: bool, id_pessoa: int) -> OrgaosViolenciaDomestica:
    """O Verde resolve a regra de órgão pelo endereço cadastrado da pessoa. Com
    RO: Juizado de VD ou DP única; sem RO: NUDEM, núcleo de 1º atendimento ou DP
    única. Devolve em ordem de prioridade."""
    if not VERDE_JWT_TOKEN:
        logger.warn(MENSAGEM_MOCK, **contexto_atual())
        if indicacao_ro and id_pessoa == 0:
            return {"encontrado": False, "orgaos": [], "contactarCrc": True, "mensagemCrc": MENSAGEM_CRC_MOCK}
        orgao: OrgaoAtendimento = (
            {
                "id": 274,
                "nome": "DP de Defesa da Mulher junto ao Juizado de Violência Doméstica (mock)",
                "enderecos": [{"municipio": "Município de Teste", "idLocalAtendimento": 222}],
            }
            if indicacao_ro
            else {
                "id": 525,
                "nome": "Coordenação de Defesa dos Direitos da Mulher (mock)",
                "enderecos": [{"municipio": "Rio de Janeiro (mock)", "idLocalAtendimento": 1233}],
            }
        )
        return {"encontrado": True, "orgaos": [orgao]}
    inicio = _agora_ms()
    # Booleano como "true"/"false", como o template literal de develop; nunca
    # `params=` do httpx.
    url = (
        f"{VERDE_API_URL}/orgao/violencia-domestica?indicacaoRO={_js.texto_template(indicacao_ro)}&idPessoa={_js.texto_template(id_pessoa)}"
    )
    resultado = await chamar_verde_com_retry("orgao-violencia-domestica", _requisicao("GET", url, com_accept=True, ler_corpo=True))
    if not resultado.ok or resultado.res is None:
        await _fechar(resultado)
        return {"encontrado": False, "orgaos": []}
    corpo = _js.json_parse(resultado.res.content)
    _sucesso("orgao-violencia-domestica", inicio)
    # "CONTACTAR_CRC": "não achei nada, ligue 129" (só com RO). Igualdade estrita.
    if _js.prop(corpo, "codigo") == "CONTACTAR_CRC":
        return _contactar_crc(_js.prop(corpo, "mensagem"))
    orgaos = _orgaos(_js.coalesce(_js.prop(corpo, "dados"), []))
    return {"encontrado": len(orgaos) > 0, "orgaos": orgaos}


async def consultar_plantao_vigente() -> list[Plantao]:
    """Lista vazia = fora de horário de plantão."""
    if not VERDE_JWT_TOKEN:
        logger.warn(MENSAGEM_MOCK, **contexto_atual())
        if os.environ.get("MOCK_PLANTAO_VIGENTE") == "true":
            return [{"id": 1, "tipo": "Violência Doméstica (mock)"}]
        return []
    inicio = _agora_ms()
    resultado = await chamar_verde_com_retry(
        "plantao-vigente", _requisicao("GET", f"{VERDE_API_URL}/plantao/vigente", com_accept=True, ler_corpo=True)
    )
    if not resultado.ok or resultado.res is None:
        await _fechar(resultado)
        return []
    corpo = _js.json_parse(resultado.res.content)
    _sucesso("plantao-vigente", inicio)
    lista = _js.coalesce(_js.prop(corpo, "dados"), [])
    if not isinstance(lista, list):
        raise TypeError("(corpo.dados ?? []).filter is not a function")
    plantoes: list[Plantao] = []
    # `filter(p => p.id !== undefined)`: mantém id null (chave presente).
    for p in lista:
        if _js.prop(p, "id") is AUSENTE:
            continue
        plantao: dict[str, Any] = {"id": _js.prop(p, "id")}
        _js.definir(plantao, "tipo", _js.prop(p, "tipo"))
        plantoes.append(cast(Plantao, plantao))
    return plantoes


async def consultar_orgaos_plantao_violencia_domestica(id_plantao: list[int | None], id_assistido: int) -> OrgaosViolenciaDomestica:
    if not VERDE_JWT_TOKEN:
        logger.warn(MENSAGEM_MOCK, **contexto_atual())
        if id_assistido == 0:
            return {"encontrado": False, "orgaos": [], "contactarCrc": True, "mensagemCrc": MENSAGEM_CRC_MOCK}
        return {
            "encontrado": True,
            "orgaos": [
                {
                    "id": 999,
                    "nome": "Órgão de Plantão (mock)",
                    "enderecos": [{"municipio": "Rio de Janeiro (mock)", "idLocalAtendimento": 333}],
                }
            ],
        }
    inicio = _agora_ms()
    # idPlantao repetível; um id null vira "idPlantao=null", como em develop.
    query = "&".join(f"idPlantao={_js.texto_template(i)}" for i in id_plantao)
    url = f"{VERDE_API_URL}/orgao/plantao/violencia-domestica?{query}&idAssistido={_js.texto_template(id_assistido)}"
    resultado = await chamar_verde_com_retry("orgao-plantao-violencia-domestica", _requisicao("GET", url, com_accept=True, ler_corpo=True))
    if not resultado.ok or resultado.res is None:
        await _fechar(resultado)
        return {"encontrado": False, "orgaos": []}
    # Aqui o log de sucesso vem ANTES do parse (verde.ts:560).
    _sucesso("orgao-plantao-violencia-domestica", inicio)
    corpo = _js.json_parse(resultado.res.content)
    # Qualquer `codigo` não vazio é erro (ex.: REQUISICAO_INVALIDA), mesma UX do CONTACTAR_CRC.
    if _js.verdadeiro(_js.prop(corpo, "codigo")):
        return _contactar_crc(_js.prop(corpo, "mensagem"))
    # O Swagger documenta `dados` como objeto único aqui; normaliza os dois formatos.
    bruto = _js.prop(corpo, "dados")
    lista = bruto if isinstance(bruto, list) else ([bruto] if _js.verdadeiro(bruto) else [])
    orgaos = _orgaos(lista)
    return {"encontrado": len(orgaos) > 0, "orgaos": orgaos}


# --- Encaminhamento (POST /encaminhamento/encaminhar) -----------------------------


class DadosEncaminhamento(TypedDict):
    idPessoa: int
    idOrgao: int
    idLocalAtendimento: NotRequired[int]
    urgente: bool


def _mensagem_de_erro(corpo_erro: Any, resultado: ResultadoChamadaVerde) -> Any:
    """`corpoErro?.mensagem ?? (falhaInfra ? "…infra esgotada" : `HTTP ${res?.status}`)`."""
    status = AUSENTE if resultado.res is None else resultado.res.status_code
    padrao = "falha na chamada ao Verde (infra esgotada)" if resultado.falha_infra else f"HTTP {_js.texto_template(status)}"
    return _js.coalesce(_js.opt(corpo_erro, "mensagem"), padrao)


async def _registrar_falha_de_escrita(chamada: str, resultado: ResultadoChamadaVerde, inicio: int) -> Any:
    corpo_erro = AUSENTE if resultado.res is None else await _ler_json_ou_vazio(resultado.res)
    campos: dict[str, Any] = dict(contexto_atual())
    _js.definir(campos, "corpo", corpo_erro)
    if resultado.res is not None:
        campos["status"] = resultado.res.status_code
    logger.error(
        f"[verde] {chamada}: falhou, corpo de erro da Verde",
        **campos,
        evento="verde_chamada",
        chamada=chamada,
        resultado="nao_ok",
        duracaoMs=_agora_ms() - inicio,
    )
    return corpo_erro


async def criar_encaminhamento_violencia_domestica(dados: DadosEncaminhamento) -> ResultadoEncaminhamento:
    """Cria o encaminhamento de verdade no Verde. preferenciaAtendimento sempre
    "Remoto" (é chatbot); idAssunto não é enviado (confirmado com o Verde)."""
    if not VERDE_JWT_TOKEN:
        logger.warn(MENSAGEM_MOCK, **contexto_atual())
        if os.environ.get("MOCK_ENCAMINHAMENTO_FALHA") == "true":
            return {"sucesso": False, "erro": "falha simulada (mock)"}
        return {"sucesso": True, "id": 999999}
    inicio = _agora_ms()
    corpo_envio: dict[str, Any] = {"idPessoa": dados["idPessoa"], "idOrgao": dados["idOrgao"]}
    if "idLocalAtendimento" in dados:
        corpo_envio["idLocalAtendimento"] = dados["idLocalAtendimento"]
    corpo_envio["urgencia"] = dados["urgente"]
    corpo_envio["preferenciaAtendimento"] = "Remoto"
    corpo_envio["fluxoEncaminhamento"] = "VIOLENCIA_DOMESTICA"
    if _js.verdadeiro(dados["urgente"]):
        corpo_envio["motivoUrgencia"] = "Violência doméstica com Boletim de Ocorrência registrado"
    resultado = await chamar_verde_com_retry(
        "encaminhamento",
        _requisicao("POST", f"{VERDE_API_URL}/encaminhamento/encaminhar", com_accept=True, corpo=corpo_envio, ler_corpo=False),
    )
    if not resultado.ok or resultado.res is None:
        corpo_erro = await _registrar_falha_de_escrita("encaminhamento", resultado, inicio)
        await _fechar(resultado)
        return {"sucesso": False, "erro": _mensagem_de_erro(corpo_erro, resultado)}
    corpo = await _ler_json_ou_vazio(resultado.res)
    _sucesso("encaminhamento", inicio, corpo=corpo)
    saida: dict[str, Any] = {"sucesso": True}
    _js.definir(saida, "id", _js.opt(_js.prop(corpo, "dados"), "id"))
    return cast(ResultadoEncaminhamento, saida)


# --- Cadastro de pessoa (POST /pessoa) -----------------------------------------------


class EnderecoCadastroPessoa(TypedDict, total=False):
    logradouro: str
    numero: str
    complemento: str
    cep: str
    bairro: str
    municipio: str
    uf: str


class DadosCadastroPessoa(TypedDict):
    nome: str
    cpf: str
    dataNascimento: str
    # Issue #176: opcional; sem ele, o cadastro vai sem endereço.
    endereco: NotRequired[EnderecoCadastroPessoa]


async def cadastrar_pessoa(dados: DadosCadastroPessoa) -> ResultadoCadastroPessoa:
    """Issue #171: cria o cadastro (CPF válido e ainda não cadastrado), só com os
    campos obrigatórios e, desde a #176, o endereço."""
    if not VERDE_JWT_TOKEN:
        logger.warn(MENSAGEM_MOCK, **contexto_atual())
        if os.environ.get("MOCK_CADASTRO_FALHA") == "true":
            return {"sucesso": False, "erro": "falha simulada (mock)"}
        return {"sucesso": True, "idPessoa": 888888}
    inicio = _agora_ms()
    corpo_envio: dict[str, Any] = {"nome": dados["nome"], "cpf": dados["cpf"], "dtNascimento": dados["dataNascimento"]}
    endereco = cast(Mapping[str, Any], dados).get("endereco", AUSENTE)
    if _js.verdadeiro(endereco):
        corpo_envio["endereco"] = endereco
    resultado = await chamar_verde_com_retry(
        "cadastroPessoa", _requisicao("POST", f"{VERDE_API_URL}/pessoa", com_accept=True, corpo=corpo_envio, ler_corpo=False)
    )
    if not resultado.ok or resultado.res is None:
        corpo_erro = await _registrar_falha_de_escrita("cadastroPessoa", resultado, inicio)
        await _fechar(resultado)
        return {"sucesso": False, "erro": _mensagem_de_erro(corpo_erro, resultado)}
    corpo = await _ler_json_ou_vazio(resultado.res)
    _sucesso("cadastroPessoa", inicio, corpo=corpo)
    id_pessoa = _js.opt(_js.prop(corpo, "dados"), "idPessoa")
    if id_pessoa is AUSENTE:
        return {"sucesso": False, "erro": "Verde não devolveu idPessoa"}
    return {"sucesso": True, "idPessoa": id_pessoa}
