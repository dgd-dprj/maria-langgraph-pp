"""O registro das versões no startup (#542) não pode atrasar nem derrubar a Maria."""

from typing import Any

import pytest

from maria import app
from maria.versionamento.manifesto import Manifesto


async def test_sem_banco_nao_faz_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    chamadas: list[Any] = []

    async def registrar(*args: Any) -> list[str]:
        chamadas.append(args)
        return []

    monkeypatch.setattr(app, "registrar_versoes", registrar)
    await app._registrar_versoes_dos_fluxos()
    assert chamadas == []


async def test_com_banco_registra_com_o_ambiente_e_a_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    monkeypatch.setattr(app, "carregar_meta", lambda: {"commit_sha": "abc"})
    chamadas: list[tuple[str, str, Manifesto, dict[str, Any]]] = []

    async def registrar(url: str, ambiente: str, manifesto: Manifesto, meta: dict[str, Any]) -> list[str]:
        chamadas.append((url, ambiente, manifesto, meta))
        return []

    monkeypatch.setattr(app, "registrar_versoes", registrar)
    await app._registrar_versoes_dos_fluxos()
    ((url, ambiente, manifesto, meta),) = chamadas
    assert (url, ambiente, meta) == ("postgresql://x", "release", {"commit_sha": "abc"})
    assert "3df874f2-675a-4c43-9ec7-480f7c702f50" in manifesto["fluxos"]


async def test_falha_ao_ler_os_fluxos_so_vai_para_o_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")

    def quebra() -> Manifesto:
        raise RuntimeError("arquivo ilegível")

    monkeypatch.setattr(app, "montar_manifesto", quebra)
    await app._registrar_versoes_dos_fluxos()  # não levanta
