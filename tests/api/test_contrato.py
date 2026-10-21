"""Contrato HTTP com a Tykhe: as fixtures gravadas do servidor TypeScript real
(develop @ 1157a6d, `tests/fixtures/contrato/`), reproduzidas byte a byte.

Cada instância (A a E) roda numa aplicação nova, com as variáveis de ambiente da
gravação (NODE_ENV vira APP_ENV), e as fixtures são reproduzidas na ordem do
`indice.json`, porque algumas dependem do estado deixado pelas anteriores.

Compara:
- status, content-type, Location e o corpo bruto (no 500, tudo menos o valor de
  `message`, #210);
- as linhas de log de cada requisição (as que têm `reqId`), sem `time`, `pid`,
  `hostname`, `reqId`, `responseTime`, o endereço do cliente e o `stack`.

Módulo api (#246): as 31 fixtures do PR 1 e as 19 do PR 2 (`GET /atendimentos/:chatId`,
`POST /atendimentos/respostas` e `/webhook/whatsapp`), as 50.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from maria.app import criar_app

RAIZ = Path("tests/fixtures/contrato")
CHAVE = "chave-de-captura"
VARIAVEIS_DE_INSTANCIA = ("MOCK_CLASSIFICACAO_FLOWID", "MOCK_CLASSIFICACAO_FLOWIDS", "TTL_INATIVIDADE_HORAS", "WHATSAPP_VERIFY_TOKEN")


def _fixtures() -> list[dict[str, Any]]:
    indice = json.loads((RAIZ / "indice.json").read_text(encoding="utf-8"))
    return [json.loads((RAIZ / "http" / f"{i['nome']}.json").read_text(encoding="utf-8")) for i in indice]


FIXTURES = _fixtures()
INSTANCIAS: dict[str, list[dict[str, Any]]] = {}
for _f in FIXTURES:
    INSTANCIAS.setdefault(_f["instancia"]["nome"], []).append(_f)


def test_as_50_fixtures_entram() -> None:
    assert len(FIXTURES) == 50


def _cabecalhos(f: dict[str, Any]) -> dict[str, str]:
    return {k: (f"Bearer {CHAVE}" if v == "Bearer <API_KEY>" else v) for k, v in f["requisicao"]["headers"].items()}


def _conteudo(f: dict[str, Any]) -> bytes | None:
    req = f["requisicao"]
    if "corpoBruto" in req:
        return str(req["corpoBruto"]).encode("utf-8")
    if "corpo" in req:
        return json.dumps(req["corpo"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return None


_VARIAVEIS_LOG = {"time", "pid", "hostname", "reqId", "responseTime"}


def _normalizar(linha: dict[str, Any], status_500: bool) -> dict[str, Any]:
    out = {k: v for k, v in linha.items() if k not in _VARIAVEIS_LOG}
    if isinstance(out.get("req"), dict):
        out["req"] = {k: v for k, v in out["req"].items() if k not in ("remoteAddress", "remotePort", "host")}
    if isinstance(out.get("err"), dict):
        out["err"] = {k: v for k, v in out["err"].items() if k != "stack"}
        if status_500:
            out["err"].pop("message", None)
            out.pop("msg", None)
    return out


def _por_requisicao(linhas: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grupos: dict[str, list[dict[str, Any]]] = {}
    for linha in linhas:
        if "reqId" in linha:
            grupos.setdefault(linha["reqId"], []).append(linha)
    return list(grupos.values())


def _logs_da_gravacao(instancia: str) -> dict[str, list[dict[str, Any]]]:
    """Linhas de log de cada fixture da instância, pelo nome.

    O script de captura consulta o /health até o servidor subir, então há
    requisições na gravação que não são fixtures. O alinhamento é pela ordem e
    pelo método + URL de cada requisição."""
    texto = (RAIZ / "logs" / f"{instancia}.ndjson").read_text(encoding="utf-8")
    grupos = _por_requisicao([json.loads(x) for x in texto.splitlines() if x.strip()])
    por_nome: dict[str, list[dict[str, Any]]] = {}
    i = 0
    for f in INSTANCIAS[instancia]:
        alvo = (f["requisicao"]["metodo"], f["requisicao"]["caminho"])
        while i < len(grupos) and (grupos[i][0].get("req", {}).get("method"), grupos[i][0].get("req", {}).get("url")) != alvo:
            i += 1
        assert i < len(grupos), f"sem linhas de log gravadas para {f['nome']}"
        por_nome[f["nome"]] = grupos[i]
        i += 1
    return por_nome


@pytest.fixture
async def instancia(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    nome: str = request.param
    env = dict(INSTANCIAS[nome][0]["instancia"]["env"])
    for variavel in VARIAVEIS_DE_INSTANCIA:
        monkeypatch.delenv(variavel, raising=False)
    monkeypatch.setenv("APP_ENV", env.pop("NODE_ENV"))
    for chave, valor in env.items():
        monkeypatch.setenv(chave, valor)
    monkeypatch.setenv("API_KEY", CHAVE)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VERDE_JWT_TOKEN", raising=False)
    app = criar_app(pre_aquecer=False)
    async with app.router.lifespan_context(app):
        transporte = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transporte, base_url="http://127.0.0.1:3001") as cliente:
            yield cliente


@pytest.mark.parametrize("instancia", sorted(INSTANCIAS), indirect=True)
async def test_fixtures_byte_a_byte(
    instancia: httpx.AsyncClient, request: pytest.FixtureRequest, capsys: pytest.CaptureFixture[str]
) -> None:
    nome: str = request.node.callspec.params["instancia"]
    gravados = _logs_da_gravacao(nome)
    falhas: list[str] = []
    for f in INSTANCIAS[nome]:
        capsys.readouterr()
        req = f["requisicao"]
        r = await instancia.request(req["metodo"], req["caminho"], headers=_cabecalhos(f), content=_conteudo(f))
        esperado = f["resposta"]
        if r.status_code != esperado["status"]:
            falhas.append(f"{f['nome']}: status {r.status_code} != {esperado['status']}: {r.text}")
            continue
        if r.headers.get("content-type") != esperado["contentType"]:
            falhas.append(f"{f['nome']}: content-type {r.headers.get('content-type')} != {esperado['contentType']}")
        if r.headers.get("location") != esperado["location"]:
            falhas.append(f"{f['nome']}: location {r.headers.get('location')} != {esperado['location']}")
        if esperado["status"] == 500:
            obtido, esperado_corpo = json.loads(r.text), json.loads(esperado["corpoBruto"])
            obtido.pop("message"), esperado_corpo.pop("message")
            if list(obtido.items()) != list(esperado_corpo.items()):
                falhas.append(f"{f['nome']}: corpo {r.text} != {esperado['corpoBruto']}")
        elif r.text != esperado["corpoBruto"]:
            falhas.append(f"{f['nome']}:\n    obtido:   {r.text}\n    esperado: {esperado['corpoBruto']}")

        linhas = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{")]
        meus = _por_requisicao(linhas)
        deles = gravados[f["nome"]]
        status_500 = esperado["status"] == 500
        obtidos = [_normalizar(x, status_500) for x in (meus[0] if meus else [])]
        esperados = [_normalizar(x, status_500) for x in deles]
        if obtidos != esperados:
            falhas.append(
                f"{f['nome']}: log\n    obtido:   {json.dumps(obtidos, ensure_ascii=False)}\n"
                f"    esperado: {json.dumps(esperados, ensure_ascii=False)}"
            )
    assert not falhas, "\n".join(falhas)
