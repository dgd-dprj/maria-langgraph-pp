"""O fluxo do plano de saúde no orquestrador (#386, decisão da #266).

Na produção, nada muda: o catálogo de classificação e a descrição de `tykhe:saude` são
comparados, caractere por caractere, com a cópia gravada em 2026-11-05, antes da #386
(`tests/fixtures/orquestrador/catalogo-producao-2026-11-05.json`). Nunca edite essa cópia:
se a produção tiver de mudar, é outra decisão, com registro na #208.

No release, onde o fluxo em teste liga (#324), o plano de saúde entra no catálogo só para o que
envolve cirurgia com o plano (escopo confirmado em 2026-11-05); a descrição de `tykhe:saude`
mantém "plano de saúde que negou cobertura" e tira só a parte de cirurgia: as outras negativas do
plano continuam com a Tykhe. A escolha da IA de verdade (H1 a H6) fica no teste
de integração `tests/integracao/ia/test_classificacao_plano_saude.py`; aqui a classificação é
simulada e o que se prova é o caminho da rota.
"""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA, catalogo_para_classificacao
from maria.fluxos.tipos_tykhe import TIPOS_TYKHE, tipo_tykhe_por_id

BASE = "/atendimentos/orquestrador"
GRAVADO = Path("tests/fixtures/orquestrador/catalogo-producao-2026-11-05.json")
TEXTO_GRAVADO = GRAVADO.read_text(encoding="utf-8")
# Valores de MARIA_AMBIENTE que NÃO ligam o fluxo em teste (os mesmos de `test_fluxo_em_teste.py`).
NAO_LIGAM = [None, "", "producao", "Release", "RELEASE", "release ", " release", "homologacao"]
TRECHO_PLANO = "plano de saúde que negou cobertura, "
TROCA_RELEASE = "plano de saúde que negou cobertura de exame, remédio, tratamento, internação ou reembolso (menos cirurgia), "
# O CEP faz o fluxo do plano seguir para a 1ª pergunta, em vez de encerrar por não saber o município.
DADOS_NO_RIO = {"endereco": {"cep": "20000000"}}

_ids = count(1)


def _chat() -> str:
    return f"teste-orq-plano-{next(_ids)}"


def _gravado() -> list[dict[str, str]]:
    dados: list[dict[str, str]] = json.loads(TEXTO_GRAVADO)
    return dados


