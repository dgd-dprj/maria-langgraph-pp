"""QA de ponta a ponta dos fluxos que consultam o Verde (#502).

O QA da staging não confere esses fluxos, porque o Verde de homologação tem cópia de dados
reais. Este roteiro conversa pela API, como a Tykhe, com a Maria inteira no
`docker-compose.yml` mais o `docker-compose.ponta-a-ponta.yml`: imagem, uvicorn, Postgres
e checkpoint de verdade, com o Verde, a IA e o e-mail simulados. Nada sai da máquina.

Uso (com a Maria no ar em http://127.0.0.1:3001):

    uv run python scripts/qa/fluxos_ponta_a_ponta.py [--grupo normal|falha-encaminhamento]

A chave vem de API_KEY (a mesma do compose). Saída: o resumo em Markdown; código 1 se
algum cenário falhar, com o passo, o que foi enviado e o que voltou. Todos os dados são
inventados ou sentinelas do mock do Verde (`maria.integracoes.verde`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA
from maria.integracoes.verde import CPF_MOCK_FALHA_INFRA, CPF_MOCK_NAO_ENCONTRADO

PP, VD, PS = ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, ID_PROBLEMAS_PLANO_SAUDE

PROCESSO = "0000088-95.2026.8.19.0010"  # o mock do Verde encontra (origem SEEU)
PROCESSO_ORIGEM_NAO_SUPORTADA = "0000000-00.0000.0.00.0000"
RG = "11111111111"  # todos iguais: nunca é CPF válido (#497); o mock acha o apenado
RG_LIBERTADO = "22222222222"  # sentinela: situação fora do permitido
CPF_VALIDO = "12345678909"
CPF_CONTA_ERRADA = "12345678900"
CPF_NO_LUGAR_DO_RG = "123.456.789-09"
CEP = {"endereco": {"cep": "20000000"}}
LINK_FRENTE = "https://downloads.tykhe.dev/arquivos/qa-frente?token=qa-frente"
LINK_VERSO = "https://downloads.tykhe.dev/arquivos/qa-verso?token=qa-verso"


@dataclass(frozen=True)
class Passo:
    """`iniciar` abre o atendimento (POST /atendimentos); senão, `resposta` vai para /atendimentos/respostas.

    `espera` confere a resposta: `texto` (trecho de `resposta`), `status`, `tipoResposta`, `destino`
    e os campos de `metadados` com o prefixo `metadados.`.
    """

    resposta: str | None = None
    iniciar: tuple[str, dict[str, Any]] | None = None
    espera: dict[str, Any] = field(default_factory=dict)


def iniciar(fluxo: str, dados: dict[str, Any] | None = None, **espera: Any) -> Passo:
    return Passo(iniciar=(fluxo, dados or {}), espera=_espera(espera))


def responder(resposta: str, **espera: Any) -> Passo:
    return Passo(resposta=resposta, espera=_espera(espera))


def _espera(espera: dict[str, Any]) -> dict[str, Any]:
    # `metadados__motivoHandoff=...` vira "metadados.motivoHandoff".
    return {chave.replace("__", "."): valor for chave, valor in espera.items()}


@dataclass(frozen=True)
class Cenario:
    nome: str
    passos: tuple[Passo, ...]


EM_ANDAMENTO = {"status": "em_andamento"}

CENARIOS_NORMAIS: tuple[Cenario, ...] = (
    Cenario(
        "Pessoa presa com processo, até o fim (concluído)",
        (
            iniciar(PP, texto="número do processo", tipoResposta="sim_nao"),
            responder("Sim", texto="Qual o número do processo"),
            responder(PROCESSO, texto="RG da pessoa presa"),
            responder(RG, texto="Confirma que a pessoa presa é"),
            responder("Sim", texto="parentesco"),
            responder("amigo", status="concluido"),
        ),
    ),
    Cenario(
        "Pessoa presa sem processo (atendimento humano)",
        (
            iniciar(PP),
            responder("Não", texto="RG da pessoa presa"),
            responder(RG, texto="Confirma que a pessoa presa é"),
            responder("Sim", texto="parentesco"),
            responder("amigo", status="handoff_humano", metadados__motivoHandoff="sem_numero_processo"),
        ),
    ),
    Cenario(
        "Pessoa presa com processo de origem não suportada",
        (
            iniciar(PP),
            responder("Sim"),
            responder(PROCESSO_ORIGEM_NAO_SUPORTADA, texto="RG da pessoa presa"),
            responder(RG),
            responder("Sim"),
            responder("amigo", status="handoff_humano", metadados__motivoHandoff="origem_processo_nao_suportada"),
        ),
    ),
    Cenario(
        "Pessoa presa fora do permitido (libertada)",
        (
            iniciar(PP),
            responder("Sim"),
            responder(PROCESSO),
            responder(RG_LIBERTADO),
            responder("Sim"),
            responder("amigo", status="handoff_humano", metadados__motivoHandoff="dados_pessoa_nao_atendidos"),
        ),
    ),
    Cenario(
        "Pessoa presa: CPF no lugar do RG não vai ao Verde (#497)",
        (
            iniciar(PP),
            responder("Não"),
            responder(CPF_NO_LUGAR_DO_RG, texto="parece um CPF", **EM_ANDAMENTO),
            responder(CPF_NO_LUGAR_DO_RG, texto="tentativa 2 de 3", **EM_ANDAMENTO),
            responder(CPF_NO_LUGAR_DO_RG, status="handoff_humano", metadados__motivoHandoff="rg_formato_invalido"),
        ),
    ),
    Cenario(
        "Pessoa presa: a conversa continua do checkpoint no Postgres",
        (
            iniciar(PP),
            responder("Não", texto="RG da pessoa presa"),
            iniciar(PP, texto="RG da pessoa presa"),
        ),
    ),
    Cenario(
        "Violência doméstica sem RO, com CPF, até o fim (padrão)",
        (
            iniciar(VD, texto="vítima de violência doméstica", tipoResposta="sim_nao"),
            responder("Sim"),
            responder("Não"),
            responder("Não", texto="Qual o seu CPF"),
            responder(CPF_VALIDO, status="concluido", metadados__tipoEncaminhamento="padrao"),
        ),
    ),
    Cenario(
        "Violência doméstica com RO e CPF conhecido (urgente, com protocolo)",
        (
            iniciar(VD, {"cpf": CPF_VALIDO, "idPessoa": 1, "nome": "Pessoa de Teste"}),
            responder("Sim"),
            responder("Não"),
            responder("Sim", status="concluido", texto="Protocolo", metadados__tipoEncaminhamento="urgente"),
        ),
    ),
    Cenario(
        "Violência doméstica: quem não é vítima vai ao atendimento humano",
        (
            iniciar(VD),
            responder("Não", status="handoff_humano", metadados__motivoHandoff="nao_e_vitima"),
        ),
    ),
    Cenario(
        "Violência doméstica: CPF com a conta errada não vai ao Verde (#497)",
        (
            iniciar(VD),
            responder("Sim"),
            responder("Não"),
            responder("Não", texto="Qual o seu CPF"),
            responder(CPF_CONTA_ERRADA, texto="Esse CPF não está certo", **EM_ANDAMENTO),
            responder(CPF_VALIDO, status="concluido"),
        ),
    ),
    Cenario(
        "Violência doméstica: CPF não encontrado e nova tentativa",
        (
            iniciar(VD),
            responder("Sim"),
            responder("Não"),
            responder("Não", texto="Qual o seu CPF"),
            responder(CPF_MOCK_NAO_ENCONTRADO, texto="Não encontrei ninguém com esse CPF", **EM_ANDAMENTO),
            responder(CPF_VALIDO, status="concluido"),
        ),
    ),
    Cenario(
        "Violência doméstica: falha do Verde ao buscar o CPF",
        (
            iniciar(VD),
            responder("Sim"),
            responder("Não"),
            responder("Não", texto="Qual o seu CPF"),
            responder(CPF_MOCK_FALHA_INFRA, status="handoff_humano", metadados__motivoHandoff="falha_infra_verde"),
        ),
    ),
    Cenario(
        "Plano de saúde para a própria pessoa, com as fotos por link, até o e-mail",
        (
            iniciar(PS, {**CEP, "relato": "o plano negou a cirurgia"}, texto="para você", tipoResposta="sim_nao"),
            responder("Sim", tipoResposta="link_imagem"),
            responder(LINK_FRENTE, tipoResposta="link_imagem"),
            responder(LINK_VERSO, texto="renda"),
            responder("2500"),
            responder("Sim", status="concluido", destino="email_enviado"),
        ),
    ),
    Cenario(
        "Plano de saúde para outra pessoa com CPF inválido 3 vezes",
        (
            iniciar(PS, CEP),
            responder("Não", texto="CPF da pessoa que será atendida"),
            responder("123"),
            responder("456"),
            responder("789", status="handoff_humano", metadados__motivoHandoff="cpf_outra_pessoa_invalido"),
        ),
    ),
)

CENARIOS_FALHA_ENCAMINHAMENTO: tuple[Cenario, ...] = (
    Cenario(
        "Violência doméstica: falha ao criar o encaminhamento não finge sucesso",
        (
            iniciar(VD, {"cpf": CPF_VALIDO}),
            responder("Sim"),
            responder("Não"),
            responder("Sim", status="handoff_humano", metadados__motivoHandoff="falha_encaminhamento"),
        ),
    ),
)

GRUPOS = {"normal": CENARIOS_NORMAIS, "falha-encaminhamento": CENARIOS_FALHA_ENCAMINHAMENTO}


def _post(base: str, chave: str, caminho: str, corpo: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    pedido = urllib.request.Request(
        base + caminho,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {chave}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as erro:
        return erro.code, json.loads(erro.read() or b"{}")


def _valor(corpo: dict[str, Any], chave: str) -> Any:
    atual: Any = corpo
    for parte in chave.split("."):
        atual = atual.get(parte) if isinstance(atual, dict) else None
    return atual


def _diferencas(status_http: int, corpo: dict[str, Any], espera: dict[str, Any]) -> list[str]:
    if status_http != 200:
        return [f"HTTP {status_http}"]
    erros = []
    for chave, esperado in espera.items():
        if chave == "texto":
            if esperado not in str(corpo.get("resposta", "")):
                erros.append(f"a resposta não tem «{esperado}»")
        elif _valor(corpo, chave) != esperado:
            erros.append(f"{chave} = {_valor(corpo, chave)!r}, esperado {esperado!r}")
    return erros


def rodar(base: str, chave: str, cenario: Cenario, numero: int) -> tuple[bool, str]:
    chat_id = f"qa-ponta-{time.strftime('%H%M%S')}-{numero}"
    for indice, passo in enumerate(cenario.passos, start=1):
        if passo.iniciar is not None:
            fluxo, dados = passo.iniciar
            corpo_pedido: dict[str, Any] = {"chatId": chat_id, "flowId": fluxo}
            if dados:
                corpo_pedido["dadosConhecidos"] = dados
            enviado = "início do fluxo"
            status_http, corpo = _post(base, chave, "/atendimentos", corpo_pedido)
        else:
            assert passo.resposta is not None
            enviado = f"«{passo.resposta}»"
            status_http, corpo = _post(base, chave, "/atendimentos/respostas", {"chatId": chat_id, "resposta": passo.resposta})
        erros = _diferencas(status_http, corpo, passo.espera)
        if erros:
            recebido = (
                f"status {corpo.get('status')!r}, tipoResposta {corpo.get('tipoResposta')!r}, "
                f"motivo {_valor(corpo, 'metadados.motivoHandoff')!r}, resposta «{str(corpo.get('resposta', ''))[:160]}»"
            )
            return False, f"passo {indice} ({enviado}): {'; '.join(erros)}. Recebido: {recebido}"
    return True, f"{len(cenario.passos)} passos"


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    argumentos.add_argument("--base", default="http://127.0.0.1:3001")
    argumentos.add_argument("--grupo", choices=sorted(GRUPOS), default="normal")
    opcoes = argumentos.parse_args()
    chave = os.environ.get("API_KEY", "troque-esta-chave")

    linhas = [
        f"### QA de ponta a ponta: grupo `{opcoes.grupo}` (Verde, IA e e-mail simulados)",
        "",
        "| Cenário | Resultado | Detalhe |",
        "|---|---|---|",
    ]
    falhas = 0
    for numero, cenario in enumerate(GRUPOS[opcoes.grupo], start=1):
        ok, detalhe = rodar(opcoes.base, chave, cenario, numero)
        falhas += not ok
        linhas.append(f"| {cenario.nome} | {'OK' if ok else '**FALHOU**'} | {detalhe} |")
    total = len(GRUPOS[opcoes.grupo])
    linhas += ["", f"**{total - falhas} de {total} cenários OK.**"]
    print("\n".join(linhas))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
