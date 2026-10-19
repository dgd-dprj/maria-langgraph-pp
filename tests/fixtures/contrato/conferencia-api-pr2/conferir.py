# mypy: ignore-errors
# ruff: noqa
# Script de conferência (não é teste nem código da aplicação), guardado para repetir a conferência.
"""Conferência diferencial do PR 2 do api: lado Python e comparação com develop.

Uso (na raiz do repositório):
  uv run python tests/fixtures/contrato/conferencia-api-pr2/conferir.py \\
      cenarios.json develop.json develop.ndjson [python.json]

Roda os cenários na mesma ordem, numa única aplicação, por ASGI cru (o caminho
chega como veio, sem a normalização de URL do httpx) e com os cabeçalhos que o
`app.inject` de develop manda (host, user-agent e content-length). Compara status,
content-type, Location, corpo byte a byte e as linhas de log de cada cenário.

Normalização, nos dois lados:
- o timestamp do chatId do bridge (`whatsapp:<número>:<ms>`);
- nos logs: time, pid, hostname, reqId, responseTime, endereço do cliente, host e
  o stack; no 500, a mensagem do erro (#210).
"""

import asyncio
import contextlib
import io
import json
import os
import re
import sys
from urllib.parse import unquote

CENARIOS, DEVELOP, DEVELOP_LOGS = sys.argv[1:4]
SAIDA_PY = sys.argv[4] if len(sys.argv) > 4 else None

os.environ.update({"APP_ENV": "test", "API_KEY": "chave-conferencia"})
for k in (
    "DATABASE_URL",
    "VERDE_JWT_TOKEN",
    "MOCK_CLASSIFICACAO_FLOWID",
    "MOCK_CLASSIFICACAO_FLOWIDS",
    "ORQUESTRADOR_INCLUIR_PLANEJADOS",
    "TTL_INATIVIDADE_HORAS",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "MOCK_CLASSIFICACAO_PARENTESCO",
    "MOCK_ENCAMINHAMENTO_FALHA",
):
    os.environ.pop(k, None)

from maria.app import criar_app  # noqa: E402

_WPP = re.compile(r"(whatsapp:[^:\"]+:)\d+")
_LOG_FORA = {"time", "pid", "hostname", "reqId", "responseTime"}


def _norm_texto(t):
    return _WPP.sub(r"\1<T>", t) if isinstance(t, str) else t


def _norm_log(linha, status_500):
    out = {k: v for k, v in linha.items() if k not in _LOG_FORA}
    if isinstance(out.get("req"), dict):
        out["req"] = {k: v for k, v in out["req"].items() if k not in ("remoteAddress", "remotePort", "host")}
    if isinstance(out.get("err"), dict):
        out["err"] = {k: v for k, v in out["err"].items() if k != "stack"}
        if status_500:
            out["err"].pop("message", None)
            out.pop("msg", None)
    return json.loads(_norm_texto(json.dumps(out, ensure_ascii=False)))


async def _asgi(app, c):
    caminho, _, consulta = c["caminho"].partition("?")
    cab = {"user-agent": "lightMyRequest", "host": "localhost:80"}
    cab.update({k.lower(): v for k, v in c["headers"].items()})
    corpo = b""
    if c["corpo"] is not None:
        corpo = c["corpo"].encode("utf-8")
        cab["content-length"] = str(len(corpo))
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
        "headers": [(k.encode("latin-1"), v.encode("utf-8")) for k, v in cab.items()],
        "client": ("127.0.0.1", 0),
        "server": ("localhost", 80),
    }
    enviado = False

    async def receive():
        nonlocal enviado
        if enviado:
            await asyncio.sleep(3600)
        enviado = True
        return {"type": "http.request", "body": corpo, "more_body": False}

    resposta = {"status": None, "headers": {}, "corpo": b""}

    async def send(m):
        if m["type"] == "http.response.start":
            resposta["status"] = m["status"]
            resposta["headers"] = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in m.get("headers", [])}
        elif m["type"] == "http.response.body":
            resposta["corpo"] += m.get("body", b"")

    await app(scope, receive, send)
    h = resposta["headers"]
    return {
        "nome": c["nome"],
        "status": resposta["status"],
        "contentType": h.get("content-type"),
        "location": h.get("location"),
        "corpo": resposta["corpo"].decode("utf-8"),
    }


def _logs_develop():
    grupos, atual = {}, None
    for linha in open(DEVELOP_LOGS, encoding="utf-8"):
        linha = linha.strip()
        if not linha.startswith("{"):
            continue
        d = json.loads(linha)
        if "marcador" in d:
            atual = d["marcador"]
            grupos[atual] = []
            continue
        if atual is not None:
            grupos[atual].append(d)
    return grupos


async def main():
    cenarios = json.load(open(CENARIOS, encoding="utf-8"))
    develop = {r["nome"]: r for r in json.load(open(DEVELOP, encoding="utf-8"))}
    logs_dev = _logs_develop()
    app = criar_app(pre_aquecer=False)
    resultados, diferencas = [], []
    async with app.router.lifespan_context(app):
        for c in cenarios:
            antes = {}
            env = {"APP_ENV": c["env"].get("APP_ENV", "test"), **{k: v for k, v in c["env"].items() if k != "APP_ENV"}}
            for k, v in env.items():
                antes[k] = os.environ.get(k)
                os.environ[k] = v
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = await _asgi(app, c)
            for k, v in antes.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            resultados.append(r)
            d = develop[c["nome"]]
            difs = []
            for campo in ("status", "contentType", "location"):
                if r[campo] != d[campo]:
                    difs.append(f"{campo}: python={r[campo]!r} develop={d[campo]!r}")
            if d["status"] == 500 and r["status"] == 500 and d["corpo"] and r["corpo"]:
                rp, dp = json.loads(r["corpo"]), json.loads(d["corpo"])
                rp.pop("message", None), dp.pop("message", None)
                if list(rp.items()) != list(dp.items()):
                    difs.append(f"corpo: python={r['corpo']!r} develop={d['corpo']!r}")
            elif _norm_texto(r["corpo"]) != _norm_texto(d["corpo"]):
                difs.append(f"corpo:\n      python ={r['corpo'][:400]!r}\n      develop={d['corpo'][:400]!r}")
            s500 = d["status"] == 500
            meus = [_norm_log(json.loads(x), s500) for x in buf.getvalue().splitlines() if x.strip().startswith("{")]
            deles = [_norm_log(x, s500) for x in logs_dev.get(c["nome"], [])]
            if meus != deles:
                difs.append(
                    "log:\n      python ="
                    + json.dumps(meus, ensure_ascii=False)[:1500]
                    + "\n      develop="
                    + json.dumps(deles, ensure_ascii=False)[:1500]
                )
            if difs:
                diferencas.append((c["nome"], c["bloco"], difs))
    if SAIDA_PY:
        json.dump(resultados, open(SAIDA_PY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    blocos = {}
    for c in cenarios:
        blocos.setdefault(c["bloco"], [0, 0])[0] += 1
    for _, bloco, _ in diferencas:
        blocos[bloco][1] += 1
    print(f"{len(cenarios)} cenários, {len(cenarios) - len(diferencas)} idênticos (resposta e log), {len(diferencas)} com diferença")
    for b, (total, dif) in blocos.items():
        print(f"  {b}: {total} cenários, {dif} com diferença")
    for nome, bloco, difs in diferencas:
        print(f"\n[{bloco}] {nome}")
        for x in difs:
            print("   ", x)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
asyncio.run(main())
