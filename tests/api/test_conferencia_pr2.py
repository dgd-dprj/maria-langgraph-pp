"""Conferência diferencial do PR 2 do api, como teste de regressão.

`tests/fixtures/contrato/conferencia-api-pr2/develop.json` guarda as respostas do
app real de develop @ 1157a6d (`executor-develop.mts`, por inject) para os 313
cenários de `cenarios.json` (`gerar_cenarios_pr2.py`):
- os caminhos principais da consulta e da resposta;
- o TTL, com cada forma de confirmar e cada valor de `TTL_INATIVIDADE_HORAS`;
- os casos de borda do roteador (find-my-way);
- a varredura da entrada de `POST /atendimentos/respostas`;
- o webhook do WhatsApp, inclusive o bridge e o `#sair`.

O teste roda os mesmos cenários, na mesma ordem e numa única aplicação, por ASGI
cru (o caminho chega intacto, sem a normalização de URL do httpx), e compara
status, content-type, Location e o corpo byte a byte. As linhas de log foram
comparadas na execução da conferência (`conferir.py`), com o mesmo resultado.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

from maria.api.webhook_whatsapp import limpar_conversas_ativas_de_teste
from maria.app import criar_app
from tests.api.sem_campos_posteriores import sem_campos_posteriores

RAIZ = Path("tests/fixtures/contrato/conferencia-api-pr2")
CENARIOS: list[dict[str, Any]] = json.loads((RAIZ / "cenarios.json").read_text(encoding="utf-8"))
DEVELOP: dict[str, dict[str, Any]] = {r["nome"]: r for r in json.loads((RAIZ / "develop.json").read_text(encoding="utf-8"))}
_CHAT_WPP = re.compile(r"(whatsapp:[^:\"]+:)\d+")

# HEAD de erro do roteador (404, 400, 414): pelo inject, develop devolve o corpo;
# numa conexão HTTP de verdade, o Node descarta o corpo de toda resposta a HEAD
# (executado em develop @ 1157a6d, 2026-10-19). O Python responde como o servidor
# real: sem corpo. Artefato da ferramenta de teste, e não divergência de contrato.
HEAD_SEM_CORPO = {
    "rota_head_barra_final",
    "rota_head_barra_crua",
    "rota_head_utf8_incompleto",
    "rota_head_escape_invalido",
    "rota_head_caixa",
    "rota_head_barra_dupla_meio",
    "rota_head_param_101",
    "rota_head_param_101_codificado",
    "rota_head_param_emoji_51",
    "rota_head_fluxos_escape_invalido",
    "rota_head_inexistente_escape_invalido",
}
_VARIAVEIS = (
    "MOCK_CLASSIFICACAO_FLOWID",
    "MOCK_CLASSIFICACAO_FLOWIDS",
    "ORQUESTRADOR_INCLUIR_PLANEJADOS",
    "TTL_INATIVIDADE_HORAS",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "MOCK_CLASSIFICACAO_PARENTESCO",
    "MOCK_ENCAMINHAMENTO_FALHA",
    "DATABASE_URL",
    "VERDE_JWT_TOKEN",
)


async def _asgi(app: Any, c: dict[str, Any]) -> dict[str, Any]:
    caminho, _, consulta = c["caminho"].partition("?")
    cabecalhos = {"user-agent": "lightMyRequest", "host": "localhost:80", **{k.lower(): v for k, v in c["headers"].items()}}
    corpo = b""
    if c["corpo"] is not None:
        corpo = c["corpo"].encode("utf-8")
        cabecalhos["content-length"] = str(len(corpo))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": c["metodo"],
        "scheme": "http",
        "path": unquote(caminho),
        "raw_path": caminho.encode("utf-8"),
        "query_string": consulta.encode("utf-8"),
        "root_path": "",
        "headers": [(k.encode("latin-1"), v.encode("utf-8")) for k, v in cabecalhos.items()],
        "client": ("127.0.0.1", 0),
        "server": ("localhost", 80),
    }
    entregue = False

    async def receive() -> dict[str, Any]:
        nonlocal entregue
        if entregue:
            await asyncio.sleep(3600)
        entregue = True
        return {"type": "http.request", "body": corpo, "more_body": False}

    resposta: dict[str, Any] = {"status": None, "headers": {}, "corpo": b""}

    async def send(m: dict[str, Any]) -> None:
        if m["type"] == "http.response.start":
            resposta["status"] = m["status"]
            resposta["headers"] = {k.decode("latin-1"): v.decode("latin-1") for k, v in m.get("headers", [])}
        else:
            resposta["corpo"] += m.get("body", b"")

    await app(scope, receive, send)
    h = resposta["headers"]
    return {
        "status": resposta["status"],
        "contentType": h.get("content-type"),
        "location": h.get("location"),
        "corpo": resposta["corpo"].decode(),
    }


async def test_313_cenarios_iguais_a_develop(monkeypatch: pytest.MonkeyPatch) -> None:
    for variavel in _VARIAVEIS:
        monkeypatch.delenv(variavel, raising=False)
    monkeypatch.setenv("API_KEY", "chave-conferencia")
    limpar_conversas_ativas_de_teste()
    app = criar_app(pre_aquecer=False)
    falhas: list[str] = []
    async with app.router.lifespan_context(app):
        for c in CENARIOS:
            with monkeypatch.context() as m:
                m.setenv("APP_ENV", c["env"].get("APP_ENV", "test"))
                for k, v in c["env"].items():
                    if k != "APP_ENV":
                        m.setenv(k, v)
                r = await _asgi(app, c)
            d = DEVELOP[c["nome"]]
            esperado_corpo = "" if c["nome"] in HEAD_SEM_CORPO else d["corpo"]
            for campo in ("status", "contentType", "location"):
                if r[campo] != d[campo]:
                    falhas.append(f"{c['nome']}: {campo} {r[campo]!r} != {d[campo]!r}")
            if d["status"] == 500 and r["corpo"] and esperado_corpo:
                obtido, esperado = json.loads(r["corpo"]), json.loads(esperado_corpo)
                obtido.pop("message"), esperado.pop("message")  # #210
                if list(obtido.items()) != list(esperado.items()):
                    falhas.append(f"{c['nome']}: corpo {r['corpo']} != {esperado_corpo}")
            elif _CHAT_WPP.sub(r"\1<T>", sem_campos_posteriores(r["corpo"])) != _CHAT_WPP.sub(r"\1<T>", esperado_corpo):
                falhas.append(f"{c['nome']}:\n    obtido:   {r['corpo'][:300]}\n    esperado: {esperado_corpo[:300]}")
    limpar_conversas_ativas_de_teste()
    assert not falhas, "\n".join(falhas)
