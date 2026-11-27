"""Avisa por e-mail a renovação do token do Verde e a falha dela (issue #571).

Roda como último passo do `verificar-token-verde.yml`, só com a biblioteca padrão. Chama a função
`maria-email-nudecon` com o campo `aviso` (modelo neutro, sem a marca do NUDECON).

Entrada (variáveis de ambiente): `AMBIENTE`, `STATUS_DO_JOB` (`success` ou `failure`), `URL_DA_EXECUCAO`,
`EMAIL_AVISO_URL` e `EMAIL_AVISO_API_KEY`; `TESTE_AVISO=true` (com `ID_DA_EXECUCAO`) manda só um e-mail de teste,
sem renovar nada; e, no diretório atual, os arquivos que o passo de renovação deixa:
`etapa.txt` (etapa em andamento) e `renovado.json` (só existe se o token foi renovado e gravado).

Só avisa se o token foi renovado ou se o job falhou; token saudável não manda e-mail. Nunca imprime nem envia o token,
o client id ou a chave: o e-mail leva só ambiente, resultado, expiração nova, etapa e o link da execução.
Sai com código 1 se o envio falhar (o passo do workflow é `continue-on-error`, então o resultado do job não muda).
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

PRAZO_S = 20
NOMES_DO_AMBIENTE = {"prod": "Produção (SP)", "release": "Release (SP)"}


def montar_aviso(
    ambiente: str, status_do_job: str, etapa: str, renovado: dict[str, Any] | None, url_da_execucao: str, hoje: date
) -> dict[str, Any] | None:
    """O corpo da chamada à função de e-mail, ou `None` quando não há nada a avisar."""
    nome = NOMES_DO_AMBIENTE.get(ambiente, ambiente)
    dia = hoje.strftime("%Y%m%d")
    if status_do_job == "failure":
        dados = {"Ambiente": nome, "Resultado": "Falha na renovação", "Etapa": etapa or "leitura do segredo", "Execução": url_da_execucao}
        texto = "O workflow que renova o token do Verde terminou com erro."
        if renovado is not None:
            dados["Token renovado"] = "sim, mas o processo não terminou: confira o serviço"
            texto = "O token do Verde foi renovado, mas o processo não terminou."
        return {
            "protocolo": f"TOKEN-VERDE-{ambiente.upper()}-FALHA-{dia}",
            "dados": dados,
            "aviso": {
                "assunto": f"Falha na renovação do token do Verde ({nome})",
                "titulo": "Falha na renovação do token do Verde",
                "texto": texto,
            },
        }
    if renovado is not None:
        dados = {"Ambiente": nome, "Resultado": "Token renovado", "Nova expiração": renovado.get("expiraEm") or "não informada"}
        dados["Execução"] = url_da_execucao
        return {
            "protocolo": f"TOKEN-VERDE-{ambiente.upper()}-RENOVADO-{dia}",
            "dados": dados,
            "aviso": {
                "assunto": f"Token do Verde renovado ({nome})",
                "titulo": "Token do Verde renovado",
                "texto": "A renovação automática terminou e o serviço já está com o token novo.",
            },
        }
    return None


def montar_aviso_de_teste(ambiente: str, id_da_execucao: str, url_da_execucao: str, hoje: date) -> dict[str, Any]:
    """E-mail de teste do aviso (#571): confirma o caminho até a caixa sem renovar o token. O id da execução entra no
    `protocolo` para o teste poder ser repetido no mesmo dia (a função só envia uma vez por protocolo)."""
    nome = NOMES_DO_AMBIENTE.get(ambiente, ambiente)
    return {
        "protocolo": f"TOKEN-VERDE-{ambiente.upper()}-TESTE-{hoje.strftime('%Y%m%d')}-{id_da_execucao}"[:64],
        "dados": {"Ambiente": nome, "Resultado": "Teste do aviso (nada foi renovado)", "Execução": url_da_execucao},
        "aviso": {
            "assunto": f"Teste do aviso do token do Verde ({nome})",
            "titulo": "Teste do aviso do token do Verde",
            "texto": "Este é um e-mail de teste do aviso de renovação. Nenhum token foi consultado nem renovado.",
        },
    }


def _ler_texto(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8").strip() if caminho.exists() else ""


def _ler_renovado(caminho: Path) -> dict[str, Any] | None:
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def enviar(url: str, chave: str, corpo: dict[str, Any], prazo: float = PRAZO_S) -> int:
    """`POST` na função de e-mail; devolve o status HTTP. Nada do pedido nem da chave vai para a saída."""
    pedido = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(corpo).encode("utf-8"),
        headers={"authorization": f"Bearer {chave}", "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=prazo) as resposta:
            return int(resposta.status)
    except urllib.error.HTTPError as erro:
        return int(erro.code)


def main(env: dict[str, str] | None = None, pasta: Path | None = None) -> int:
    env = dict(os.environ) if env is None else env
    pasta = pasta or Path(".")
    ambiente = env.get("AMBIENTE", "")
    teste = env.get("TESTE_AVISO", "").lower() == "true"
    corpo = (
        montar_aviso_de_teste(ambiente, env.get("ID_DA_EXECUCAO", "0"), env.get("URL_DA_EXECUCAO", ""), date.today())
        if teste
        else montar_aviso(
            ambiente,
            env.get("STATUS_DO_JOB", ""),
            _ler_texto(pasta / "etapa.txt"),
            _ler_renovado(pasta / "renovado.json"),
            env.get("URL_DA_EXECUCAO", ""),
            date.today(),
        )
    )
    if corpo is None:
        print(f"[{ambiente}] token sem renovação e sem falha: nenhum aviso")
        return 0
    url, chave = env.get("EMAIL_AVISO_URL", ""), env.get("EMAIL_AVISO_API_KEY", "")
    if not url or not chave:
        print(f"::warning::[{ambiente}] secrets EMAIL_AVISO_URL/EMAIL_AVISO_API_KEY ausentes: aviso não enviado")
        return 1
    try:
        status = enviar(url, chave, corpo)
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        print(f"::warning::[{ambiente}] aviso não enviado ({type(erro).__name__})")
        return 1
    if status != 200:
        print(f"::warning::[{ambiente}] aviso não enviado (HTTP {status})")
        return 1
    print(f"[{ambiente}] aviso enviado ({corpo['protocolo']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
