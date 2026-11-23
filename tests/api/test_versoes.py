"""GET /versoes-dos-fluxos (#547): chave própria, rota desligada sem ela, só leitura, erros sem vazar exceção."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from maria.api import versoes
from maria.app import criar_app
from maria.versionamento import leitura

CHAVE_DO_VISOR = "chave-do-visor-dos-testes"
BASE = "/versoes-dos-fluxos"
VERSAO = {"id": 7, "fluxo": "f1", "nomeFluxo": "pessoa-presa", "ambiente": "producao", "hash": "h7", "resumo": "1 pergunta"}


@pytest.fixture
async def visor(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("VERSOES_API_KEY", CHAVE_DO_VISOR)
    app = criar_app(pre_aquecer=False)
    async with app.router.lifespan_context(app):
        transporte = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transporte, base_url="http://127.0.0.1:3001") as c:
            yield c


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    chamadas: list[tuple[Any, ...]] = []

    async def listar(url: str, fluxo: str | None, ambiente: str | None, limite: int) -> dict[str, Any]:
        chamadas.append(("listar", fluxo, ambiente, limite))
        return {"emVigor": [{"fluxo": "f1", "ambiente": "producao", "id": 7}], "versoes": [VERSAO]}

    async def buscar(url: str, id_: int) -> dict[str, Any] | None:
        chamadas.append(("buscar", id_))
        return {**VERSAO, "snapshot": {"x": 1}} if id_ == 7 else None

    monkeypatch.setattr(leitura, "listar", listar)
    monkeypatch.setattr(leitura, "buscar", buscar)
    return chamadas


def bearer(chave: str) -> dict[str, str]:
    return {"authorization": f"Bearer {chave}"}


async def test_sem_a_variavel_a_rota_nao_existe(cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    # `cliente` sobe sem VERSOES_API_KEY (ela não está no ambiente dos testes).
    assert not versoes.ligado()
    assert (await cliente.get(BASE, headers=auth)).status_code == 404
    assert (await cliente.get(f"{BASE}/7", headers=auth)).status_code == 404


async def test_a_chave_da_tykhe_nao_abre_a_leitura(visor: httpx.AsyncClient) -> None:
    r = await visor.get(BASE, headers=bearer(os.environ["API_KEY"]))
    assert r.status_code == 401
    assert (await visor.get(BASE)).status_code == 401


async def test_a_chave_do_visor_nao_abre_as_rotas_da_tykhe(visor: httpx.AsyncClient) -> None:
    assert (await visor.get("/fluxos", headers=bearer(CHAVE_DO_VISOR))).status_code == 401
    assert (await visor.post("/atendimentos", json={}, headers=bearer(CHAVE_DO_VISOR))).status_code == 401


async def test_lista_com_filtros_e_em_vigor(visor: httpx.AsyncClient, banco: list[tuple[Any, ...]]) -> None:
    r = await visor.get(f"{BASE}?fluxo=pessoa-presa&ambiente=producao&limite=5", headers=bearer(CHAVE_DO_VISOR))
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["versoes"] == [VERSAO]
    assert corpo["emVigor"][0]["id"] == 7
    assert "lidoEm" in corpo
    assert "snapshot" not in corpo["versoes"][0]
    assert banco == [("listar", "pessoa-presa", "producao", 5)]


async def test_lista_usa_o_limite_padrao(visor: httpx.AsyncClient, banco: list[tuple[Any, ...]]) -> None:
    assert (await visor.get(BASE, headers=bearer(CHAVE_DO_VISOR))).status_code == 200
    assert banco == [("listar", None, None, versoes.LIMITE_PADRAO)]


@pytest.mark.parametrize(
    "consulta", ["limite=0", "limite=101", "limite=abc", "limite=-1", "fluxo=a%20b", "ambiente=x;drop", "fluxo=a&fluxo=b"]
)
async def test_filtro_invalido_400_com_motivo(visor: httpx.AsyncClient, banco: list[tuple[Any, ...]], consulta: str) -> None:
    r = await visor.get(f"{BASE}?{consulta}", headers=bearer(CHAVE_DO_VISOR))
    assert r.status_code == 400
    assert "inválido" in r.json()["erro"]
    assert banco == []


async def test_detalhe_traz_o_snapshot(visor: httpx.AsyncClient, banco: list[tuple[Any, ...]]) -> None:
    r = await visor.get(f"{BASE}/7", headers=bearer(CHAVE_DO_VISOR))
    assert r.status_code == 200
    assert r.json()["snapshot"] == {"x": 1}


async def test_detalhe_inexistente_404_e_id_invalido_400(visor: httpx.AsyncClient, banco: list[tuple[Any, ...]]) -> None:
    assert (await visor.get(f"{BASE}/999", headers=bearer(CHAVE_DO_VISOR))).status_code == 404
    assert (await visor.get(f"{BASE}/abc", headers=bearer(CHAVE_DO_VISOR))).status_code == 400


async def test_so_leitura(visor: httpx.AsyncClient, banco: list[tuple[Any, ...]]) -> None:
    for metodo in ("POST", "PUT", "PATCH", "DELETE"):
        r = await visor.request(metodo, BASE, headers=bearer(CHAVE_DO_VISOR), json={})
        assert r.status_code == 404, metodo
    assert banco == []


async def test_banco_fora_503_sem_vazar_a_excecao(visor: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")

    async def quebra(*_: Any) -> Any:
        raise RuntimeError("senha=segredo host=interno")

    monkeypatch.setattr(leitura, "listar", quebra)
    monkeypatch.setattr(leitura, "buscar", quebra)
    for caminho in (BASE, f"{BASE}/7"):
        r = await visor.get(caminho, headers=bearer(CHAVE_DO_VISOR))
        assert r.status_code == 503
        assert r.json()["erro"] == versoes.MENSAGEM_503
        assert "segredo" not in r.text


async def test_sem_banco_configurado_503(visor: httpx.AsyncClient) -> None:
    assert (await visor.get(BASE, headers=bearer(CHAVE_DO_VISOR))).status_code == 503


def test_a_mesma_chave_da_tykhe_impede_a_subida(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERSOES_API_KEY", os.environ["API_KEY"])
    with pytest.raises(RuntimeError, match="diferente da API_KEY"):
        criar_app(pre_aquecer=False)


async def test_fora_do_docs_publico(visor: httpx.AsyncClient) -> None:
    r = await visor.get("/docs/json")
    assert BASE not in r.text
