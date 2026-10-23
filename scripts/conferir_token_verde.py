"""Confere se o Verde aceita o token do segredo de um ambiente (issue #298).

Só leitura: chama `GET /autenticacao/token/status` e nunca o `refresh`. A renovação
invalida o token antigo na hora, e por isso tem um dono só, o workflow agendado
`verificar-token-verde.yml` (que usa as funções deste arquivo para a consulta).

Roda no runner do GitHub, só com a biblioteca padrão, sem `uv sync`:

    python3 scripts/conferir_token_verde.py --ambiente release --segredo segredo.json

`segredo.json` é o `SecretString` do `maria-langgraph-pp-<ambiente>/app` (campos
`VERDE_API_URL`, `VERDE_JWT_TOKEN` e `VERDE_CLIENT_ID`). Sai com código 1 quando o Verde
não aceita o token. O token nunca vai para a saída: na falha, só o status HTTP, o `codigo`
do Verde e os campos `expirado`, `revogado` e `expiraEm`.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PRAZO_S = 20
CAMPOS_DO_STATUS = {"valido", "expirado", "revogado"}
TAMANHO_MAXIMO_DO_CODIGO = 60


class ErroDeStatus(Exception):
    """O Verde não respondeu o que a conferência precisa; a mensagem é segura para o log."""


def consultar_status(api_url: str, token: str, client_id: str, prazo: float = PRAZO_S) -> tuple[int, Any]:
    """`GET /autenticacao/token/status`. Devolve (status HTTP, corpo em JSON ou None)."""
    pedido = urllib.request.Request(
        f"{api_url.rstrip('/')}/autenticacao/token/status",
        method="GET",
        headers={"accept": "application/json", "authorization": f"Bearer {token}", "x-client-id": client_id},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=prazo) as resposta:
            return resposta.status, _como_json(resposta.read())
    except urllib.error.HTTPError as erro:
        return erro.code, _como_json(erro.read())
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        # Só o tipo do erro: a mensagem de um URLError pode trazer o endereço.
        raise ErroDeStatus(f"GET token/status sem resposta do Verde ({type(erro).__name__})") from erro


def _como_json(corpo: bytes) -> Any:
    try:
        return json.loads(corpo)
    except ValueError:
        return None


def _codigo_do_verde(corpo: Any) -> str | None:
    """O `codigo` do erro do Verde (ex.: NAO_AUTORIZADO), na raiz ou em `dados`."""
    if not isinstance(corpo, dict):
        return None
    for nivel in (corpo, corpo.get("dados")):
        codigo = nivel.get("codigo") if isinstance(nivel, dict) else None
        if isinstance(codigo, str):
            return codigo[:TAMANHO_MAXIMO_DO_CODIGO]
    return None


def ler_status(codigo_http: int, corpo: Any) -> dict[str, Any]:
    """Valida a resposta de `token/status` e devolve o objeto com `valido`/`expirado`/`revogado`.

    A resposta vem envelopada em `dados` (achado ao vivo, #194), mas o exemplo do Swagger é
    plano; aceita os dois. Um formato inesperado nunca vira "token saudável".
    """
    if codigo_http != 200:
        codigo = _codigo_do_verde(corpo)
        detalhe = f", codigo {codigo}" if codigo else ""
        raise ErroDeStatus(f"GET token/status falhou (HTTP {codigo_http}{detalhe})")
    status = corpo.get("dados", corpo) if isinstance(corpo, dict) else None
    if not isinstance(status, dict) or not (CAMPOS_DO_STATUS & status.keys()):
        raise ErroDeStatus(
            "GET token/status devolveu 200 mas sem nenhum campo esperado (valido, expirado ou revogado): o contrato do Verde mudou?"
        )
    return status


def problema_do_token(status: dict[str, Any]) -> str | None:
    """Por que o Verde não aceita o token, ou None se aceita."""
    if status.get("revogado"):
        return "o token foi revogado no Verde: precisa de um token novo, emitido por eles"
    if status.get("expirado"):
        return "o token expirou"
    if status.get("valido") is False:
        return "o Verde diz que o token não é válido"
    return None


def _resumo(status: dict[str, Any]) -> str:
    return f"expirado={status.get('expirado', False)} revogado={status.get('revogado', False)} expiraEm={status.get('expiraEm')}"


def conferir(segredo: dict[str, Any], ambiente: str) -> int:
    codigo_http, corpo = consultar_status(str(segredo["VERDE_API_URL"]), str(segredo["VERDE_JWT_TOKEN"]), str(segredo["VERDE_CLIENT_ID"]))
    status = ler_status(codigo_http, corpo)
    problema = problema_do_token(status)
    if problema:
        print(f"::error::[{ambiente}] o Verde não aceita o token do segredo: {problema} ({_resumo(status)})")
        return 1
    print(f"[{ambiente}] o Verde aceita o token do segredo ({_resumo(status)})")
    return 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="Confere se o Verde aceita o token do segredo de um ambiente (só leitura).")
    analisador.add_argument("--ambiente", required=True, help="nome do ambiente, só para o log (prod ou release)")
    analisador.add_argument("--segredo", required=True, type=Path, help="arquivo JSON com o SecretString do ambiente")
    argumentos = analisador.parse_args(argv)
    try:
        segredo = json.loads(argumentos.segredo.read_text(encoding="utf-8"))
        return conferir(segredo, argumentos.ambiente)
    except ErroDeStatus as erro:
        print(f"::error::[{argumentos.ambiente}] {erro}")
        return 1
    except (OSError, ValueError, KeyError, TypeError) as erro:
        # Sem o texto do erro: um KeyError ou ValueError não deve arrastar o conteúdo do segredo para o log.
        print(
            f"::error::[{argumentos.ambiente}] segredo ilegível ou sem VERDE_API_URL, VERDE_JWT_TOKEN ou VERDE_CLIENT_ID "
            f"({type(erro).__name__})"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
