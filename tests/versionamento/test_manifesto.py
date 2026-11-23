"""Manifesto dos fluxos (#542): o hash muda com o comportamento e ignora comentário, docstring e formatação."""

from pathlib import Path

from maria.versionamento.alteracoes import comparar_compartilhado, comparar_fluxo, contagem
from maria.versionamento.manifesto import montar_manifesto, raiz_instalada
from tests.versionamento.conftest import GRAFO, INIT, escrever

ID = "11111111-1111-1111-1111-111111111111"


def test_acha_o_fluxo_o_tipo_da_tykhe_e_o_compartilhado(raiz: Path) -> None:
    m = montar_manifesto(raiz)
    assert set(m["fluxos"]) == {ID, "tykhe:saude"}
    assert m["fluxos"][ID]["nome"] == "exemplo"
    assert m["fluxos"][ID]["snapshot"]["pasta"] == "exemplo"
    assert list(m["fluxos"][ID]["snapshot"]["arquivos"]) == ["fluxos/exemplo/graph.py"]
    assert list(m["compartilhado"]["snapshot"]["arquivos"]) == ["shared/util.py"]


def test_comentario_docstring_e_formatacao_nao_mudam_o_hash(raiz: Path) -> None:
    antes = montar_manifesto(raiz)["fluxos"][ID]["hash"]
    reformatado = GRAFO.replace("# comentário", "# outro comentário").replace("Docstring da função.", "Outra docstring.")
    reformatado = reformatado.replace('return "Qual o seu nome?"', 'return   "Qual o seu nome?"')
    escrever(raiz, "fluxos/exemplo/graph.py", reformatado)
    assert montar_manifesto(raiz)["fluxos"][ID]["hash"] == antes


def test_pergunta_nova_muda_o_hash_e_aparece_no_antes_e_depois(raiz: Path) -> None:
    antes = montar_manifesto(raiz)["fluxos"][ID]
    escrever(raiz, "fluxos/exemplo/graph.py", GRAFO.replace("Qual o seu nome?", "Qual o nome completo?"))
    depois = montar_manifesto(raiz)["fluxos"][ID]
    assert depois["hash"] != antes["hash"]
    alteracoes = comparar_fluxo(antes["snapshot"], depois["snapshot"])
    textos = next(a for a in alteracoes if a["item"].endswith("::textos"))
    assert textos["antes"] == ["Qual o seu nome?"] and textos["depois"] == ["Qual o nome completo?"]
    assert any(a["item"] == "fluxos/exemplo/graph.py::pergunta" for a in alteracoes)
    assert "1 trecho(s) de código" in contagem(alteracoes) and "2 texto(s)" in contagem(alteracoes)


def test_mudanca_no_grafo_aparece_como_chamada_trocada(raiz: Path) -> None:
    antes = montar_manifesto(raiz)["fluxos"][ID]
    escrever(raiz, "fluxos/exemplo/graph.py", GRAFO.replace('add_edge("pergunta", "fim")', 'add_edge("pergunta", "outra")'))
    depois = montar_manifesto(raiz)["fluxos"][ID]
    grafo = next(a for a in comparar_fluxo(antes["snapshot"], depois["snapshot"]) if a["item"].endswith("::grafo"))
    assert grafo["antes"] == ["construtor.add_edge('pergunta', 'fim')"]
    assert grafo["depois"] == ["construtor.add_edge('pergunta', 'outra')"]


def test_campo_da_config_muda_so_o_fluxo_dele(raiz: Path) -> None:
    antes = montar_manifesto(raiz)
    escrever(raiz, "fluxos/__init__.py", INIT.replace("em_teste=True", "em_teste=False"))
    depois = montar_manifesto(raiz)
    assert depois["fluxos"][ID]["hash"] != antes["fluxos"][ID]["hash"]
    assert depois["fluxos"]["tykhe:saude"]["hash"] == antes["fluxos"]["tykhe:saude"]["hash"]
    config = comparar_fluxo(antes["fluxos"][ID]["snapshot"], depois["fluxos"][ID]["snapshot"])
    assert config == [{"item": "config.em_teste", "antes": True, "depois": False}]


def test_tipo_da_tykhe_muda_pela_descricao(raiz: Path) -> None:
    antes = montar_manifesto(raiz)["fluxos"]["tykhe:saude"]
    escrever(raiz, "fluxos/tipos_tykhe.py", (raiz / "fluxos/tipos_tykhe.py").read_text().replace("Questões de saúde", "Saúde e plano"))
    depois = montar_manifesto(raiz)["fluxos"]["tykhe:saude"]
    assert [a["item"] for a in comparar_fluxo(antes["snapshot"], depois["snapshot"])] == ["config.descricao"]


def test_codigo_compartilhado_muda_so_o_compartilhado(raiz: Path) -> None:
    antes = montar_manifesto(raiz)
    escrever(raiz, "shared/util.py", "def util():\n    return 2\n")
    depois = montar_manifesto(raiz)
    assert depois["compartilhado"]["hash"] != antes["compartilhado"]["hash"]
    assert depois["fluxos"][ID]["hash"] == antes["fluxos"][ID]["hash"]
    assert [a["item"] for a in comparar_compartilhado(antes["compartilhado"]["snapshot"], depois["compartilhado"]["snapshot"])] == [
        "arquivo.shared/util.py"
    ]


def test_o_codigo_de_verdade_tem_os_fluxos_e_o_hash_e_estavel() -> None:
    m = montar_manifesto(raiz_instalada())
    assert {"3df874f2-675a-4c43-9ec7-480f7c702f50", "cabb2495-4e12-4f4a-9956-3d20649059bc", "84433c84-4776-4b05-a5a0-af8012d8eced"} <= set(
        m["fluxos"]
    )
    assert "tykhe:saude" in m["fluxos"] and "padrao" in m["fluxos"]
    assert all(e["snapshot"]["arquivos"] for i, e in m["fluxos"].items() if not i.startswith("tykhe:"))
    assert montar_manifesto(raiz_instalada()) == m
