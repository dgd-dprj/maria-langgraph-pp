"""Gera `cenarios.json` da conferência do crawler contra develop @ 1157a6d (spec 08, seção 7).

Cada cenário é uma rodada inteira do crawler: os planejados cadastrados na store em memória
e as respostas do Verde falso, por caminho e query. As árvores são inventadas. Violência
doméstica (categoria 10113) é sempre o primeiro alvo, como em develop.

Uso: python gerar_cenarios_coleta.py (grava cenarios.json ao lado).
"""

import json
from pathlib import Path
from typing import Any

Rota = dict[str, Any]


def no(pergunta: Any, *respostas: tuple[Any, Any]) -> Rota:
    return {
        "status": 200,
        "corpo": {
            "dados": {"pergunta": pergunta, "respostas": [{"id": i, "resposta": r} for i, r in respostas], "assuntoEncontrado": False}
        },
    }


def folha(id_assunto: Any, nome: str = "assunto inventado") -> Rota:
    return {"status": 200, "corpo": {"dados": {"assuntoEncontrado": True, "idAssunto": id_assunto, "nomeAssunto": nome}}}


def detalhe(nome: Any = "Detalhe inventado", **extra: Any) -> Rota:
    return {"status": 200, "corpo": {"dados": {"nome": nome, **extra}}}


def dados(valor: Any) -> Rota:
    return {"status": 200, "corpo": {"dados": valor}}


def item(i: Any) -> str:
    return f"/assunto/consultar-item-arvore?idItemCategoria={i}"


def cat(c: int) -> str:
    return f"/assunto/consultar-item-arvore?idCategoria={c}"


VD: dict[str, Rota] = {
    cat(10113): no("É COM VOCÊ?", (71, "Sim"), (72, "Não")),
    item(71): folha(701),
    item(72): no("ALGUÉM CORRE RISCO?", (73, "Sim"), (74, "Não")),
    item(73): folha(702),
    item(74): no("AVISO FINAL INVENTADO"),
    "/assunto/701": detalhe("Assunto VD 701", nomeMateria="Família", urgente=True, plantao=True),
    "/assunto/702": detalhe("Assunto VD 702", documentosNecessarios=[{"id": 9, "nomeDocumento": "Documento inventado", "basico": False}]),
}

A: dict[str, Rota] = {
    cat(9001): no("A SITUAÇÃO É URGENTE?", (11, "Sim"), (12, " não ")),
    item(11): no("QUAL O TIPO?", (21, "Cível"), (22, "Criminal"), (23, "Outro")),
    item(21): folha(501),
    item(22): no("AVISO: PROCURE O ÓRGÃO RESPONSÁVEL"),
    item(23): folha(502),
    item(12): no("SIM OU TALVEZ?", (31, "SIM"), (32, "TALVEZ")),
    item(31): folha(501),
    item(32): folha(503, "nome da árvore"),
    "/assunto/501": detalhe("Assunto 501", nomeMateria="Matéria", descricao="Descrição inventada", txDocumentosNecessarios="RG"),
    "/assunto/502": detalhe("Assunto 502"),
    "/assunto/503": detalhe(None),
}

B: dict[str, Rota] = {
    cat(9002): no("B?", (81, "x")),
    item(81): folha(501, "outro nome"),
}

PLANEJADOS = [
    {"id": "planejado-a", "nome": "categoria a", "descricao": "d", "idCategoriaAssuntoVerde": 9001, "palavrasChave": []},
    {"id": "planejado-b", "nome": "categoria b", "descricao": "d", "idCategoriaAssuntoVerde": 9002, "palavrasChave": []},
]

cenarios: list[dict[str, Any]] = []


def cenario(nome: str, mudancas: dict[str, Rota] | None = None, **extra: Any) -> None:
    rotas = {**VD, **A, **B, **(mudancas or {})}
    rotas = {k: v for k, v in rotas.items() if v is not None}
    cenarios.append({"nome": nome, "planejados": extra.pop("planejados", PLANEJADOS), "rotas": rotas, **extra})


# Caminhos principais
cenario("arvore completa nas tres categorias")
cenario("sem planejados", planejados=[])
cenario("assunto compartilhado com detalhe novo na segunda categoria", {"/assunto/501": detalhe("Assunto 501")})

# Falhas por categoria (a rodada segue)
cenario("HTTP 500 na raiz de b", {cat(9002): {"status": 500, "corpo": {}}})
cenario("HTTP 503 no meio de a", {item(12): {"status": 503, "corpo": {}}})
cenario("HTTP 404 no detalhe", {"/assunto/502": {"status": 404, "corpo": {"erro": "x"}}})
cenario("HTTP 302 na raiz de a", {cat(9001): {"status": 302, "corpo": {}}})
cenario("raiz da violencia domestica falha", {cat(10113): {"status": 500, "corpo": {}}})
cenario("rota inexistente no Verde (404 sem corpo JSON)", {cat(9002): {"status": 404, "bruto": "Not Found"}})

# `corpo.dados` e o corpo
valor: Any
for rotulo, valor in [("null", None), ("vazio", ""), ("zero", 0), ("false", False), ("lista vazia", []), ("objeto vazio", {})]:
    cenario(f"dados {rotulo} na raiz de a", {cat(9001): dados(valor)})