@pytest.fixture(autouse=True)
def _sem_planejados(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", raising=False)


def _ambiente(monkeypatch: pytest.MonkeyPatch, valor: str | None) -> None:
    if valor is None:
        monkeypatch.delenv("MARIA_AMBIENTE", raising=False)
    else:
        monkeypatch.setenv("MARIA_AMBIENTE", valor)


# ---- produção: igual à cópia gravada -------------------------------------------------


@pytest.mark.parametrize("valor", NAO_LIGAM, ids=repr)
async def test_producao_catalogo_igual_ao_gravado_em_2026_11_05(valor: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    _ambiente(monkeypatch, valor)
    catalogo = await catalogo_para_classificacao()
    # Comparação do texto serializado: pega ordem, chaves e cada caractere das descrições.
    assert json.dumps(catalogo, ensure_ascii=False, indent=2) + "\n" == TEXTO_GRAVADO


@pytest.mark.parametrize("valor", NAO_LIGAM, ids=repr)
async def test_producao_descricao_de_saude_igual_a_gravada(valor: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    _ambiente(monkeypatch, valor)
    gravada = next(o["descricao"] for o in _gravado() if o["id"] == "tykhe:saude")
    no_catalogo = next(o["descricao"] for o in await catalogo_para_classificacao() if o["id"] == "tykhe:saude")
    assert no_catalogo == gravada
    assert TRECHO_PLANO in gravada, "na produção, a negativa de plano continua com a Tykhe"


def test_a_copia_gravada_e_a_de_antes_da_386() -> None:
    # Se alguém regravar a cópia com o plano dentro, o teste de cima deixaria de proteger a produção.
    ids = [o["id"] for o in _gravado()]
    assert ids == [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, *(t.id for t in TIPOS_TYKHE)]


# ---- release: o plano entra só para cirurgia ------------------------------------------


async def test_release_catalogo_com_o_plano_so_para_cirurgia(monkeypatch: pytest.MonkeyPatch) -> None:
    _ambiente(monkeypatch, "release")
    catalogo = await catalogo_para_classificacao()
    gravado = _gravado()
    assert [o["id"] for o in catalogo] == [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, ID_PROBLEMAS_PLANO_SAUDE, *(t.id for t in TIPOS_TYKHE)]
    plano = catalogo[2]
    assert plano["nome"] == "problemas-plano-de-saude"
    assert "cirurgia" in plano["descricao"]
    # Por enquanto, só o que envolve cirurgia (2026-11-05): as outras negativas ficam com a Tykhe.
    for fora in ("exame", "tratamento", "remédio", "internação", "mensalidade", "cancel"):
        assert fora not in plano["descricao"].lower(), fora
    saude_release = next(o for o in catalogo if o["id"] == "tykhe:saude")
    saude_gravada = next(o for o in gravado if o["id"] == "tykhe:saude")
    assert saude_release["descricao"] == saude_gravada["descricao"].replace(TRECHO_PLANO, TROCA_RELEASE)
    # A frase do plano fica, e as outras negativas continuam com a Tykhe; sai só a cirurgia.
    assert "plano de saúde que negou cobertura" in saude_release["descricao"]
    for fica in ("exame", "remédio", "internação", "reembolso"):
        assert fica in TROCA_RELEASE, fica
    assert "(menos cirurgia)" in saude_release["descricao"]
    # O resto do catálogo é o mesmo da produção.
    assert [o for o in catalogo if o["id"] not in (ID_PROBLEMAS_PLANO_SAUDE, "tykhe:saude")] == [
        o for o in gravado if o["id"] != "tykhe:saude"
    ]


def test_trecho_do_plano_aparece_uma_vez_na_descricao_de_saude() -> None:
    # Sem isso, uma mudança de vírgula na descrição faria o `replace` não trocar nada, em silêncio.
    saude = tipo_tykhe_por_id("tykhe:saude")
    assert saude is not None and saude.trecho_de_fluxo_da_maria is not None
    assert saude.descricao.count(saude.trecho_de_fluxo_da_maria.trecho) == 1
    assert saude.trecho_de_fluxo_da_maria.troca == TROCA_RELEASE


# ---- rota (classificação simulada) -----------------------------------------------------


async def test_h1_release_o_relato_de_plano_vai_para_o_fluxo(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _ambiente(monkeypatch, "release")
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PROBLEMAS_PLANO_SAUDE)
    corpo = {"chatId": _chat(), "mensagem": "meu plano de saúde negou minha cirurgia", "dadosConhecidos": DADOS_NO_RIO}
    r = await cliente.post(BASE, json=corpo, headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "em_andamento"
    assert r.json()["flowId"] == ID_PROBLEMAS_PLANO_SAUDE


@pytest.mark.parametrize("valor", NAO_LIGAM, ids=repr)
async def test_producao_mesmo_que_a_ia_devolva_o_plano_ele_nao_e_escolhido(
    valor: str | None, cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # O id fora do catálogo não acha nada, e o caso volta para a Tykhe como hoje.
    _ambiente(monkeypatch, valor)
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_PROBLEMAS_PLANO_SAUDE)
    r = await cliente.post(BASE, json={"chatId": _chat(), "mensagem": "meu plano de saúde negou minha cirurgia"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "redirecionado"
    assert "flowId" not in r.json()


async def test_h3_release_saude_publica_continua_com_a_tykhe(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _ambiente(monkeypatch, "release")
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", "tykhe:saude")
    r = await cliente.post(BASE, json={"chatId": _chat(), "mensagem": "preciso de um remédio que o posto não tem"}, headers=auth)
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["tipoCaso"]) == ("redirecionado", "saude")


async def test_h4_release_relato_ambiguo_entre_plano_e_saude_segue_direto_no_fluxo_sem_perguntar(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # #419 (decisão do Ícaro, 2026-11-05): o par plano de saúde x tykhe:saude não gera pergunta de desambiguação.
    _ambiente(monkeypatch, "release")
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", f"{ID_PROBLEMAS_PLANO_SAUDE},tykhe:saude")
    corpo = {"chatId": _chat(), "mensagem": "preciso de uma cirurgia", "dadosConhecidos": DADOS_NO_RIO}
    r = await cliente.post(BASE, json=corpo, headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "em_andamento"
    assert r.json()["flowId"] == ID_PROBLEMAS_PLANO_SAUDE
    assert r.json()["tipoResposta"] == "sim_nao"  # a 1ª pergunta do fluxo: para quem é o atendimento (#430)
    assert r.json()["opcoes"] == ["Sim", "Não"]
    assert "para você" in r.json()["resposta"]
