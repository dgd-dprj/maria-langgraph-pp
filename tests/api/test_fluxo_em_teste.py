"""Fluxo em teste (#324): ligado só onde `MARIA_AMBIENTE` é exatamente "release".

O fluxo do plano de saúde (NUDECON, #329) é o primeiro fluxo em teste de verdade (decisão de
2026-11-03): na produção ele some de `GET /fluxos`, e `POST /atendimentos` com o id dele responde
como a um id desconhecido, para o contrato com a Tykhe não mudar. Os testes de mecânica usam
também um fluxo em teste de mentira, o grafo de pessoa presa registrado com outro id e
`em_teste=True`, que só existe aqui: o roteiro dele é curto e conhecido. Desligado, um fluxo em
teste some de `GET /fluxos` e do catálogo do orquestrador; a conversa que já começou nele termina
normalmente.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from maria.app import criar_app
from maria.fluxos import (
    ID_PESSOA_PRESA,
    ID_PROBLEMAS_PLANO_SAUDE,
    ID_VIOLENCIA_DOMESTICA,
    buscar_fluxo,
    catalogo_para_classificacao,
    fluxos_por_id,
)
from tests.api.casos_aposentados import AMBIENTE_DAS_CONFERENCIAS

ID_EM_TESTE = "7b1e2c3d-4f5a-4b6c-8d7e-9f0a1b2c3d4e"
ID_DESCONHECIDO = "0f9e8d7c-6b5a-4c3d-9e2f-1a0b9c8d7e6f"
EM_TESTE = replace(fluxos_por_id[ID_PESSOA_PRESA], nome="fluxo-em-teste", descricao="Fluxo em teste dos testes da #324.", em_teste=True)
# Valores que NÃO ligam: ausente (None), vazio, produção e os quase iguais.
NAO_LIGAM = [None, "", "producao", "Release", "RELEASE", "release ", " release", "homologacao"]
TERRAFORM = Path("infra/terraform")
# A resposta de hoje a um flowId desconhecido (`api/atendimentos.py`, `_post_atendimentos`).
RESPOSTA_ID_DESCONHECIDO = (404, '{"erro":"fluxo não encontrado — ver GET /fluxos"}'.encode())


@pytest.fixture(autouse=True)
def registrado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(fluxos_por_id, ID_EM_TESTE, EM_TESTE)


def _ambiente(monkeypatch: pytest.MonkeyPatch, valor: str | None) -> None:
    if valor is None:
        monkeypatch.delenv("MARIA_AMBIENTE", raising=False)
    else:
        monkeypatch.setenv("MARIA_AMBIENTE", valor)


async def _criar(cliente: httpx.AsyncClient, auth: dict[str, str], fluxo_id: str, chat_id: str) -> httpx.Response:
    return await cliente.post("/atendimentos", headers=auth, json={"chatId": chat_id, "flowId": fluxo_id})


async def test_no_release_o_fluxo_em_teste_aparece_e_funciona(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _ambiente(monkeypatch, "release")
    fluxos = (await cliente.get("/fluxos", headers=auth)).json()
    assert [f["id"] for f in fluxos] == [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, ID_PROBLEMAS_PLANO_SAUDE, ID_EM_TESTE]
    assert ID_EM_TESTE in [o["id"] for o in await catalogo_para_classificacao()]
    r = await _criar(cliente, auth, ID_EM_TESTE, "chat-em-teste-release")
    assert r.status_code == 200
    assert r.json()["status"] == "em_andamento"


async def test_no_release_o_plano_de_saude_aparece_e_atende(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _ambiente(monkeypatch, "release")
    fluxos = (await cliente.get("/fluxos", headers=auth)).json()
    assert {"id": ID_PROBLEMAS_PLANO_SAUDE, "nome": "problemas-plano-de-saude"} in fluxos
    r = await cliente.post(
        "/atendimentos",
        headers=auth,
        json={"chatId": "chat-plano-release", "flowId": ID_PROBLEMAS_PLANO_SAUDE, "dadosConhecidos": {"endereco": {"cep": "20000000"}}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "em_andamento"
    # No release, o orquestrador também o oferece (#386).
    assert ID_PROBLEMAS_PLANO_SAUDE in [o["id"] for o in await catalogo_para_classificacao()]


@pytest.mark.parametrize("valor", NAO_LIGAM, ids=repr)
async def test_fora_do_release_o_fluxo_em_teste_some(
    valor: str | None, cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _ambiente(monkeypatch, valor)
    fluxos = (await cliente.get("/fluxos", headers=auth)).json()
    # A lista da produção de hoje (main), igual às gravações da versão TypeScript.
    assert fluxos == [{"id": ID_PESSOA_PRESA, "nome": "pessoa-presa"}, {"id": ID_VIOLENCIA_DOMESTICA, "nome": "violencia-domestica"}]
    assert ID_EM_TESTE not in [o["id"] for o in await catalogo_para_classificacao()]
    em_teste = await _criar(cliente, auth, ID_EM_TESTE, "chat-em-teste-desligado")
    plano = await _criar(cliente, auth, ID_PROBLEMAS_PLANO_SAUDE, "chat-plano-desligado")
    desconhecido = await _criar(cliente, auth, ID_DESCONHECIDO, "chat-id-desconhecido")
    assert (
        (em_teste.status_code, em_teste.content)
        == (plano.status_code, plano.content)
        == (desconhecido.status_code, desconhecido.content)
        == RESPOSTA_ID_DESCONHECIDO
    )
    assert em_teste.headers.get("content-type") == plano.headers.get("content-type") == desconhecido.headers.get("content-type")


async def test_o_plano_de_saude_desligado_responde_como_id_desconhecido_tambem_com_dados(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Desligado, o fluxo não chega a rodar: nem a busca do município pelo CEP (#331) acontece.
    _ambiente(monkeypatch, None)
    corpo = {"chatId": "chat-plano-com-dados", "dadosConhecidos": {"endereco": {"cep": "20000000"}}}
    plano = await cliente.post("/atendimentos", headers=auth, json={**corpo, "flowId": ID_PROBLEMAS_PLANO_SAUDE})
    corpo_desconhecido = {**corpo, "chatId": "chat-desc-com-dados", "flowId": ID_DESCONHECIDO}
    desconhecido = await cliente.post("/atendimentos", headers=auth, json=corpo_desconhecido)
    assert (plano.status_code, plano.content) == (desconhecido.status_code, desconhecido.content) == RESPOSTA_ID_DESCONHECIDO
    assert (await cliente.get("/atendimentos/chat-plano-com-dados", headers=auth)).status_code == 404


async def test_a_conversa_em_andamento_termina_depois_do_desligamento(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _ambiente(monkeypatch, "release")
    criado = await _criar(cliente, auth, ID_EM_TESTE, "chat-em-andamento")
    assert criado.json()["status"] == "em_andamento"

    _ambiente(monkeypatch, "producao")
    consulta = await cliente.get("/atendimentos/chat-em-andamento", headers=auth)
    assert consulta.status_code == 200
    # Pessoa presa: sem processo, RG do mock encontrado, nome confirmado, parentesco.
    corpo: dict[str, object] = {}
    for resposta in ("false", "123456789", "true", "mãe"):
        r = await cliente.post("/atendimentos/respostas", headers=auth, json={"chatId": "chat-em-andamento", "resposta": resposta})
        assert r.status_code == 200, r.text
        corpo = r.json()
    assert corpo["status"] == "handoff_humano"
    assert corpo["flowId"] == ID_EM_TESTE

    nova = await _criar(cliente, auth, ID_EM_TESTE, "chat-novo-depois")
    assert nova.status_code == 404


async def test_so_o_plano_de_saude_esta_em_teste(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    em_teste = {fluxos_por_id[id_].nome for id_ in fluxos_por_id if id_ != ID_EM_TESTE and fluxos_por_id[id_].em_teste}
    assert em_teste == {"problemas-plano-de-saude"}
    for valor in (None, "producao", "release"):
        _ambiente(monkeypatch, valor)
        ids = [f["id"] for f in (await cliente.get("/fluxos", headers=auth)).json()]
        assert ids[:2] == [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA]


async def test_buscar_fluxo_sem_a_variavel(monkeypatch: pytest.MonkeyPatch) -> None:
    # O padrão sem variável é desligado; a conversa em andamento ainda resolve o fluxo.
    _ambiente(monkeypatch, None)
    assert await buscar_fluxo(ID_PROBLEMAS_PLANO_SAUDE) is None
    assert await buscar_fluxo(ID_PROBLEMAS_PLANO_SAUDE, conversa_em_andamento=True) is fluxos_por_id[ID_PROBLEMAS_PLANO_SAUDE]
    assert (await buscar_fluxo(ID_PESSOA_PRESA)) is fluxos_por_id[ID_PESSOA_PRESA]


@pytest.mark.parametrize(
    ("valor", "ligados", "desligados"),
    [
        (None, ["pessoa-presa", "violencia-domestica"], ["problemas-plano-de-saude", "fluxo-em-teste"]),
        ("producao", ["pessoa-presa", "violencia-domestica"], ["problemas-plano-de-saude", "fluxo-em-teste"]),
        ("release", ["pessoa-presa", "violencia-domestica", "problemas-plano-de-saude", "fluxo-em-teste"], []),
    ],
)
async def test_a_subida_registra_o_ambiente_e_os_fluxos_ligados(
    valor: str | None, ligados: list[str], desligados: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _ambiente(monkeypatch, valor)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = criar_app(pre_aquecer=False)
    capsys.readouterr()
    async with app.router.lifespan_context(app):
        pass
    linhas = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    subida = [x for x in linhas if x.get("evento") == "fluxos_ligados"]
    assert len(subida) == 1
    assert (subida[0]["ambiente"], subida[0]["fluxosLigados"], subida[0]["fluxosEmTesteDesligados"]) == (
        valor or "(ausente)",
        ligados,
        desligados,
    )


def _ambiente_no_terraform(arquivo: str) -> list[str]:
    texto = (TERRAFORM / arquivo).read_text(encoding="utf-8")
    return re.findall(r'\{\s*name\s*=\s*"MARIA_AMBIENTE"\s*,\s*value\s*=\s*"([^"]*)"\s*\}', texto)


def test_o_terraform_declara_producao_em_producao() -> None:
    """Um PR que troque o valor de produção falha aqui antes de entrar."""
    assert _ambiente_no_terraform("ecs.tf") == ["producao"]


def test_o_terraform_declara_release_no_release() -> None:
    assert _ambiente_no_terraform("release.tf") == ["release"]


def test_as_conferencias_rodam_com_o_ambiente_da_producao() -> None:
    """As gravações são o contrato da produção: as conferências usam o valor do `ecs.tf`."""
    assert [AMBIENTE_DAS_CONFERENCIAS] == _ambiente_no_terraform("ecs.tf")
