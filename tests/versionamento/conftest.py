"""Mini árvore `maria/` para os testes do manifesto: um fluxo, um tipo da Tykhe e código compartilhado."""

from pathlib import Path

import pytest

INIT = """
from maria.fluxos.exemplo.graph import obter_grafo as obter_grafo_exemplo
from maria.fluxos.tipos_tykhe import TIPOS_TYKHE

ID_EXEMPLO = "11111111-1111-1111-1111-111111111111"

fluxos_por_id = {
    ID_EXEMPLO: FluxoConfig(
        nome="exemplo",
        descricao="Fluxo de exemplo",
        obter_grafo=obter_grafo_exemplo,
        mensagem_concluido="Pronto.",
        em_teste=True,
    ),
}
"""

GRAFO = '''
"""Docstring do módulo."""

def pergunta():
    """Docstring da função."""
    return "Qual o seu nome?"


def montar(construtor):
    # comentário
    construtor.add_node("pergunta", pergunta)
    construtor.add_edge("pergunta", "fim")
'''

TIPOS = """
TIPOS_TYKHE = (
    TipoTykhe(id="tykhe:saude", tipo_caso="saude", nome="saude", descricao="Questões de saúde", mensagem="Vou encaminhar."),
)
"""


def escrever(raiz: Path, arquivo: str, texto: str) -> None:
    caminho = raiz / arquivo
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")


@pytest.fixture
def raiz(tmp_path: Path) -> Path:
    escrever(tmp_path, "fluxos/__init__.py", INIT)
    escrever(tmp_path, "fluxos/exemplo/graph.py", GRAFO)
    escrever(tmp_path, "fluxos/tipos_tykhe.py", TIPOS)
    escrever(tmp_path, "shared/util.py", "def util():\n    return 1\n")
    return tmp_path
