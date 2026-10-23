"""Conferência do crawler: develop @ 1157a6d contra o Python, por HTTP real (spec 08, seção 7).

Sobe um Verde falso local, roda cada cenário de `cenarios.json` nos dois lados como processo
separado (develop pela cópia sonda, Python pelo `executor_python.py`) e compara:
- stdout, linha a linha (as linhas de log pino sem time, pid e hostname);
- stderr, linha a linha (num erro fatal, só a primeira linha: a pilha é da linguagem);
- o código de saída;
- as chamadas feitas ao Verde, na ordem;
- o que ficou gravado em cada flow, sem os UUIDs. Chave ausente e null contam igual, porque a
  store do Postgres grava os dois como NULL; a store em memória de develop guarda undefined.

Grava `develop.json` e `python.json` ao lado.

Uso: python conferir_coleta.py <worktree de develop> [índices de cenário...]
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
RAIZ_PYTHON = AQUI.parents[3]
DEVELOP = Path(sys.argv[1])
CENARIOS: list[dict[str, Any]] = json.loads((AQUI / "cenarios.json").read_text(encoding="utf-8"))
SO = [int(i) for i in sys.argv[2:]]

chamadas: dict[tuple[str, int], list[str]] = {}


class VerdeFalso(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        _, lado, indice, resto = self.path.split("/", 3)
        rota = "/" + resto.removeprefix("api/integra/")
        chamadas.setdefault((lado, int(indice)), []).append(rota)
        resposta = CENARIOS[int(indice)]["rotas"].get(rota)
        if resposta is None:
            resposta = {"status": 404, "corpo": {"erro": "rota não existe no Verde falso"}}
        time.sleep(resposta.get("atraso", 0))
        if "bruto" in resposta:
            corpo, tipo = resposta["bruto"].encode(), "text/plain"
        else:
            corpo, tipo = json.dumps(resposta["corpo"]).encode(), "application/json"
        try:
            self.send_response(resposta["status"])
            self.send_header("content-type", tipo)
            self.send_header("content-length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
        except OSError:
            pass  # o cliente desistiu (timeout)


servidor = ThreadingHTTPServer(("127.0.0.1", 0), VerdeFalso)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
PORTA = servidor.server_address[1]

COMANDOS = {
    "develop": (["node", str(DEVELOP / "node_modules/tsx/dist/cli.mjs"), ".sonda/coletar-sonda.ts"], DEVELOP),
    "python": ([str(RAIZ_PYTHON / ".venv/Scripts/python.exe"), str(AQUI / "executor_python.py")], Path(tempfile.mkdtemp())),
}


def log_normalizado(linha: str) -> str:
    """Linha de log pino: sem time, pid e hostname, que mudam a cada execução."""
    if not linha.startswith("{"):
        return linha
    try:
        registro = json.loads(linha)
    except ValueError:
        return linha
    if not isinstance(registro, dict) or "level" not in registro:
        return linha
    return json.dumps({k: v for k, v in registro.items() if k not in ("time", "pid", "hostname")}, ensure_ascii=False)


def rodar(lado: str, indice: int, cenario: dict[str, Any]) -> dict[str, Any]:
    api = {"vazia": "", "porta_fechada": "http://127.0.0.1:1/api/integra"}.get(
        cenario.get("api_url", ""), f"http://127.0.0.1:{PORTA}/{lado}/{indice}/api/integra"
    )
    dump = Path(tempfile.mkdtemp()) / "dump.json"
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "VERDE_API_URL", "VERDE_JWT_TOKEN", "VERDE_CLIENT_ID")}
    env.update(
        VERDE_API_URL=api,
        VERDE_JWT_TOKEN="token-falso",
        VERDE_CLIENT_ID="cliente-falso",
        CENARIO_PLANEJADOS=json.dumps(cenario["planejados"]),
        DUMP_ARQUIVO=str(dump),
        PYTHONIOENCODING="utf-8",
    )
    comando, cwd = COMANDOS[lado]
    r = subprocess.run(comando, cwd=cwd, env=env, capture_output=True, timeout=600)
    return {
        "nome": cenario["nome"],
        "codigo": r.returncode,
        "stdout": [log_normalizado(linha) for linha in r.stdout.decode("utf-8").replace("\r\n", "\n").splitlines()],
        "stderr": r.stderr.decode("utf-8").replace("\r\n", "\n").splitlines(),
        "chamadas": chamadas.get((lado, indice), []),
        "dump": json.loads(dump.read_text(encoding="utf-8")) if dump.exists() else None,
    }


def sem_null(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {k: sem_null(v) for k, v in valor.items() if v is not None}
    if isinstance(valor, list):
        return [sem_null(v) for v in valor]
    return valor


def stderr_comparavel(linhas: list[str]) -> list[str]:
    for i, linha in enumerate(linhas):
        if linha.startswith("crawl falhou:"):
            return linhas[: i + 1]
    return linhas


def diferencas(d: dict[str, Any], p: dict[str, Any]) -> list[str]:
    saida = []
    for campo in ("codigo", "stdout", "chamadas"):
        if d[campo] != p[campo]:
            saida.append(f"{campo}: develop={d[campo]!r} python={p[campo]!r}")
    if stderr_comparavel(d["stderr"]) != stderr_comparavel(p["stderr"]):
        saida.append(f"stderr: develop={stderr_comparavel(d['stderr'])!r} python={stderr_comparavel(p['stderr'])!r}")
    if sem_null(d["dump"]) != sem_null(p["dump"]):
        saida.append(
            f"dump: develop={json.dumps(d['dump'], ensure_ascii=False)[:600]} python={json.dumps(p['dump'], ensure_ascii=False)[:600]}"
        )
    return saida


resultados: dict[str, list[dict[str, Any]]] = {"develop": [], "python": []}
iguais = 0
indices = SO or list(range(len(CENARIOS)))
# Cada cenário é gravado assim que termina: numa rodada interrompida, o que já rodou fica.
parcial = AQUI / "resultados-parciais.jsonl"
for indice in indices:
    cenario = CENARIOS[indice]
    d = rodar("develop", indice, cenario)
    p = rodar("python", indice, cenario)
    resultados["develop"].append(d)
    resultados["python"].append(p)
    with parcial.open("a", encoding="utf-8", newline="\n") as arquivo:
        arquivo.write(json.dumps({"indice": indice, "develop": d, "python": p}, ensure_ascii=False) + "\n")
    time.sleep(1)  # sem rajada de processos (a rodada de 2026-10-20 foi bloqueada pelo sistema)
    difs = diferencas(d, p)
    if difs:
        print(f"DIFERENTE [{indice}] {cenario['nome']}")
        for dif in difs:
            print("   ", dif)
    else:
        iguais += 1
        print(f"igual     [{indice}] {cenario['nome']}")
    sys.stdout.flush()

if not SO:
    for lado, lista in resultados.items():
        (AQUI / f"{lado}.json").write_text(json.dumps(lista, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
print(f"\n{iguais} de {len(indices)} cenários iguais")
