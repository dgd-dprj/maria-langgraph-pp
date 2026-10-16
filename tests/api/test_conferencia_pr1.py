"""Conferência diferencial do PR 1 do api, como teste de regressão.

`tests/fixtures/contrato/conferencia-api-pr1/develop.json` guarda as respostas do
app real de develop @ 1157a6d (`executor-develop.mts`, por inject) para os 310
cenários de `cenarios.json` (`gerar_cenarios.py`): caminhos principais e a
varredura da entrada vinda de fora (cada campo de corpo com null, texto, número,
booleano, objeto, lista, vazio, ausente, inteiro grande; content-type, corpo,
autenticação). O teste roda os mesmos cenários, na mesma ordem e numa única
aplicação, e compara status, content-type, Location e o corpo byte a byte. O UUID
gerado (chatId ausente em APP_ENV=test) é normalizado.

As linhas de log de cada requisição foram comparadas na execução da conferência
(PR #246); aqui ficam as respostas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from maria.app import criar_app

RAIZ = Path("tests/fixtures/contrato/conferencia-api-pr1")
CENARIOS: list[dict[str, Any]] = json.loads((RAIZ / "cenarios.json").read_text(encoding="utf-8"))
DEVELOP: list[dict[str, Any]] = json.loads((RAIZ / "develop.json").read_text(encoding="utf-8"))
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_FIXOS = {"3df874f2-675a-4c43-9ec7-480f7c702f50", "cabb2495-4e12-4f4a-9956-3d20649059bc", "00000000-0000-4000-8000-000000000000"}

# O httpx trata "//health" como referência de rede (host "health"). Conferido por
# ASGI cru: o Python responde "Route GET://health not found", igual a develop.
CLIENTE_DE_TESTE = {"dupla_barra"}

# Divergências, com o motivo. O teste confere o comportamento do Python.
DIVERGENCIAS = {
    # Decisão 1 do fluxos (#241): o colapso de null e undefined em encaminhamentoId.
    # Além do desfecho já registrado, develop devolve metadados.encaminhamentoId: null
    # e o Python omite a chave.
    "dados_encaminhamentoId_null": "colapso null/undefined em encaminhamentoId (fluxos, decisão 1)",
}
# dadosConhecidos.tokensGastos fora do formato {input, output, total} numéricos:
# develop aceita e zera ou corrompe a contagem em silêncio (o NaN da soma vira null
# no checkpoint JSON e depois 0; "0x0" vira 0 pelo Number()), e conclui com 200. O
# Python lança TypeError na criação: 500. Proposta D-5 da spec 07 (mesmo molde do
# D-1 do fluxos). Com null, os dois lados dão 500 e só a mensagem difere (#210).
TOKENS_500 = {
    c["nome"] for c in CENARIOS if c["nome"].startswith(("dados_tokensGastos_", "dados_tokens_")) or c["nome"] == "criar_tokens_null_500"
}


def _norm(texto: str | None) -> str | None:
    if texto is None:
        return None
    return _UUID.sub(lambda m: m.group(0) if m.group(0) in _FIXOS else "<uuid>", texto)


@pytest.fixture
async def cliente_conferencia(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("API_KEY", "chave-conferencia")
    for variavel in (
        "DATABASE_URL",
        "VERDE_JWT_TOKEN",
        "MOCK_CLASSIFICACAO_FLOWID",
        "MOCK_CLASSIFICACAO_FLOWIDS",
        "ORQUESTRADOR_INCLUIR_PLANEJADOS",
        "TTL_INATIVIDADE_HORAS",
    ):
        monkeypatch.delenv(variavel, raising=False)
    app = criar_app(pre_aquecer=False)
    async with app.router.lifespan_context(app):
        transporte = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transporte, base_url="http://localhost:80") as cliente:
            yield cliente


def test_conferencia_tem_310_cenarios_e_as_saidas_de_develop() -> None:
    assert len(CENARIOS) == len(DEVELOP) == 310
    assert [c["nome"] for c in CENARIOS] == [d["nome"] for d in DEVELOP]


async def test_conferencia_diferencial_contra_develop(cliente_conferencia: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    falhas: list[str] = []
    for c, d in zip(CENARIOS, DEVELOP, strict=True):
        env = {"APP_ENV": c["env"].get("APP_ENV", "test"), **{k: v for k, v in c["env"].items() if k != "APP_ENV"}}
        with monkeypatch.context() as m:
            for k, v in env.items():
                m.setenv(k, v)
            conteudo = None if c["corpo"] is None else c["corpo"].encode("utf-8")
            r = await cliente_conferencia.request(c["metodo"], c["caminho"], headers=c["headers"], content=conteudo)
        nome = c["nome"]
        if nome in CLIENTE_DE_TESTE:
            continue
        if nome in TOKENS_500:
            if r.status_code != 500:
                falhas.append(f"{nome}: esperado 500 (D-5), veio {r.status_code}")
            continue
        obtido = (r.status_code, r.headers.get("content-type"), _norm(r.headers.get("location")), _norm(r.content.decode("utf-8")))
        esperado = (d["status"], d["contentType"], _norm(d["location"]), _norm(d["corpo"]))
        if nome in DIVERGENCIAS:
            if obtido == esperado:
                falhas.append(f"{nome}: a divergência registrada sumiu ({DIVERGENCIAS[nome]})")
            continue
        if obtido != esperado:
            falhas.append(f"{nome}:\n    python:  {obtido}\n    develop: {esperado}")
    assert not falhas, "\n".join(falhas)
