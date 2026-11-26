"""Manifesto dos fluxos: um hash e um snapshot por fluxo (#542).

A análise é **estática**: lê os arquivos `.py` e monta a árvore (`ast`), sem importar nada. Assim a CI compara a
`develop` com o PR sem instalar o código antigo, e o runtime lê o próprio pacote instalado.

O hash cobre o comportamento e ignora comentário, docstring e formatação: muda quando muda uma função, uma
mensagem ou pergunta (texto entre aspas), uma chamada do grafo (`add_node`, `add_edge`…) ou um campo da
configuração do fluxo (`FluxoConfig`). O snapshot guarda também o código-fonte de cada trecho, para mostrar
antes e depois. Nenhum dado pessoal entra: só código e textos fixos do repositório.

Quatro tipos de entrada:
- cada fluxo de `fluxos_por_id` (config + todos os `.py` da pasta dele);
- o fluxo padrão (`FLUXO_PADRAO`);
- cada tipo da Tykhe de `tipos_tykhe.py` (só a configuração), com id `tykhe:<tipoCaso>`;
- `compartilhado`: código que todos os fluxos usam (`shared`, `ia`, `subgrafos`, `integracoes`).
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

SUBPASTAS_COMPARTILHADAS = ("shared", "ia", "subgrafos", "integracoes")
CHAMADAS_DO_GRAFO = frozenset({"add_node", "add_edge", "add_conditional_edges", "add_sequence", "set_entry_point", "set_finish_point"})
LIMITE_FONTE = 4000

Manifesto = dict[str, Any]


def raiz_instalada() -> Path:
    """A pasta do pacote `maria` que está rodando."""
    import maria

    return Path(maria.__file__).resolve().parent


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _json(valor: object) -> str:
    return json.dumps(valor, sort_keys=True, ensure_ascii=False, default=str)


def _tirar_docstrings(arvore: ast.AST) -> None:
    for no in ast.walk(arvore):
        if isinstance(no, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            primeiro = no.body[0] if no.body else None
            if isinstance(primeiro, ast.Expr) and isinstance(primeiro.value, ast.Constant) and isinstance(primeiro.value.value, str):
                no.body = no.body[1:] or [ast.Pass()]


def _hash_do_no(no: ast.AST) -> str:
    copia = copy.deepcopy(no)
    wrapper = ast.Module(body=[copia], type_ignores=[]) if isinstance(copia, ast.stmt) else copia
    _tirar_docstrings(wrapper)
    return _hash(ast.dump(wrapper))[:16]


def _nome_do_trecho(no: ast.stmt) -> str:
    if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return no.name
    if isinstance(no, ast.Assign):
        nomes = [a.id for a in no.targets if isinstance(a, ast.Name)]
        if nomes:
            return ",".join(nomes)
    if isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name):
        return no.target.id
    return f"<{type(no).__name__}:{_hash_do_no(no)[:6]}>"


def analisar_arquivo(caminho: Path) -> dict[str, Any]:
    """Trechos de código (hash e fonte), textos entre aspas e chamadas do grafo de um arquivo."""
    fonte = caminho.read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    trechos: dict[str, dict[str, str]] = {}
    importacoes: list[str] = []
    for no in arvore.body:
        if isinstance(no, ast.Import | ast.ImportFrom):
            importacoes.append(ast.unparse(no))
            continue
        if isinstance(no, ast.Expr) and isinstance(no.value, ast.Constant) and isinstance(no.value.value, str):
            continue  # docstring do módulo
        nome = _nome_do_trecho(no)
        base, n = nome, 2
        while nome in trechos:
            nome, n = f"{base}#{n}", n + 1
        trechos[nome] = {"hash": _hash_do_no(no), "fonte": (ast.get_source_segment(fonte, no) or "")[:LIMITE_FONTE]}
    if importacoes:
        trechos["<importacoes>"] = {"hash": _hash("\n".join(sorted(importacoes)))[:16], "fonte": "\n".join(importacoes)[:LIMITE_FONTE]}

    sem_doc = copy.deepcopy(arvore)
    _tirar_docstrings(sem_doc)
    textos = sorted(
        (no.lineno, no.col_offset, no.value)
        for no in ast.walk(sem_doc)
        if isinstance(no, ast.Constant) and isinstance(no.value, str) and no.value.strip()
    )
    chamadas = sorted(
        (no.lineno, ast.unparse(no))
        for no in ast.walk(sem_doc)
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr in CHAMADAS_DO_GRAFO
    )
    return {"trechos": trechos, "textos": [t[2] for t in textos], "grafo": [c[1] for c in chamadas]}


def _valor(no: ast.expr) -> Any:
    try:
        valor = ast.literal_eval(no)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return ast.unparse(no)
    return json.loads(_json(valor))  # tuplas e conjuntos viram listas, tudo serializável


def _campos(chamada: ast.Call) -> dict[str, Any]:
    return {kw.arg: _valor(kw.value) for kw in chamada.keywords if kw.arg}


def _atribuicao(arvore: ast.Module, nome: str) -> ast.expr | None:
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(isinstance(a, ast.Name) and a.id == nome for a in no.targets):
            return no.value
        if isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name) and no.target.id == nome:
            return no.value
    return None


def _constantes(arvore: ast.Module) -> dict[str, str]:
    consts: dict[str, str] = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign) and isinstance(no.value, ast.Constant) and isinstance(no.value.value, str):
            for alvo in no.targets:
                if isinstance(alvo, ast.Name):
                    consts[alvo.id] = no.value.value
    return consts


def _modulos_importados(arvore: ast.Module) -> dict[str, str]:
    """`obter_grafo_pessoa_presa` → `maria.fluxos.pessoa_presa.graph`."""
    mapa: dict[str, str] = {}
    for no in arvore.body:
        if isinstance(no, ast.ImportFrom) and no.module:
            for alias in no.names:
                mapa[alias.asname or alias.name] = no.module
    return mapa


def _pasta_do_grafo(chamada: ast.Call, importados: dict[str, str]) -> str | None:
    for kw in chamada.keywords:
        if kw.arg == "obter_grafo" and isinstance(kw.value, ast.Name):
            partes = importados.get(kw.value.id, "").split(".")
            if len(partes) >= 3 and partes[:2] == ["maria", "fluxos"]:
                return partes[2]
    return None


def _arquivos_da_pasta(raiz: Path, pasta: str) -> dict[str, Any]:
    base = raiz / "fluxos" / pasta
    return {str(arq.relative_to(raiz)): analisar_arquivo(arq) for arq in sorted(base.rglob("*.py"))}


def _entrada(nome: str, pasta: str | None, config: dict[str, Any], arquivos: dict[str, Any]) -> dict[str, Any]:
    snapshot = {"nome": nome, "pasta": pasta, "config": config, "arquivos": arquivos}
    base = {"config": config, "arquivos": {arq: {t: v["hash"] for t, v in a["trechos"].items()} for arq, a in arquivos.items()}}
    return {"nome": nome, "hash": _hash(_json(base)), "snapshot": snapshot}


def _fluxos_do_codigo(raiz: Path) -> dict[str, Any]:
    arvore = ast.parse((raiz / "fluxos" / "__init__.py").read_text(encoding="utf-8"))
    consts, importados = _constantes(arvore), _modulos_importados(arvore)
    saida: dict[str, Any] = {}

    def _de(id_: str, chamada: ast.Call) -> None:
        config = _campos(chamada)
        pasta = _pasta_do_grafo(chamada, importados)
        arquivos = _arquivos_da_pasta(raiz, pasta) if pasta and (raiz / "fluxos" / pasta).is_dir() else {}
        saida[id_] = _entrada(str(config.get("nome", id_)), pasta, config, arquivos)

    tabela = _atribuicao(arvore, "fluxos_por_id")
    if isinstance(tabela, ast.Dict):
        for chave, valor in zip(tabela.keys, tabela.values, strict=True):
            if isinstance(chave, ast.Name) and isinstance(valor, ast.Call):
                _de(consts.get(chave.id, chave.id), valor)
    padrao = _atribuicao(arvore, "FLUXO_PADRAO")
    if isinstance(padrao, ast.Call):
        _de("padrao", padrao)
    return saida


def _tipos_tykhe(raiz: Path) -> dict[str, Any]:
    arquivo = raiz / "fluxos" / "tipos_tykhe.py"
    if not arquivo.is_file():
        return {}
    tabela = _atribuicao(ast.parse(arquivo.read_text(encoding="utf-8")), "TIPOS_TYKHE")
    saida: dict[str, Any] = {}
    if isinstance(tabela, ast.Tuple):
        for item in tabela.elts:
            if isinstance(item, ast.Call):
                config = _campos(item)
                id_ = str(config.get("id") or f"tykhe:{config.get('tipo_caso')}")
                saida[id_] = _entrada(str(config.get("nome", id_)), None, config, {})
    return saida


def _compartilhado(raiz: Path) -> dict[str, Any]:
    arquivos: dict[str, str] = {}
    for sub in SUBPASTAS_COMPARTILHADAS:
        for arq in sorted((raiz / sub).rglob("*.py")) if (raiz / sub).is_dir() else []:
            analise = analisar_arquivo(arq)
            arquivos[str(arq.relative_to(raiz))] = _hash(_json({t: v["hash"] for t, v in analise["trechos"].items()}))[:16]
    return {"hash": _hash(_json(arquivos)), "snapshot": {"arquivos": arquivos}}


def montar_manifesto(raiz: Path | None = None) -> Manifesto:
    raiz = raiz or raiz_instalada()
    return {"fluxos": {**_fluxos_do_codigo(raiz), **_tipos_tykhe(raiz)}, "compartilhado": _compartilhado(raiz)}
