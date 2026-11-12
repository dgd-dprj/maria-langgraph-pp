"""Sufixo de prompt só para modelo Qwen (#458): outro modelo recebe o prompt de sempre."""

from __future__ import annotations

from typing import Any

import pytest

from maria.ia import classificar_fluxos, classificar_necessidades, desambiguar
from maria.ia.ajuste_qwen import SUFIXO_DESAMBIGUAR, SUFIXO_FLUXOS, SUFIXO_NECESSIDADES, com_ajuste_qwen, modelo_e_qwen

QWEN = "qwen.qwen3-vl-235b-a22b"
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


@pytest.mark.parametrize(
    ("modelo_id", "esperado"),
    [(QWEN, True), (" Qwen.qwen3-vl-235b-a22b ", True), (HAIKU, False), ("anthropic.claude-3-haiku-20240307-v1:0", False), ("", False)],
)
def test_detecta_qwen_pelo_id(monkeypatch: pytest.MonkeyPatch, modelo_id: str, esperado: bool) -> None:
    monkeypatch.setenv("BEDROCK_MODEL_ID", modelo_id)
    assert modelo_e_qwen() is esperado


def test_sem_variavel_nao_e_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    assert modelo_e_qwen() is False
    assert com_ajuste_qwen("base", "+extra") == "base"


def test_so_o_qwen_recebe_o_sufixo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEDROCK_MODEL_ID", QWEN)
    assert com_ajuste_qwen("base", "+extra") == "base+extra"
    monkeypatch.setenv("BEDROCK_MODEL_ID", HAIKU)
    assert com_ajuste_qwen("base", "+extra") == "base"


def test_sufixos_nao_tem_chaves() -> None:
    # SISTEMA usa .format e o sufixo entra em f-string: chave aqui quebraria o prompt.
    for texto in (SUFIXO_NECESSIDADES, SUFIXO_FLUXOS, SUFIXO_DESAMBIGUAR):
        assert "{" not in texto
        assert "}" not in texto


async def _sistema_das_necessidades(monkeypatch: pytest.MonkeyPatch, modelo_id: str) -> str:
    capturado: dict[str, Any] = {}

    async def falso(_modelo: object, _esquema: object, sistema: str, _mensagem: str) -> dict[str, Any]:
        capturado["sistema"] = sistema
        return {"parsed": {"necessidades": []}, "raw": None}

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("BEDROCK_MODEL_ID", modelo_id)
    monkeypatch.setattr(classificar_necessidades, "invocar_estruturado", falso)
    monkeypatch.setattr(classificar_necessidades, "definir_tokens", lambda *_: None)
    await classificar_necessidades.classificar_necessidades("relato", [{"id": "a", "nome": "n", "descricao": "d"}])
    return str(capturado["sistema"])


async def test_necessidades_qwen_leva_o_sufixo_e_outro_modelo_fica_identico(monkeypatch: pytest.MonkeyPatch) -> None:
    base = classificar_necessidades.SISTEMA.format(descricoes='- id "a" (n): d')
    com_qwen = await _sistema_das_necessidades(monkeypatch, QWEN)
    com_haiku = await _sistema_das_necessidades(monkeypatch, HAIKU)
    assert com_haiku == base
    assert com_qwen == base + SUFIXO_NECESSIDADES


async def _sistema_dos_fluxos(monkeypatch: pytest.MonkeyPatch, modelo_id: str) -> str:
    capturado: dict[str, Any] = {}

    async def falso(_mensagem: str, sistema: str, _ids: list[str]) -> dict[str, Any]:
        capturado["sistema"] = sistema
        return {"ids": [], "viaIA": True}

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("BEDROCK_MODEL_ID", modelo_id)
    monkeypatch.setattr(classificar_fluxos, "classificar_multiplo_entre_opcoes", falso)
    await classificar_fluxos.classificar_fluxos_plausiveis("relato", [{"id": "a", "nome": "n", "descricao": "d"}])
    return str(capturado["sistema"])


async def test_fluxos_qwen_leva_o_sufixo_e_outro_modelo_fica_identico(monkeypatch: pytest.MonkeyPatch) -> None:
    com_haiku = await _sistema_dos_fluxos(monkeypatch, HAIKU)
    com_qwen = await _sistema_dos_fluxos(monkeypatch, QWEN)
    assert SUFIXO_FLUXOS not in com_haiku
    assert com_qwen == com_haiku + SUFIXO_FLUXOS


async def _sistema_da_desambiguacao(monkeypatch: pytest.MonkeyPatch, modelo_id: str) -> str:
    capturado: dict[str, Any] = {}

    async def falso(_modelo: object, _esquema: object, sistema: str, _mensagem: str) -> dict[str, Any]:
        capturado["sistema"] = sistema
        return {"parsed": {"pergunta": "?"}, "raw": None}

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("BEDROCK_MODEL_ID", modelo_id)
    monkeypatch.setattr(desambiguar, "invocar_estruturado", falso)
    monkeypatch.setattr(desambiguar, "definir_tokens", lambda *_: None)
    await desambiguar.gerar_pergunta_desambiguacao(
        "relato", [{"id": "a", "nome": "n", "descricao": "d"}, {"id": "b", "nome": "m", "descricao": "e"}]
    )
    return str(capturado["sistema"])


async def test_desambiguacao_qwen_cita_as_opcoes_e_outro_modelo_fica_identico_472(monkeypatch: pytest.MonkeyPatch) -> None:
    com_haiku = await _sistema_da_desambiguacao(monkeypatch, HAIKU)
    com_qwen = await _sistema_da_desambiguacao(monkeypatch, QWEN)
    assert SUFIXO_DESAMBIGUAR not in com_haiku
    assert com_qwen == com_haiku + SUFIXO_DESAMBIGUAR
