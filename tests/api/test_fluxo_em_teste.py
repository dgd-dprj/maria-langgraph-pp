"""Fluxo em teste (#324): ligado só onde `MARIA_AMBIENTE` é exatamente "release".

O fluxo em teste destes testes é o grafo de pessoa presa registrado com outro
id e `em_teste=True`; ele só existe aqui. Desligado, ele some de `GET /fluxos`
e do catálogo do orquestrador, e `POST /atendimentos` responde como a um id
desconhecido. A conversa que já começou nele termina normalmente.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from maria.app import criar_app
from maria.fluxos import ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, catalogo_para_classificacao, fluxos_por_id

ID_EM_TESTE = "7b1e2c3d-4f5a-4b6c-8d7e-9f0a1b2c3d4e"
ID_DESCONHECIDO = "0f9e8d7c-6b5a-4c3d-9e2f-1a0b9c8d7e6f"
EM_TESTE = replace(fluxos_por_id[ID_PESSOA_PRESA], nome="fluxo-em-teste", descricao="Fluxo em teste dos testes da #324.", em_teste=True)
# Valores que NÃO ligam: ausente (None), vazio, produção e os quase iguais.
NAO_LIGAM = [None, "", "producao", "Release", "RELEASE", "release ", " release", "homologacao"]
TERRAFORM = Path("infra/terraform")


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
    assert [f["id"] for f in fluxos] == [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, ID_EM_TESTE]
    assert ID_EM_TESTE in [o["id"] for o in await catalogo_para_classificacao()]
    r = await _criar(cliente, auth, ID_EM_TESTE, "chat-em-teste-release")
    assert r.status_code == 200
    assert r.json()["status"] == "em_andamento"


@pytest.mark.parametrize("valor", NAO_LIGAM, ids=repr)
async def test_fora_do_release_o_fluxo_em_teste_some(
    valor: str | None, cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _ambiente(monkeypatch, valor)
    fluxos = (await cliente.get("/fluxos", headers=auth)).json()
    assert [f["id"] for f in fluxos] == [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA]
    assert ID_EM_TESTE not in [o["id"] for o in await catalogo_para_classificacao()]
    em_teste = await _criar(cliente, auth, ID_EM_TESTE, "chat-em-teste-desligado")
    desconhecido = await _criar(cliente, auth, ID_DESCONHECIDO, "chat-id-desconhecido")
    assert (
        (em_teste.status_code, em_teste.content)
        == (desconhecido.status_code, desconhecido.content)
        == (
            404,
            '{"erro":"fluxo não encontrado — ver GET /fluxos"}'.encode(),
        )
    )


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


async def test_os_fluxos_de_hoje_continuam_ligados_em_todo_ambiente(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not any(cfg.em_teste for id_, cfg in fluxos_por_id.items() if id_ != ID_EM_TESTE)
    for valor in (None, "producao", "release"):
        _ambiente(monkeypatch, valor)
        ids = [f["id"] for f in (await cliente.get("/fluxos", headers=auth)).json()]
        assert ids[:2] == [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA]


@pytest.mark.parametrize(
    ("valor", "ligados", "desligados"),
    [
        (None, ["pessoa-presa", "violencia-domestica"], ["fluxo-em-teste"]),
        ("release", ["pessoa-presa", "violencia-domestica", "fluxo-em-teste"], []),
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