cenario("dados ausente", {cat(9001): {"status": 200, "corpo": {"outro": 1}}})
cenario("corpo null", {cat(9001): {"status": 200, "corpo": None}})
cenario("corpo lista", {cat(9001): {"status": 200, "corpo": [1, 2]}})
cenario("corpo texto JSON", {cat(9001): {"status": 200, "corpo": "dados"}})
cenario("dados texto", {cat(9001): dados("texto")})
cenario("detalhe com dados null", {"/assunto/502": dados(None)})
cenario("JSON invalido (D-4)", {cat(9001): {"status": 200, "bruto": "{nao e json"}})
cenario("corpo vazio com 200 (D-4)", {cat(9001): {"status": 200, "bruto": ""}})

# `assuntoEncontrado` e `idAssunto`
for rotulo, valor in [("texto false", "false"), ("texto zero", "0"), ("zero", 0), ("lista vazia", []), ("null", None)]:
    cenario(
        f"assuntoEncontrado {rotulo}", {item(22): dados({"assuntoEncontrado": valor, "idAssunto": 502, "pergunta": "P", "respostas": []})}
    )
cenario("idAssunto ausente", {item(21): dados({"assuntoEncontrado": True})})
cenario("idAssunto null", {item(21): folha(None), "/assunto/null": detalhe("Assunto null")})
cenario("idAssunto texto", {item(21): folha("501")})
cenario("idAssunto decimal", {item(21): folha(501.5), "/assunto/501.5": detalhe("Assunto decimal")})
cenario(
    "detalhe com campos null",
    {"/assunto/502": detalhe("Assunto 502", nomeMateria=None, descricao=None, documentosNecessarios=None, urgente=None, plantao=None)},
)
cenario(
    "detalhe sem nome e sem nomeAssunto",
    {item(23): dados({"assuntoEncontrado": True, "idAssunto": 502}), "/assunto/502": dados({"urgente": False})},
)
cenario("detalhe com nome vazio", {"/assunto/502": detalhe("")})

# `pergunta` e `respostas`
for rotulo, valor in [("vazia", ""), ("null", None), ("zero", 0), ("numero", 5), ("lista", ["x"])]:
    cenario(f"pergunta {rotulo}", {item(22): dados({"pergunta": valor, "respostas": []})})
for rotulo, valor in [("null", None), ("texto vazio", ""), ("texto", "abc"), ("objeto", {"id": 1}), ("zero", 0)]:
    cenario(f"respostas {rotulo}", {item(22): dados({"pergunta": "AVISO", "respostas": valor})})
cenario("resposta numerica", {item(22): dados({"pergunta": "P", "respostas": [{"id": 61, "resposta": 7}]})})
cenario("resposta sem texto", {item(22): dados({"pergunta": "P", "respostas": [{"id": 61}]})})
cenario("resposta null na lista", {item(22): dados({"pergunta": "P", "respostas": [None]})})
cenario("resposta sem id", {item(22): dados({"pergunta": "P", "respostas": [{"resposta": "x"}]}), item("undefined"): folha(502)})
cenario(
    "resposta com id null", {item(22): dados({"pergunta": "P", "respostas": [{"id": None, "resposta": "x"}]}), item("null"): folha(502)}
)
cenario("resposta com id texto com espaco", {item(22): dados({"pergunta": "P", "respostas": [{"id": "a b", "resposta": "x"}]})})

# sim/não
for rotulo, respostas in [
    ("minusculas com espaco", [" sim ", "não"]),
    ("ordem trocada", ["NÃO", "SIM"]),
    ("sem acento", ["SIM", "NAO"]),
    ("repetido", ["SIM", "SIM"]),
    ("com BOM", ["﻿SIM", "NÃO"]),
    ("com separador", ["\x1cSIM", "NÃO"]),
    ("tres opcoes", ["SIM", "NÃO", "TALVEZ"]),
    ("nao em NFD", ["SIM", "NÃO"]),
]:
    cenario(
        f"sim/nao {rotulo}",
        {item(22): no("P", *[(600 + i, r) for i, r in enumerate(respostas)]), **{item(600 + i): folha(502) for i in range(len(respostas))}},
    )

# Profundidade
cadeia = {item(22): no("NIVEL 2", (1001, "segue"))}
for nivel in range(3, 15):
    cadeia[item(1001 + nivel - 3)] = no(f"NIVEL {nivel}", (1001 + nivel - 2, "segue"))
cadeia[item(1001 + 12)] = folha(502)
cenario("profundidade 13 (passa do limite)", cadeia)
cadeia_ok = {item(22): no("NIVEL 2", (2001, "segue"))}
for nivel in range(3, 13):
    cadeia_ok[item(2001 + nivel - 3)] = no(f"NIVEL {nivel}", (2001 + nivel - 2, "segue"))
cadeia_ok[item(2001 + 10)] = folha(502)
cenario("profundidade 12 (no limite)", cadeia_ok)

# Rede e configuração
cenario("timeout na raiz de b (21 s)", {cat(9002): {"status": 200, "corpo": no("B?")["corpo"], "atraso": 21}})
cenario("porta fechada", api_url="porta_fechada")
cenario("VERDE_API_URL vazia", api_url="vazia")

Path(__file__).with_name("cenarios.json").write_text(
    json.dumps(cenarios, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
)
print(f"{len(cenarios)} cenários")
