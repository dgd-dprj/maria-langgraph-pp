"""Ponto de entrada: o loop de eventos do servidor (#260)."""

import asyncio
from typing import Any

import pytest
import uvicorn
from uvicorn.config import Config

from maria import main as modulo_main


def test_windows_usa_o_selector_e_os_outros_sistemas_ficam_no_auto() -> None:
    assert modulo_main.loop_do_servidor("win32") == "asyncio:SelectorEventLoop"
    assert modulo_main.loop_do_servidor("linux") == "auto"


def test_a_fabrica_do_windows_e_aceita_pelo_uvicorn() -> None:
    # Um nome que o uvicorn não importa faria a subida sair com STARTUP_FAILURE.
    assert Config("maria.app:criar_app", loop="asyncio:SelectorEventLoop").get_loop_factory() is asyncio.SelectorEventLoop


def test_main_passa_o_loop_da_plataforma(monkeypatch: pytest.MonkeyPatch) -> None:
    chamada: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: chamada.update(k))
    monkeypatch.setattr(modulo_main, "load_dotenv", lambda: None)
    modulo_main.main()
    assert chamada["loop"] == modulo_main.loop_do_servidor()
    assert chamada["workers"] == 1
    assert chamada["port"] == 3001
