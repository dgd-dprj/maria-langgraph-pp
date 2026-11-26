"""QA da staging (#502, parte C): roda contra o release de São Paulo depois de cada publicação da `staging`.

No Actions, o `.github/workflows/qa-staging.yml` chama este roteiro quando o "Deploy — release (homolog)" da
`staging` termina com sucesso, e comenta o resumo no último PR que entrou na `staging`. Na máquina:

    uv run python -X utf8 scripts/qa/qa_staging.py [--saida resumo.md]

O que confere:
1. A publicação: o último "Deploy — release (homolog)" da `staging` é do commit atual da `staging` e terminou bem.
2. O release no ar: `/health` e o contrato do `/docs`.
3. Os fluxos que não dependem de RG nem CPF do Verde: o orquestrador com vários assuntos, a ordem, a pergunta
   "Qual você quer resolver primeiro?" numerada, a pergunta curta do irmão, os assuntos em aberto (lista numerada,
   encerrar, abrir pelo flowId e pelo tipoCaso) e o encerrar pelo número.
3b. #497: o CPF fictício no lugar do RG e o CPF com a conta errada são recusados antes do Verde.
4. O log do release durante o teste: nenhum erro de nível 50.

O que NÃO confere (fica para o teste da equipe): os fluxos que consultam pessoa no Verde e o fim da conversa depois
deles. O Verde de homologação tem cópia de dados reais: o QA nunca procura RG nem CPF lá.

Cuidados:
- a chave da API do release vem do segredo `RELEASE_API_KEY` (Actions) ou do Secrets Manager (máquina), e nunca é
  impressa;
- relatos inventados; `idUsuario` `qa-staging-<hora>` (os assuntos guardados vencem em 30 dias);
- teto de IA de US$ 0,10 por rodada (decisão da Nicole, 2026-11-16), pelos `tokensGastos` e o preço do Haiku `us.`
  como teto seguro (é mais caro que o Qwen do release). Medido em 13/11: cerca de US$ 0,006 por rodada. Se passar, o
  roteiro para antes da chamada seguinte, e o resumo menciona a Nicole e o Ícaro.

Código de saída: 0 tudo certo, 1 alguma conferência falhou, 2 parou no teto de IA.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3  # type: ignore[import-untyped]  # sem stubs no projeto

REPO = "dgd-dprj/maria-langgraph-pp"
# #463 (16/11): o release roda só em São Paulo.
BASE = "https://d29e2r1w5lfmic.cloudfront.net"
REGIAO = "sa-east-1"
GRUPO_LOG = "/ecs/maria-langgraph-pp-release-sp/api"
SEGREDO = "maria-langgraph-pp-release/app"
ID_PP = "3df874f2-675a-4c43-9ec7-480f7c702f50"
ID_VD = "cabb2495-4e12-4f4a-9956-3d20649059bc"
TETO_USD = 0.10
# Preço do Haiku `us.` por milhão de tokens (entrada, saída): o teto seguro.
PRECO_ENTRADA, PRECO_SAIDA = 1.10, 5.50
AVISAR = "@pivetadev @icaroeduardo-lab"


class PassouDoTeto(Exception):
    """O gasto de IA da rodada passou de TETO_USD: o roteiro para antes da chamada seguinte."""


class QA:
    def __init__(self, chave: str) -> None:
        self.chave = chave
        self.gasto = 0.0
        self.resultados: list[tuple[str, bool, str]] = []
        self.sufixo = time.strftime("%Y%m%d-%H%M%S")

    def conferir(self, nome: str, ok: bool, detalhe: str = "") -> bool:
        self.resultados.append((nome, ok, detalhe))
        print(f"[{'OK' if ok else 'FALHOU'}] {nome}" + (f": {detalhe}" if detalhe and not ok else ""))
        return ok

    def chamar(self, metodo: str, rota: str, corpo: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        if self.gasto > TETO_USD:
            raise PassouDoTeto(f"custo de IA US$ {self.gasto:.4f} passou do teto de US$ {TETO_USD}")
        pedido = urllib.request.Request(
            BASE + rota,
            data=json.dumps(corpo).encode() if corpo is not None else None,
            method=metodo,
            headers={"Authorization": f"Bearer {self.chave}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(pedido, timeout=40) as r:
                status, texto = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, texto = e.code, e.read()
        try:
            dados = json.loads(texto or b"{}")
        except ValueError:
            dados = {"_texto": texto.decode(errors="replace")[:200]}
        if not isinstance(dados, dict):
            dados = {"_corpo": dados}
        tokens = dados.get("tokensGastos") or {}
        self.gasto += (tokens.get("input", 0) * PRECO_ENTRADA + tokens.get("output", 0) * PRECO_SAIDA) / 1e6
        return status, dados

    def responder(self, chat: str, resposta: str) -> dict[str, Any]:
        return self.chamar("POST", "/atendimentos/respostas", {"chatId": chat, "resposta": resposta})[1]


def comando(*args: str) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, encoding="utf-8").stdout.strip()


def chave_do_release() -> str:
    """O segredo do Actions, se houver; senão, o Secrets Manager (a credencial da máquina)."""
    if os.environ.get("RELEASE_API_KEY"):
        return os.environ["RELEASE_API_KEY"]
    cliente = boto3.client("secretsmanager", region_name=REGIAO)
    return str(json.loads(cliente.get_secret_value(SecretId=SEGREDO)["SecretString"])["API_KEY"])


def publicacao(qa: QA) -> str:
    sha = comando("git", "ls-remote", f"https://github.com/{REPO}.git", "refs/heads/staging").split("\t")[0]
    ultimo = json.loads(
        comando(
            "gh",
            "run",
            "list",
            "-R",
            REPO,
            "--workflow",
            "Deploy — release (homolog)",
            "--branch",
            "staging",
            "--limit",
            "1",
            "--json",
            "headSha,status,conclusion",
        )
        or "[{}]"
    )[0]
    qa.conferir(
        "publicação do release é do commit atual da staging",
        ultimo.get("headSha") == sha,
        f"staging {sha[:7]}, publicação {str(ultimo.get('headSha'))[:7]}",
    )
    qa.conferir(
        "publicação terminou com sucesso",
        ultimo.get("status") == "completed" and ultimo.get("conclusion") == "success",
        f"{ultimo.get('status')}/{ultimo.get('conclusion')}",
    )
    return sha


def release_no_ar(qa: QA) -> None:
    with urllib.request.urlopen(BASE + "/health", timeout=20) as r:
        qa.conferir("/health responde 200", r.status == 200)
    with urllib.request.urlopen(BASE + "/docs/json", timeout=20) as r:
        docs = r.read().decode()
    qa.conferir("/docs: assuntosEmAberto sem chatIdAssunto", "chatIdAssunto" not in docs)
    qa.conferir("/docs: próximo assunto com flowId e tipoCaso no corpo e exemplo de verdade", '"tipoCaso"' in docs and ID_PP in docs)


def fluxos_sem_verde(qa: QA) -> None:
    chat, usuario = f"qa-staging-a-{qa.sufixo}", f"qa-staging-{qa.sufixo}"
    _, d = qa.chamar(
        "POST",
        "/atendimentos/orquestrador",
        {
            "chatId": chat,
            "idUsuario": usuario,
            "mensagem": "meu irmão foi preso, quero remarcar meu horário e saber do meu processo de pensão",
        },
    )
    texto = d.get("resposta", "")
    qa.conferir(
        "orquestrador: pergunta da ordem com Sim/Não", d.get("tipoResposta") == "sim_nao" and "Pode ser assim?" in texto, texto[:120]
    )
    qa.conferir("orquestrador: ordem nova (pessoa presa primeiro)", "começar pela pessoa presa" in texto, texto[:120])
    _, d = qa.chamar("POST", "/atendimentos/orquestrador", {"chatId": chat, "resposta": "false"})
    opcoes = d.get("opcoes") or []
    qa.conferir(
        '"Qual você quer resolver primeiro?" com botões numerados',
        d.get("tipoResposta") == "opcoes" and bool(opcoes) and opcoes[0].startswith("1. "),
    )
    qa.conferir('legenda "Responda com o número da opção."', "Responda com o número da opção." in d.get("resposta", ""))
    escolha = next((o for o in opcoes if "horário" in o), "2")
    _, d = qa.chamar("POST", "/atendimentos/orquestrador", {"chatId": chat, "resposta": escolha})
    qa.conferir(
        "escolha pelo texto do botão abre o assunto (Tykhe)", d.get("status") == "redirecionado" and d.get("tipoCaso") == "agendamentos"
    )
    pp: dict[str, Any] = next((p for p in d.get("assuntosPendentes") or [] if p.get("flowId") == ID_PP), {})
    qa.conferir(
        "pessoa presa pendente com a pergunta curta do irmão",
        (pp.get("dadosConhecidos") or {}).get("perguntaParentesco") == "Você é irmão ou irmã dele?",
    )
    _, d = qa.chamar("POST", "/atendimentos/assuntos-em-aberto", {"chatId": chat})
    abertos = d.get("assuntosEmAberto") or []
    qa.conferir("assuntos em aberto sem chatIdAssunto", bool(abertos) and all("chatIdAssunto" not in a for a in abertos))
    qa.conferir(
        "lista com Urgente:, Outras opções: e Encerrar a conversa",
        "Urgente:" in d.get("resposta", "")
        and "Outras opções:" in d.get("resposta", "")
        and any("Encerrar a conversa" in o for o in d.get("opcoes") or []),
    )
    # O encerrar vem antes de abrir os assuntos: com tudo aberto, a lista não tem a opção.
    numero = next((o.split(".")[0] for o in d.get("opcoes") or [] if "Encerrar a conversa" in o), None)
    if numero:
        _, fim = qa.chamar("POST", "/atendimentos/proximo-assunto", {"chatId": chat, "resposta": numero})
        qa.conferir("encerrar pelo número", fim.get("status") == "concluido" and fim.get("resposta", "").startswith("Combinado."))
    else:
        qa.conferir("encerrar pelo número", False, "sem a opção de encerrar na lista")
    tipo = next((a["tipoCaso"] for a in abertos if a.get("tipoCaso")), None)
    if tipo:
        _, d = qa.chamar("POST", "/atendimentos/proximo-assunto", {"chatId": chat, "tipoCaso": tipo})
        qa.conferir("abre pelo tipoCaso", d.get("status") == "redirecionado" and d.get("tipoCaso") == tipo)
    _, d = qa.chamar("POST", "/atendimentos/proximo-assunto", {"chatId": chat, "flowId": ID_PP})
    qa.conferir(
        "abre a pessoa presa pelo flowId",
        d.get("flowId") == ID_PP and d.get("resposta", "").startswith("Agora vamos falar da pessoa presa."),
    )
    # #493: os assuntos da Tykhe já abertos antes (o horário pela escolha e o outro pelo tipoCaso) não voltam como pendentes.
    ja_abertos = {"agendamentos"} | ({tipo} if tipo else set())
    restantes = [p.get("tipoCaso") or p.get("flowId") for p in d.get("assuntosPendentes") or []]
    qa.conferir(
        "#493: a pessoa presa aberta fora da ordem não traz de volta assunto já aberto",
        not ja_abertos.intersection(restantes),
        f"pendentes: {restantes}",
    )
    _, d = qa.chamar("POST", "/atendimentos/assuntos-em-aberto", {"chatId": chat})
    qa.conferir("com tudo aberto, a lista diz que não há assuntos em aberto", "Você não tem assuntos em aberto" in d.get("resposta", ""))


def cpf_antes_do_verde(qa: QA) -> None:
    """#497: o CPF conferido pelos dígitos verificadores, antes do Verde. O CPF é o fictício de teste
    (123.456.789-09 fecha a conta; 123.456.789-00 não fecha). Nenhuma das duas chamadas consulta o Verde."""
    chat_pp = f"qa-staging-cpf-pp-{qa.sufixo}"
    _, d = qa.chamar("POST", "/atendimentos", {"chatId": chat_pp, "flowId": ID_PP})
    for _ in range(3):  # até a pergunta do RG: "tem o número do processo?" → não
        if "RG da pessoa presa" in d.get("resposta", ""):
            break
        d = qa.responder(chat_pp, "false")
    d = qa.responder(chat_pp, "123.456.789-09")
    qa.conferir(
        "#497: CPF no lugar do RG pede o RG, sem consultar o Verde",
        d.get("resposta", "").startswith("Esse número parece um CPF.")
        and "(tentativa 1 de 3)" in d.get("resposta", "")
        and d.get("status") == "em_andamento"
        and "dadosApenado" not in (d.get("metadados") or {}),
        d.get("resposta", "")[:120],
    )
    chat_vd = f"qa-staging-cpf-vd-{qa.sufixo}"
    _, d = qa.chamar("POST", "/atendimentos", {"chatId": chat_vd, "flowId": ID_VD})
    for _ in range(4):  # vítima → sim; processo → não; boletim → não; até a pergunta do CPF
        if "Qual o seu CPF" in d.get("resposta", ""):
            break
        d = qa.responder(chat_vd, "true" if "vítima" in d.get("resposta", "") else "false")
    d = qa.responder(chat_vd, "123.456.789-00")
    qa.conferir(
        "#497: CPF com a conta errada não consulta o Verde e pede de novo",
        d.get("resposta", "") == "Esse CPF não está certo. Confira os 11 números e escreva de novo."
        and d.get("status") == "em_andamento"
        and "dadosPessoa" not in (d.get("metadados") or {}),
        d.get("resposta", "")[:120],
    )


def log_sem_erro(qa: QA, inicio: datetime) -> None:
    time.sleep(20)  # o log chega ao CloudWatch com alguns segundos de atraso
    logs = boto3.client("logs", region_name=REGIAO)
    consulta = logs.start_query(
        logGroupName=GRUPO_LOG,
        startTime=int(inicio.timestamp()) - 5,
        endTime=int(time.time()),
        queryString="filter level >= 50 | stats count() as erros",
    )
    resultado: dict[str, Any] = {}
    for _ in range(30):
        time.sleep(2)
        resultado = logs.get_query_results(queryId=consulta["queryId"])
        if resultado["status"] == "Complete":
            break
    erros = int(resultado["results"][0][0]["value"]) if resultado.get("results") else 0
    qa.conferir("nenhum erro no log do release durante o QA", erros == 0, f"{erros} erro(s)")


def resumo(qa: QA, sha: str, parado: str | None) -> str:
    ok = sum(1 for _, v, _ in qa.resultados if v)
    linhas = [f"## QA da staging ({datetime.now(UTC):%d/%m/%Y %H:%M} UTC, commit {sha[:7]})", ""]
    if parado:
        linhas += [f"**PARADO no teto de IA:** {parado}. {AVISAR}, decidam se vale passar o valor nesta verificação.", ""]
    linhas += [
        f"**{ok} de {len(qa.resultados)} OK.** Custo de IA: US$ {qa.gasto:.4f} (teto de US$ {TETO_USD}). "
        f"Conversas `qa-staging-*-{qa.sufixo}`.",
        "",
    ]
    linhas += [f"- {'✅' if v else '❌'} {nome}" + (f" ({detalhe})" if detalhe and not v else "") for nome, v, detalhe in qa.resultados]
    linhas += ["", "Fica para o teste da equipe: os fluxos que consultam pessoa no Verde e o fim da conversa depois deles."]
    return "\n".join(linhas) + "\n"


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--saida", type=Path, help="arquivo para o resumo em Markdown")
    args = argumentos.parse_args()
    qa = QA(chave_do_release())
    inicio = datetime.now(UTC)
    sha = publicacao(qa)
    parado = None
    try:
        release_no_ar(qa)
        fluxos_sem_verde(qa)
        cpf_antes_do_verde(qa)
    except PassouDoTeto as erro:
        parado = str(erro)
    log_sem_erro(qa, inicio)
    texto = resumo(qa, sha, parado)
    print("\n" + texto)
    if args.saida:
        args.saida.write_text(texto, encoding="utf-8")
    if parado:
        return 2
    return 0 if all(v for _, v, _ in qa.resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
