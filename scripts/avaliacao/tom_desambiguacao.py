"""Comparação do tom da pergunta de desambiguação: Haiku × Qwen × Qwen com o tom (#508).

Decisões da Nicole (2026-11-16): o Qwen vai ser a IA de frente e deve ser simpático; o tom entra só na
desambiguação; emoji permitido, nunca nos temas sensíveis; a nota vem de regras automáticas e de uma amostra
que a Nicole e a acessibilidade avaliam no Visor (visor-maria#12).

Uso (na pasta maria-langgraph-pp, com credencial da AWS que chame o Bedrock nas duas regiões):

    uv run python scripts/avaliacao/tom_desambiguacao.py [--passadas 2] [--saida docs/avaliacoes/tom-desambiguacao.json]

- 30 relatos inventados e ambíguos, com duas opções do catálogo real do orquestrador (release);
- três versões: o Haiku com o prompt de hoje (a produção), o Qwen com o prompt de antes da #508 e o Qwen com o tom;
- a chamada é a mesma da Maria (`toolConfig` da ferramenta `extract`, sem `inferenceConfig`), e o prompt sai de
  `maria.ia.desambiguar.montar_sistema`;
- custo pelo `usage` de cada chamada, no preço do Haiku `us.` (US$ 1,10 e US$ 5,50 por milhão), o teto seguro:
  o Qwen custa menos. Aprovado pela Nicole: cerca de US$ 0,30; o roteiro para se passar de US$ 0,35.

Saída: o JSON com cada pergunta, as regras e o custo, e o resumo em Markdown no fim. Relatos inventados, sem dado
de pessoa nenhuma.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3  # type: ignore[import-untyped]  # sem stubs no projeto; a Maria chama o Bedrock pelo langchain-aws

from maria.ia.ajuste_qwen import SUFIXO_DESAMBIGUAR
from maria.ia.desambiguar import ESQUEMA_PERGUNTA, CandidatoParaDesambiguar, montar_sistema, sem_emoji, tem_tema_sensivel
from maria.ia.tom import TEM_EMOJI, medir_tom

HAIKU = ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "us-east-1")
QWEN = ("qwen.qwen3-vl-235b-a22b", "sa-east-1")
VERSOES = {"haiku": "Haiku, prompt de hoje (produção)", "qwen": "Qwen, prompt de antes da #508", "qwen_tom": "Qwen com o tom (#508)"}
PRECO_ENTRADA, PRECO_SAIDA = 1.10, 5.50  # US$ por milhão de tokens, Haiku `us.`
TETO_USD = 0.35

# Relatos inventados, cada um com as duas opções do catálogo que ele deixa em dúvida.
RELATOS: list[tuple[str, tuple[str, str]]] = [
    ("Meu irmão foi preso semana passada e eu queria saber como está o processo dele.", ("pessoa-presa", "ver-andamento-do-processo")),
    ("Meu filho está na cadeia e a audiência dele foi remarcada, não sei a nova data.", ("pessoa-presa", "ver-meus-agendamentos")),
    ("Prenderam meu marido ontem e ninguém me fala nada, quero entrar com alguma coisa.", ("pessoa-presa", "iniciar-novo-processo")),
    ("Meu sobrinho foi preso e eu não sei se ele já tem advogado ou processo aberto.", ("pessoa-presa", "ver-andamento-do-processo")),
    ("Quero visitar meu pai que está preso e também saber quando sai a decisão.", ("pessoa-presa", "ver-andamento-do-processo")),
    ("Meu companheiro me bate e eu quero me separar dele.", ("violencia-domestica", "iniciar-novo-processo")),
    ("Meu ex me ameaça desde que eu pedi pensão para as crianças.", ("violencia-domestica", "iniciar-novo-processo")),
    (
        "Já tenho medida protetiva mas ele continua me perseguindo, quero saber do processo.",
        ("violencia-domestica", "ver-andamento-do-processo"),
    ),
    (
        "Meu marido me xinga e quebrou minhas coisas, tenho uma audiência marcada sobre a guarda.",
        ("violencia-domestica", "ver-meus-agendamentos"),
    ),
    ("Meu ex foi preso por me agredir e agora a família dele me ameaça.", ("violencia-domestica", "pessoa-presa")),
    ("O plano não autorizou minha cirurgia e o médico disse que é urgente.", ("problemas-plano-de-saude", "questoes-de-saude")),
    ("Preciso de uma cirurgia no joelho e não sei se é pelo convênio ou pelo posto.", ("problemas-plano-de-saude", "questoes-de-saude")),
    ("Minha mãe precisa de internação e o hospital pediu autorização do plano.", ("problemas-plano-de-saude", "questoes-de-saude")),
    ("O convênio negou o exame e a cirurgia do meu filho.", ("problemas-plano-de-saude", "questoes-de-saude")),
    ("Estou esperando cirurgia há meses e quero saber se dá para entrar na justiça.", ("questoes-de-saude", "iniciar-novo-processo")),
    (
        "Quero saber do meu processo de pensão, acho que tinha uma audiência essa semana.",
        ("ver-andamento-do-processo", "ver-meus-agendamentos"),
    ),
    ("Me ligaram da Defensoria sobre meu caso e eu perdi a ligação.", ("ver-andamento-do-processo", "ver-meus-agendamentos")),
    (
        "Tenho um atendimento marcado mas não sei se é sobre o processo antigo ou um novo.",
        ("ver-meus-agendamentos", "iniciar-novo-processo"),
    ),
    ("Não consigo entrar no aplicativo para ver meu horário marcado.", ("ajuda-app-defensoria-rj", "ver-meus-agendamentos")),
    ("O aplicativo não mostra meu processo, sumiu tudo.", ("ajuda-app-defensoria-rj", "ver-andamento-do-processo")),
    ("Fiz o cadastro no aplicativo e queria abrir um pedido de divórcio.", ("ajuda-app-defensoria-rj", "iniciar-novo-processo")),
    ("Meu senhorio quer me despejar e eu não sei o que fazer.", ("iniciar-novo-processo", "outros-assuntos")),
    ("Comprei uma geladeira com defeito e a loja não troca.", ("iniciar-novo-processo", "outros-assuntos")),
    ("Quero tirar a segunda via da certidão de nascimento.", ("outros-assuntos", "iniciar-novo-processo")),
    ("Meu pai faleceu e quero saber dos bens dele.", ("iniciar-novo-processo", "outros-assuntos")),
    ("Tenho um processo de guarda e quero remarcar a data que me deram.", ("ver-meus-agendamentos", "ver-andamento-do-processo")),
    ("Meu filho foi detido na escola e levaram ele para a delegacia.", ("pessoa-presa", "outros-assuntos")),
    ("Quero pensão do pai da minha filha e ele já foi violento comigo.", ("iniciar-novo-processo", "violencia-domestica")),
    ("O remédio da minha avó acabou no posto e o plano também não cobre.", ("questoes-de-saude", "problemas-plano-de-saude")),
    ("Quero cancelar o atendimento de amanhã e saber se meu processo andou.", ("ver-meus-agendamentos", "ver-andamento-do-processo")),
]


@dataclass
class Resultado:
    caso: int
    relato: str
    opcoes: list[str]
    sensivel: bool
    versao: str
    passada: int
    pergunta_bruta: str
    pergunta: str
    regras: dict[str, bool]
    tokens_entrada: int
    tokens_saida: int
    custo: float
    erro: str = ""


def regras(pergunta: str, sensivel: bool) -> dict[str, bool]:
    """As mesmas regras que a Maria mede na produção (`maria.ia.tom`), com os nomes do JSON da comparação."""
    m = medir_tom(pergunta, sensivel)
    return {
        "termina_em_pergunta": bool(m["terminaEmPergunta"]),
        "ate_25_palavras": bool(m["ateLimiteDePalavras"]),
        "sem_termo_tecnico": bool(m["semTermoTecnico"]),
        "oferece_as_alternativas": bool(m["ofereceAlternativas"]),
        "sem_emoji_no_tema_sensivel": bool(m["semEmojiNoTemaSensivel"]),
        "tem_acolhimento": bool(m["temAcolhimento"]),
    }


def sistema_da_versao(versao: str, candidatos: list[CandidatoParaDesambiguar]) -> str:
    os.environ["BEDROCK_MODEL_ID"] = HAIKU[0]
    base = montar_sistema(candidatos)  # com o Haiku, o prompt de hoje
    if versao == "haiku":
        return base
    if versao == "qwen":
        return base + SUFIXO_DESAMBIGUAR  # o Qwen antes da #508
    os.environ["BEDROCK_MODEL_ID"] = QWEN[0]
    return montar_sistema(candidatos)  # o Qwen com o tom


class Bedrock:
    def __init__(self) -> None:
        sessao = boto3.Session()
        self._clientes = {r: sessao.client("bedrock-runtime", region_name=r) for r in {HAIKU[1], QWEN[1]}}
        self._trava = threading.Lock()
        self.gasto = 0.0

    def perguntar(self, versao: str, sistema: str, relato: str) -> tuple[str, int, int]:
        with self._trava:
            if self.gasto > TETO_USD:
                raise SystemExit(f"PARADO: gasto de US$ {self.gasto:.4f} passou do teto de US$ {TETO_USD}. Avisar a Nicole e o Ícaro.")
        modelo, regiao = HAIKU if versao == "haiku" else QWEN
        resposta = self._clientes[regiao].converse(
            modelId=modelo,
            system=[{"text": sistema}],
            messages=[{"role": "user", "content": [{"text": relato}]}],
            toolConfig={
                "tools": [
                    {
                        "toolSpec": {
                            "name": "extract",
                            "inputSchema": {"json": ESQUEMA_PERGUNTA},
                            "description": "A function available to call.",
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": "extract"}},
            },
        )
        uso = resposta.get("usage", {})
        entrada, saida = int(uso.get("inputTokens", 0)), int(uso.get("outputTokens", 0))
        with self._trava:
            self.gasto += (entrada * PRECO_ENTRADA + saida * PRECO_SAIDA) / 1e6
        pergunta = ""
        for bloco in resposta["output"]["message"]["content"]:
            if "toolUse" in bloco:
                pergunta = str(bloco["toolUse"]["input"].get("pergunta", ""))
        return pergunta, entrada, saida


def main() -> int:
    argumentos = argparse.ArgumentParser(description="Comparação do tom da desambiguação (#508)")
    argumentos.add_argument("--passadas", type=int, default=2)
    argumentos.add_argument("--saida", default="docs/avaliacoes/tom-desambiguacao.json")
    argumentos.add_argument("--recalcular", action="store_true", help="refaz só as regras sobre o JSON de --saida, sem chamar o Bedrock")
    opcoes = argumentos.parse_args()
    if opcoes.recalcular:
        return recalcular(Path(opcoes.saida))

    os.environ.setdefault("MARIA_AMBIENTE", "release")  # o catálogo do release, com o plano de saúde
    from maria.fluxos import catalogo_para_classificacao

    catalogo = {o["nome"]: o for o in asyncio.run(catalogo_para_classificacao())}
    bedrock = Bedrock()
    tarefas = []
    for passada in range(1, opcoes.passadas + 1):
        for caso, (relato, nomes) in enumerate(RELATOS, start=1):
            candidatos: list[CandidatoParaDesambiguar] = [
                {"id": catalogo[n]["id"], "nome": catalogo[n]["nome"], "descricao": catalogo[n]["descricao"]} for n in nomes
            ]
            for versao in VERSOES:
                tarefas.append((caso, relato, nomes, candidatos, versao, passada, sistema_da_versao(versao, candidatos)))

    def rodar(tarefa: tuple[Any, ...]) -> Resultado:
        caso, relato, nomes, candidatos, versao, passada, sistema = tarefa
        sensivel = tem_tema_sensivel(candidatos)
        try:
            bruta, entrada, saida = bedrock.perguntar(versao, sistema, relato)
        except SystemExit:
            raise
        except Exception as erro:  # a chamada que falhou entra no resultado, sem parar as outras
            return Resultado(
                caso, relato, list(nomes), sensivel, versao, passada, "", "", regras("", sensivel), 0, 0, 0.0, type(erro).__name__
            )
        # A trava da #508 vale para a versão com o tom, como na Maria.
        final = sem_emoji(bruta) if versao == "qwen_tom" and sensivel else bruta
        custo = (entrada * PRECO_ENTRADA + saida * PRECO_SAIDA) / 1e6
        return Resultado(caso, relato, list(nomes), sensivel, versao, passada, bruta, final, regras(final, sensivel), entrada, saida, custo)

    with ThreadPoolExecutor(max_workers=4) as grupo:
        resultados = [asdict(r) for r in grupo.map(rodar, tarefas)]

    documento = {
        "issue": 508,
        "rodado_em": datetime.now(UTC).isoformat(timespec="seconds"),
        "passadas": opcoes.passadas,
        "relatos": len(RELATOS),
        "preco": "Haiku us.: US$ 1,10 e US$ 5,50 por milhão (teto seguro; o Qwen custa menos)",
        "custo_total": round(bedrock.gasto, 6),
        "resultados": resultados,
    }
    return gravar_e_resumir(documento, Path(opcoes.saida))


def gravar_e_resumir(documento: dict[str, Any], caminho: Path) -> int:
    """Aplica as regras de novo (sem chamar o Bedrock), refaz o resumo, grava o JSON e imprime o Markdown."""
    resultados: list[dict[str, Any]] = documento["resultados"]
    for r in resultados:
        r["regras"] = regras(r["pergunta"], r["sensivel"])
    resumo: dict[str, dict[str, Any]] = {}
    for versao, nome in VERSOES.items():
        da_versao = [r for r in resultados if r["versao"] == versao and not r["erro"]]
        resumo[versao] = {
            "nome": nome,
            "perguntas": len(da_versao),
            "erros": sum(1 for r in resultados if r["versao"] == versao and r["erro"]),
            "regras": {regra: sum(r["regras"][regra] for r in da_versao) for regra in regras("", False)},
            "palavras_em_media": round(sum(len(r["pergunta"].split()) for r in da_versao) / max(len(da_versao), 1), 1),
            "com_emoji": sum(1 for r in da_versao if TEM_EMOJI.search(r["pergunta"])),
            "custo": round(sum(r["custo"] for r in da_versao), 6),
        }
    documento["resumo"] = resumo
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(documento, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"## Tom da desambiguação (#508), {documento['relatos']} relatos × {len(VERSOES)} versões × {documento['passadas']} passadas\n")
    print("| Regra | " + " | ".join(VERSOES.values()) + " |")
    print("|---|" + "---|" * len(VERSOES))
    for regra in regras("", False):
        print(f"| {regra} | " + " | ".join(f"{resumo[v]['regras'][regra]} de {resumo[v]['perguntas']}" for v in VERSOES) + " |")
    print("| palavras em média | " + " | ".join(str(resumo[v]["palavras_em_media"]) for v in VERSOES) + " |")
    print("| com emoji | " + " | ".join(str(resumo[v]["com_emoji"]) for v in VERSOES) + " |")
    print(f"\n**Gasto: US$ {documento['custo_total']:.4f}** (teto aprovado: cerca de US$ 0,30; parada em US$ {TETO_USD}).")
    return 0


def recalcular(caminho: Path) -> int:
    """Só as regras e o resumo de novo, sobre as perguntas já geradas: nenhuma chamada paga."""
    return gravar_e_resumir(json.loads(caminho.read_text(encoding="utf-8")), caminho)


if __name__ == "__main__":
    sys.exit(main())
