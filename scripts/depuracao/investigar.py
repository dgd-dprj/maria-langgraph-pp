"""Depuração com IA (#503): uma falha do CI percorre as 6 fases e vira uma issue `[BUG]`, sem PR automático.

Decisões da Nicole (2026-11-16 e 17): o método de 6 fases; teto de US$ 0,10 por investigação, que para e avisa a
Nicole e o Ícaro se for passar; a IA é o Qwen de São Paulo (o Qwen3 Coder, que achou a causa e o patch na medição de
17/11 em cerca de 1 s por fase); na hipótese vai só o trecho alterado; o patch fica como artefato; a issue pública
nunca leva conteúdo de log da produção. Custo medido em 17/11: US$ 0,011 a 0,015 por investigação, no preço do Haiku.

| Fase | O que faz | IA |
|---|---|---|
| 1. coleta | os testes e os cenários que falharam e a classificação do defeito | 1 chamada |
| 2. reprodução | roda os testes que falharam 3 vezes: consistente ou intermitente | não |
| 3. isolamento | `git bisect` entre a base e o commit que falhou | não |
| 4. causa | até 3 hipóteses, cada uma com um patch aplicado e conferido pelos próprios testes | até 3 |
| 5. correção | o patch que passou, contra a suíte rápida inteira | não |
| 6. registro | a issue `[BUG]` com a etiqueta `depuracao-ia` e o bloco de dados do Visor | não |

Uso no Actions (`.github/workflows/depuracao.yml`): `--execucao <id da execução do CI que falhou>`.
Uso na máquina (validação): `--log <arquivo com a saída do pytest> --base <commit bom> --head <commit que falha> --sem-issue`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MODELO = "qwen.qwen3-coder-30b-a3b-v1:0"
REGIAO = "sa-east-1"
PRECO_ENTRADA, PRECO_SAIDA = 1.10, 5.50  # US$ por milhão de tokens, Haiku us.: o teto seguro (o Qwen custa menos)
TETO_USD = 0.10
HIPOTESES = 3
REPETICOES = 3
ETIQUETA = "depuracao-ia"
MARCA_DO_VISOR = "<!-- visor:depuracao -->"
# Quem a rotina avisa quando o teto for passar (decisão da Nicole, 16/11).
AVISAR = "@pivetadev @icaroeduardo-lab"
SISTEMA = (
    "Você é a rotina de depuração da Maria, a assistente em Python da Defensoria Pública do RJ. Responda em português do "
    "Brasil, curto e objetivo. Os dados dos testes são inventados; nunca escreva dado pessoal."
)

HORA_DA_LINHA = re.compile(r"^\S+Z ")
# O id do pytest pode ter espaço e travessão no parâmetro ("test_x[123 456]"): vai até o " - " da mensagem.
TESTE_QUE_FALHOU = re.compile(r"^FAILED (\S+?::.+?)(?: - .*)?$")
CENARIO_QUE_FALHOU = re.compile(r"^\| (.+?) \| \*\*FALHOU\*\* \| (.*?) \|\s*$")
TAMANHO_DO_TRECHO = 4000
TAMANHO_DO_DIFF = 12000


class EstourouTeto(Exception):
    """A próxima chamada passaria do teto: a investigação para antes de chamar."""


@dataclass
class Falha:
    testes: list[str] = field(default_factory=list)
    cenarios: list[str] = field(default_factory=list)
    trecho: str = ""


def ler_falhas(log: str) -> Falha:
    """Os testes (pytest) e os cenários (ponta a ponta) que falharam, e o fim da saída, sem a hora das linhas."""
    falha = Falha()
    limpas = [HORA_DA_LINHA.sub("", linha, count=1).rstrip() for linha in log.splitlines()]
    for linha in limpas:
        if (achou := TESTE_QUE_FALHOU.match(linha.strip())) and achou.group(1) not in falha.testes:
            falha.testes.append(achou.group(1))
        elif (achou := CENARIO_QUE_FALHOU.match(linha.strip())) and achou.group(1) not in falha.cenarios:
            falha.cenarios.append(achou.group(1).strip())
    falha.trecho = "\n".join(limpas)[-TAMANHO_DO_TRECHO:]
    return falha


@dataclass
class Orcamento:
    teto: float = TETO_USD
    gasto: float = 0.0
    chamadas: list[dict[str, Any]] = field(default_factory=list)

    def cabe(self, entrada_estimada: int, saida_maxima: int) -> bool:
        return self.gasto + (entrada_estimada * PRECO_ENTRADA + saida_maxima * PRECO_SAIDA) / 1e6 <= self.teto

    def registrar(self, fase: str, entrada: int, saida: int) -> None:
        custo = (entrada * PRECO_ENTRADA + saida * PRECO_SAIDA) / 1e6
        self.gasto += custo
        self.chamadas.append({"fase": fase, "entrada": entrada, "saida": saida, "custo": round(custo, 6)})


# A chamada ao modelo: (sistema, pedido, máximo de tokens) -> (texto, tokens de entrada, tokens de saída).
Modelo = Callable[[str, str, int], tuple[str, int, int]]


def modelo_do_bedrock() -> Modelo:
    import boto3  # type: ignore[import-untyped]  # sem stubs no projeto

    cliente = boto3.Session().client("bedrock-runtime", region_name=REGIAO)

    def chamar(sistema: str, pedido: str, maximo: int) -> tuple[str, int, int]:
        r = cliente.converse(
            modelId=MODELO,
            system=[{"text": sistema}],
            messages=[{"role": "user", "content": [{"text": pedido}]}],
            inferenceConfig={"maxTokens": maximo},
        )
        texto = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
        return texto, int(r["usage"]["inputTokens"]), int(r["usage"]["outputTokens"])

    return chamar


class IA:
    def __init__(self, modelo: Modelo, orcamento: Orcamento) -> None:
        self._modelo = modelo
        self.orcamento = orcamento

    def perguntar(self, fase: str, pedido: str, maximo: int) -> str:
        # Estimativa conservadora da entrada (cerca de 3 caracteres por token) para não passar do teto.
        if not self.orcamento.cabe(len(SISTEMA + pedido) // 3, maximo):
            raise EstourouTeto(
                f"a fase {fase} passaria do teto de US$ {self.orcamento.teto:.2f} (gasto até aqui: US$ {self.orcamento.gasto:.4f})"
            )
        texto, entrada, saida = self._modelo(SISTEMA, pedido, maximo)
        self.orcamento.registrar(fase, entrada, saida)
        return texto


# ── Git e pytest ──────────────────────────────────────────────────────────


def rodar(comando: list[str], pasta: Path, tempo: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(comando, cwd=pasta, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=tempo)


def arquivos_dos_testes(testes: list[str]) -> list[str]:
    """Os arquivos dos testes que falharam. A rotina roda o arquivo inteiro, e não o id: o id com parâmetro
    ("test_x[123.456.789-09]") se quebra no shell e no log, e o pytest acusa "não encontrado" (validação de 17/11)."""
    return sorted({t.split("::", 1)[0] for t in testes if "::" in t})


def comando_dos_testes(testes: list[str]) -> list[str]:
    return ["uv", "run", "--frozen", "pytest", "-q", "-p", "no:cacheprovider", *arquivos_dos_testes(testes)]


def reproduzir(pasta: Path, testes: list[str], vezes: int = REPETICOES) -> bool | None:
    """True se os testes falham todas as vezes; False se falham só às vezes (intermitente); None sem teste para rodar."""
    if not testes:
        return None
    falhas = sum(rodar(comando_dos_testes(testes), pasta).returncode != 0 for _ in range(vezes))
    if falhas == 0:
        return None  # não falhou de novo aqui: a falha veio de outra coisa (ambiente, CI)
    return falhas == vezes


def isolar(pasta: Path, base: str, head: str, testes: list[str]) -> str | None:
    """O commit culpado pelo `git bisect run`, entre a base (boa) e o head (ruim)."""
    if not testes or not base or base == head:
        return None
    try:
        rodar(["git", "bisect", "start", head, base], pasta)
        # O pytest direto, sem script de shell: funciona igual no Linux e no Windows (validação de 17/11).
        if rodar(["git", "bisect", "run", *comando_dos_testes(testes)], pasta, tempo=1800).returncode != 0:
            return None
        # A referência que o bisect grava, e não a frase da saída: o git novo escreve "the first 'bad' commit",
        # com aspas, e a frase pode vir traduzida (validação de 17/11).
        culpado = rodar(["git", "rev-parse", "--short=7", "refs/bisect/bad"], pasta).stdout.strip()
        return culpado or None
    finally:
        rodar(["git", "bisect", "reset"], pasta)


def diff_do_commit(pasta: Path, commit: str) -> str:
    return rodar(["git", "show", "--unified=5", "--format=%h %s", commit], pasta).stdout[:TAMANHO_DO_DIFF]


def tirar_bloco_de_codigo(texto: str) -> str:
    achou = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", texto, re.DOTALL)
    return (achou.group(1) if achou else texto).strip() + "\n"


def aplicar(pasta: Path, arquivo: Path) -> bool:
    """O `git apply`, e, se a IA errou o número das linhas, o `patch` com folga no contexto."""
    if rodar(["git", "apply", "--recount", "--whitespace=nowarn", str(arquivo)], pasta).returncode == 0:
        return True
    # A IA às vezes manda o trecho só com o contexto de antes da linha alterada; sem contexto depois, o git
    # exige que a mudança esteja no fim do arquivo. `--unidiff-zero` tira essa exigência (validação de 17/11).
    if rodar(["git", "apply", "--recount", "--unidiff-zero", "--whitespace=nowarn", str(arquivo)], pasta).returncode == 0:
        return True
    return bool(shutil.which("patch")) and rodar(["patch", "-p1", "--forward", "--fuzz=3", "-i", str(arquivo)], pasta).returncode == 0


def conferir_patch(pasta: Path, patch: str, testes: list[str]) -> tuple[bool, bool]:
    """Aplica o patch na cópia de trabalho, roda os testes que falhavam e desfaz. (aplicou, testes passaram)."""
    arquivo = pasta / ".patch-depuracao.diff"
    arquivo.write_text(patch, encoding="utf-8", newline="\n")
    try:
        if not aplicar(pasta, arquivo):
            return False, False
        return True, rodar(comando_dos_testes(testes), pasta).returncode == 0
    finally:
        rodar(["git", "checkout", "--", "."], pasta)
        arquivo.unlink(missing_ok=True)


def so_a_hipotese(resposta: str) -> str:
    """O texto da hipótese, sem o patch e sem a linha que o anuncia ("**Patch:**")."""
    linhas = []
    for linha in resposta.split("```")[0].strip().splitlines():
        if "patch" in linha.lower() and len(linha) < 40:
            break
        linhas.append(linha)
    return "\n".join(linhas).replace("**Hipótese testável:**", "").strip()[:600]


# ── As fases ──────────────────────────────────────────────────────────────


@dataclass
class Investigacao:
    execucao: str
    head: str
    base: str
    testes: list[str]
    cenarios: list[str]
    tipo: str = ""
    resumo: str = ""
    consistente: bool | None = None
    commit_culpado: str | None = None
    hipoteses: list[dict[str, Any]] = field(default_factory=list)
    patch: str = ""
    # Os patches de cada hipótese: vão para o artefato da execução, não para a issue.
    patches_tentados: list[str] = field(default_factory=list)
    suite_passou: bool | None = None
    fase: str = "detectado"
    parou: str = ""
    custo: float = 0.0
    segundos: float = 0.0


def classificar(ia: IA, falha: Falha, diffstat: str) -> tuple[str, str]:
    resposta = ia.perguntar(
        "1. coleta",
        "O CI da Maria falhou. Na 1ª linha, só o tipo do defeito: função, demora, segurança, conversa ou IA. Depois, em até 6 linhas: "
        f"o observado, o esperado e os arquivos suspeitos.\n\nTestes que falharam: {', '.join(falha.testes) or 'nenhum'}\n"
        f"Cenários que falharam: {', '.join(falha.cenarios) or 'nenhum'}\n\n"
        f"Fim da saída:\n{falha.trecho}\n\nArquivos mudados:\n{diffstat[:1500]}",
        500,
    )
    primeira = resposta.strip().splitlines()[0].lower() if resposta.strip() else ""
    tipo = next((t for t in ("função", "demora", "segurança", "conversa", "ia") if t in primeira), "função")
    return tipo, resposta.strip()


def investigar(pasta: Path, falha: Falha, base: str, head: str, execucao: str, ia: IA) -> Investigacao:
    inicio = time.monotonic()
    inv = Investigacao(execucao, head[:7], base[:7], falha.testes, falha.cenarios)
    try:
        diffstat = rodar(["git", "diff", "--stat", base, head], pasta).stdout if base else ""
        inv.tipo, inv.resumo = classificar(ia, falha, diffstat)
        inv.fase = "classificado"
        inv.consistente = reproduzir(pasta, falha.testes)
        if inv.consistente is None:
            inv.parou = "os testes não falharam de novo aqui, ou só falharam cenários do ponta a ponta: precisa de pessoa"
            return inv
        if inv.consistente is False:
            inv.fase = "intermitente"
            inv.parou = "a falha é intermitente: sem patch, precisa de pessoa"
            return inv
        inv.fase = "reproduzido"
        inv.commit_culpado = isolar(pasta, base, head, falha.testes)
        inv.fase = "isolado" if inv.commit_culpado else inv.fase
        diff = diff_do_commit(pasta, inv.commit_culpado or head)
        retorno = ""
        for tentativa in range(1, HIPOTESES + 1):
            resposta = ia.perguntar(
                f"4. causa, hipótese {tentativa}",
                "Dê UMA hipótese testável para a causa, em até 4 linhas, e depois o patch em diff unificado (bloco ```diff) que corrige "
                f"a causa.\n\nResumo da falha:\n{inv.resumo}\n\nTestes que falham: {', '.join(falha.testes)}\n\n"
                f"Diff do commit:\n{diff}{retorno}",
                900,
            )
            patch = tirar_bloco_de_codigo(resposta)
            aplicou, passou = conferir_patch(pasta, patch, falha.testes)
            inv.hipoteses.append(
                {"tentativa": tentativa, "hipotese": so_a_hipotese(resposta), "aplicou": aplicou, "testes_passaram": passou}
            )
            inv.patches_tentados.append(patch)
            if passou:
                inv.patch = patch
                inv.fase = "causa achada"
                break
            retorno = f"\n\nA hipótese {tentativa} não passou nos testes. Patch que falhou:\n{patch[:3000]}\nTente outra causa."
        if not inv.patch:
            inv.parou = f"{HIPOTESES} hipóteses falharam: precisa de pessoa"
            return inv
        arquivo = pasta / ".patch-depuracao.diff"
        arquivo.write_text(inv.patch, encoding="utf-8", newline="\n")
        try:
            aplicar(pasta, arquivo)
            inv.suite_passou = rodar(["uv", "run", "--frozen", "pytest", "-q", "-p", "no:cacheprovider"], pasta, tempo=1800).returncode == 0
        finally:
            rodar(["git", "checkout", "--", "."], pasta)
            arquivo.unlink(missing_ok=True)
        inv.fase = "correção pronta" if inv.suite_passou else "causa achada"
        if not inv.suite_passou:
            inv.parou = "o patch conserta os testes que falhavam, mas quebra outros: precisa de pessoa"
    except EstourouTeto as erro:
        inv.parou = f"parou no teto de custo: {erro}"
    finally:
        inv.custo = round(ia.orcamento.gasto, 6)
        inv.segundos = round(time.monotonic() - inicio, 1)
    return inv


# ── Registro ──────────────────────────────────────────────────────────────


def _lista_de_testes(testes: list[str], quantos: int = 6) -> str:
    if not testes:
        return "nenhum"
    lista = ", ".join(f"`{t}`" for t in testes[:quantos])
    return lista + (f" e mais {len(testes) - quantos}" if len(testes) > quantos else "")


def _resultado_da_hipotese(hipotese: dict[str, Any]) -> str:
    if hipotese["testes_passaram"]:
        return "✅"
    return "❌ (os testes falharam com o patch)" if hipotese.get("aplicou") else "❌ (o patch não aplicou)"


def _reproducao(consistente: bool | None) -> str:
    if consistente:
        return "consistente (falhou 3 de 3)"
    return "intermitente" if consistente is False else "não reproduzida aqui"


def corpo_da_issue(inv: Investigacao, endereco_da_execucao: str) -> str:
    """A issue pública: nomes de teste, commits, hipóteses e custo. Nunca a saída do CI nem conteúdo de log."""
    feito = {
        "detectado": 1,
        "classificado": 1,
        "intermitente": 2,
        "reproduzido": 2,
        "isolado": 3,
        "causa achada": 4,
        "correção pronta": 5,
    }.get(inv.fase, 1)
    fases = ["Detecção e coleta", "Reprodução", "Isolamento (git bisect)", "Causa raiz", "Correção", "Registro"]
    linhas = [
        f"**Aberta pela depuração com IA (#503)** a partir da [execução do CI que falhou]({endereco_da_execucao}). Sem PR automático: "
        "o patch, se houver, está nos artefatos da execução da depuração.",
        "",
        "## Fases",
        *[f"- [{'x' if i < feito or i == 5 else ' '}] {i + 1}. {nome}" for i, nome in enumerate(fases)],
        "",
        "## O que falhou",
        f"- **Tipo:** {inv.tipo or 'não classificado'}",
        f"- **Testes ({len(inv.testes)}):** {_lista_de_testes(inv.testes)}",
        f"- **Cenários do ponta a ponta:** {', '.join(inv.cenarios) or 'nenhum'}",
        f"- **Reprodução:** {_reproducao(inv.consistente)}",
        f"- **Commits:** base `{inv.base or '?'}`, que falha `{inv.head}`; culpado pelo bisect: `{inv.commit_culpado or 'não isolado'}`",
        "",
        "## Hipóteses",
        *(
            [f"{h['tentativa']}. {_resultado_da_hipotese(h)} {h['hipotese']}" for h in inv.hipoteses]
            or ["Nenhuma: a investigação parou antes da causa."]
        ),
        "",
        f"**Situação:** {inv.fase}. "
        + (f"**Parou:** {inv.parou}." if inv.parou else "Patch conferido pelos testes que falhavam e pela suíte rápida."),
        f"**Custo de IA:** US$ {inv.custo:.4f} (teto de US$ {TETO_USD:.2f}, no preço do Haiku) · {inv.segundos:.0f} s",
        "",
        MARCA_DO_VISOR,
        "```json",
        json.dumps(
            asdict(inv) | {"resumo": "", "patch": bool(inv.patch), "patches_tentados": len(inv.patches_tentados)}, ensure_ascii=False
        ),
        "```",
    ]
    return "\n".join(linhas) + "\n"


def titulo_da_issue(inv: Investigacao) -> str:
    alvo = inv.testes[0].split("::")[-1] if inv.testes else (inv.cenarios[0] if inv.cenarios else "falha do CI")
    return f"[BUG] Depuração com IA: {alvo} ({inv.fase})"[:120]


def abrir_issue(inv: Investigacao, endereco_da_execucao: str, repositorio: str) -> None:
    rodar(
        ["gh", "label", "create", ETIQUETA, "-R", repositorio, "--color", "B60205", "--description", "Aberta pela depuração com IA (#503)"],
        Path("."),
    )
    corpo = corpo_da_issue(inv, endereco_da_execucao)
    if inv.parou.startswith("parou no teto"):
        corpo += f"\n{AVISAR}: a investigação parou no teto de custo. Vale passar o valor nesta verificação?\n"
    rodar(["gh", "issue", "create", "-R", repositorio, "--title", titulo_da_issue(inv), "--label", ETIQUETA, "--body", corpo], Path("."))


# ── Entrada ───────────────────────────────────────────────────────────────


def log_da_execucao(execucao: str, repositorio: str) -> str:
    return rodar(["gh", "run", "view", execucao, "-R", repositorio, "--log-failed"], Path("."), tempo=300).stdout


def main() -> int:
    argumentos = argparse.ArgumentParser(description="Depuração com IA (#503)")
    argumentos.add_argument("--execucao", default="", help="id da execução do CI que falhou (no Actions)")
    argumentos.add_argument("--log", default="", help="arquivo com a saída que falhou (validação na máquina)")
    argumentos.add_argument("--base", default="", help="o commit bom (a base do PR)")
    argumentos.add_argument("--head", default="", help="o commit que falha")
    argumentos.add_argument("--repositorio", default=os.environ.get("GITHUB_REPOSITORY", "dgd-dprj/maria-langgraph-pp"))
    argumentos.add_argument("--sem-issue", action="store_true", help="imprime a issue em vez de abrir")
    argumentos.add_argument("--saida", default="depuracao", help="pasta do patch e do resultado")
    opcoes = argumentos.parse_args()

    log = (
        Path(opcoes.log).read_text(encoding="utf-8", errors="replace")
        if opcoes.log
        else log_da_execucao(opcoes.execucao, opcoes.repositorio)
    )
    falha = ler_falhas(log)
    if not falha.testes and not falha.cenarios:
        print("Nenhum teste nem cenário falhou nesta execução: nada a investigar.")
        return 0
    head = opcoes.head or rodar(["git", "rev-parse", "HEAD"], Path(".")).stdout.strip()
    # Uma cópia de trabalho à parte, para o bisect e os patches não mexerem na pasta da rotina.
    pasta = Path(tempfile.mkdtemp(prefix="depuracao-"))
    rodar(["git", "worktree", "add", "--detach", str(pasta), head], Path("."))
    try:
        ia = IA(modelo_do_bedrock(), Orcamento())
        servidor = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        endereco = f"{servidor}/{opcoes.repositorio}/actions/runs/{opcoes.execucao}" if opcoes.execucao else "(validação local)"
        inv = investigar(pasta, falha, opcoes.base, head, opcoes.execucao or "local", ia)
    finally:
        rodar(["git", "worktree", "remove", "--force", str(pasta)], Path("."))
        shutil.rmtree(pasta, ignore_errors=True)
    destino = Path(opcoes.saida)
    destino.mkdir(parents=True, exist_ok=True)
    if inv.patch:
        (destino / "patch.diff").write_text(inv.patch, encoding="utf-8", newline="\n")
    (destino / "investigacao.json").write_text(
        json.dumps(asdict(inv) | {"chamadas": ia.orcamento.chamadas}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if opcoes.sem_issue:
        print(titulo_da_issue(inv))
        print(corpo_da_issue(inv, endereco))
    else:
        abrir_issue(inv, endereco, opcoes.repositorio)
    print(f"Fase: {inv.fase}. Custo: US$ {inv.custo:.4f}. {inv.parou}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
