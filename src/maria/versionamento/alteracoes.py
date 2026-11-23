"""O que mudou entre dois snapshots de um fluxo (#542): item, valor antes e valor depois.

Cada alteração é um dicionário `{"item", "antes", "depois"}`. Os itens são:
- `config.<campo>`: campo da configuração do fluxo (descrição, mensagens, `em_teste`…);
- `<arquivo>::<trecho>`: função, classe ou constante que mudou (antes e depois são o código-fonte);
- `<arquivo>::textos`: textos entre aspas (perguntas, mensagens, prompts) que saíram e que entraram;
- `<arquivo>::grafo`: chamadas do grafo (`add_node`, `add_edge`…) que saíram e que entraram;
- `arquivo.<nome>`: arquivo novo ou removido.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

LIMITE = 1500

Alteracao = dict[str, Any]


def _corta(texto: object) -> object:
    return texto[:LIMITE] + "…" if isinstance(texto, str) and len(texto) > LIMITE else texto


def _diferenca(antes: list[str], depois: list[str]) -> tuple[list[str], list[str]]:
    """Textos que saíram e que entraram, sem se importar com a ordem (multiconjunto)."""
    saiu = Counter(antes) - Counter(depois)
    entrou = Counter(depois) - Counter(antes)
    return list(saiu.elements()), list(entrou.elements())


def comparar_fluxo(antes: dict[str, Any] | None, depois: dict[str, Any]) -> list[Alteracao]:
    if antes is None:
        return [{"item": "fluxo", "antes": None, "depois": "primeira versão registrada neste ambiente"}]
    saida: list[Alteracao] = []
    cfg_a, cfg_d = antes.get("config", {}), depois.get("config", {})
    for campo in sorted(set(cfg_a) | set(cfg_d)):
        if cfg_a.get(campo) != cfg_d.get(campo):
            saida.append({"item": f"config.{campo}", "antes": _corta(cfg_a.get(campo)), "depois": _corta(cfg_d.get(campo))})
    arq_a, arq_d = antes.get("arquivos", {}), depois.get("arquivos", {})
    for arq in sorted(set(arq_a) | set(arq_d)):
        if arq not in arq_a:
            saida.append({"item": f"arquivo.{arq}", "antes": None, "depois": "arquivo novo"})
            continue
        if arq not in arq_d:
            saida.append({"item": f"arquivo.{arq}", "antes": "arquivo removido", "depois": None})
            continue
        tr_a, tr_d = arq_a[arq]["trechos"], arq_d[arq]["trechos"]
        for trecho in sorted(set(tr_a) | set(tr_d)):
            if tr_a.get(trecho, {}).get("hash") != tr_d.get(trecho, {}).get("hash"):
                saida.append(
                    {
                        "item": f"{arq}::{trecho}",
                        "antes": _corta(tr_a.get(trecho, {}).get("fonte")),
                        "depois": _corta(tr_d.get(trecho, {}).get("fonte")),
                    }
                )
        saiu, entrou = _diferenca(arq_a[arq]["textos"], arq_d[arq]["textos"])
        if saiu or entrou:
            saida.append({"item": f"{arq}::textos", "antes": [_corta(t) for t in saiu], "depois": [_corta(t) for t in entrou]})
        saiu, entrou = _diferenca(arq_a[arq]["grafo"], arq_d[arq]["grafo"])
        if saiu or entrou:
            saida.append({"item": f"{arq}::grafo", "antes": saiu, "depois": entrou})
    return saida


def comparar_compartilhado(antes: dict[str, Any] | None, depois: dict[str, Any]) -> list[Alteracao]:
    if antes is None:
        return [{"item": "compartilhado", "antes": None, "depois": "primeira versão registrada neste ambiente"}]
    arq_a, arq_d = antes.get("arquivos", {}), depois.get("arquivos", {})
    return [
        {"item": f"arquivo.{arq}", "antes": arq_a.get(arq), "depois": arq_d.get(arq)}
        for arq in sorted(set(arq_a) | set(arq_d))
        if arq_a.get(arq) != arq_d.get(arq)
    ]


def contagem(alteracoes: list[Alteracao]) -> str:
    """Resumo automático e sem IA: quantas mudanças de cada tipo."""
    if not alteracoes:
        return "sem alteração"
    if alteracoes[0]["item"] in ("fluxo", "compartilhado"):
        return str(alteracoes[0]["depois"])
    config = [a["item"].removeprefix("config.") for a in alteracoes if a["item"].startswith("config.")]
    textos = sum(len(a["depois"]) + len(a["antes"]) for a in alteracoes if a["item"].endswith("::textos"))
    grafo = sum(1 for a in alteracoes if a["item"].endswith("::grafo"))
    arquivos = sum(1 for a in alteracoes if a["item"].startswith("arquivo."))
    trechos = sum(1 for a in alteracoes if "::" in a["item"] and not a["item"].endswith(("::textos", "::grafo")))
    partes: list[str] = []
    if trechos:
        partes.append(f"{trechos} trecho(s) de código")
    if textos:
        partes.append(f"{textos} texto(s) entre aspas")
    if grafo:
        partes.append(f"{grafo} mudança(s) no grafo")
    if arquivos:
        partes.append(f"{arquivos} arquivo(s) novo(s) ou removido(s)")
    if config:
        partes.append("configuração: " + ", ".join(config))
    return "; ".join(partes)
