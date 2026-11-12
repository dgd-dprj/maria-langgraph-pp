"""#457: o porquê de cada atendimento humano da pessoa presa no `atendimento_finalizado`, sem dado pessoal.

Campos novos do log (registrados em `CAMPOS_DE_LOG_POSTERIORES`, `tests/api/campos_posteriores.py`):
"statusFinal" (todos os fluxos), "processoLocalizado", "origemProcesso", "statusVerdeProcesso",
"criterioNaoAtendido", "criterioSemDado" e "digitosRg". O `status` de develop continua "concluido".
"""

from __future__ import annotations

import json
from itertools import count
from typing import Any

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA
from maria.fluxos.pessoa_presa.graph import campos_de_log_do_fim

BASE = "/atendimentos"
_ids = count(1)

APENADO_OK = {"encontrado": True, "situacao": "EM VPF", "tipoPreso": "CONDENADO", "regime": "SEMIABERTO"}


# ---- os campos, um motivo por vez --------------------------------------------------


def test_origem_de_processo_achado_traz_o_sistema_e_nao_o_numero() -> None:
    campos = campos_de_log_do_fim(
        {
            "motivoHandoff": "origem_processo_nao_suportada",
            "numeroProcesso": "0000088-95.2026.8.19.0010",
            "dadosProcesso": {"encontrado": True, "id": 123, "origem": "PJe"},
        }
    )
    assert campos == {"processoLocalizado": True, "origemProcesso": "PJe"}


def test_processo_nao_localizado_traz_o_status_do_verde() -> None:
    campos = campos_de_log_do_fim(
        {"motivoHandoff": "origem_processo_nao_suportada", "dadosProcesso": {"encontrado": False}, "statusConsultaProcesso": 422}
    )
    assert campos == {"processoLocalizado": False, "statusVerdeProcesso": 422}


def test_processo_sem_resposta_do_verde_so_diz_que_nao_localizou() -> None:
    assert campos_de_log_do_fim({"motivoHandoff": "origem_processo_nao_suportada"}) == {"processoLocalizado": False}


@pytest.mark.parametrize(
    ("apenado", "esperado"),
    [
        ({**APENADO_OK, "situacao": "EVADIDO"}, ("situacao", False)),
        ({**APENADO_OK, "tipoPreso": "PROVISÓRIO"}, ("tipoPreso", False)),
        ({**APENADO_OK, "regime": "ABERTO"}, ("regime", False)),
        # Na ordem do `concluir`: a situação é olhada antes do regime.
        ({**APENADO_OK, "situacao": "EVADIDO", "regime": "ABERTO"}, ("situacao", False)),
        # O Verde não mandou o campo, ou mandou nulo.
        ({"encontrado": True, "situacao": "ATIVO", "tipoPreso": "CONDENADO"}, ("regime", True)),
        ({**APENADO_OK, "tipoPreso": None}, ("tipoPreso", True)),
        (None, ("situacao", True)),
    ],
)
def test_criterio_que_barrou_sem_o_valor(apenado: Any, esperado: tuple[str, bool]) -> None:
    campos = campos_de_log_do_fim({"motivoHandoff": "dados_pessoa_nao_atendidos", "dadosApenado": apenado})
    assert campos == {"criterioNaoAtendido": esperado[0], "criterioSemDado": esperado[1]}
    assert not {"EVADIDO", "PROVISÓRIO", "ABERTO"} & {str(v) for v in campos.values()}


@pytest.mark.parametrize(("rg", "digitos"), [("123456789", 9), ("12.345.678-9", 9), ("12345678", 8), ("12345678901", 11)])
def test_rg_nao_encontrado_traz_so_quantos_digitos(rg: str, digitos: int) -> None:
    assert campos_de_log_do_fim({"motivoHandoff": "rg_nao_encontrado", "rg": rg}) == {"digitosRg": digitos}


@pytest.mark.parametrize("motivo", [None, "sem_numero_processo", "nome_nao_confirmado", "falha_infra_verde"])
def test_outros_desfechos_nao_ganham_campo(motivo: str | None) -> None:
    valores = {"motivoHandoff": motivo, "rg": "123456789", "dadosProcesso": {"encontrado": True, "origem": "PJe"}}
    assert campos_de_log_do_fim(valores) == {}


# ---- no log de verdade, pela API --------------------------------------------------


def _fim(saida: str) -> dict[str, Any]:
    [linha] = [json.loads(x) for x in saida.splitlines() if '"atendimento_finalizado"' in x]
    return dict(linha)


async def _pessoa_presa(cliente: httpx.AsyncClient, auth: dict[str, str], respostas: list[str]) -> dict[str, Any]:
    chat_id = f"teste-log-motivos-{next(_ids)}"
    corpo = (await cliente.post(BASE, json={"chatId": chat_id, "flowId": ID_PESSOA_PRESA}, headers=auth)).json()
    for resposta in respostas:
        corpo = (await cliente.post(f"{BASE}/respostas", json={"chatId": chat_id, "resposta": resposta}, headers=auth)).json()
    return dict(corpo)


async def test_rg_nao_encontrado_no_log_sem_o_rg(
    cliente: httpx.AsyncClient, auth: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    # Verde em mock: "000000000" não acha.
    capsys.readouterr()
    corpo = await _pessoa_presa(cliente, auth, ["false", "000000000", "true", "000000000", "true", "000000000"])
    assert corpo["status"] == "handoff_humano"
    saida = capsys.readouterr().out
    fim = _fim(saida)
    assert (fim["status"], fim["statusFinal"], fim["motivoHandoff"], fim["digitosRg"]) == (
        "concluido",
        "handoff_humano",
        "rg_nao_encontrado",
        9,
    )
    assert "000000000" not in json.dumps(fim)


async def test_origem_nao_suportada_no_log(cliente: httpx.AsyncClient, auth: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
    # Verde em mock: esse número é de outra origem ("e-Proc (mock)").
    capsys.readouterr()
    await _pessoa_presa(cliente, auth, ["true", "0000000-00.0000.0.00.0000", "11111111111", "true", "amigo"])
    fim = _fim(capsys.readouterr().out)
    assert (fim["statusFinal"], fim["motivoHandoff"]) == ("handoff_humano", "origem_processo_nao_suportada")
    assert (fim["processoLocalizado"], fim["origemProcesso"]) == (True, "e-Proc (mock)")
    assert "0000000-00.0000.0.00.0000" not in json.dumps(fim)


async def test_concluido_traz_so_o_status_final(
    cliente: httpx.AsyncClient, auth: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    corpo = await _pessoa_presa(cliente, auth, ["true", "0000088-95.2026.8.19.0010", "11111111111", "true", "amigo"])
    assert corpo["status"] == "concluido"
    fim = _fim(capsys.readouterr().out)
    assert fim["statusFinal"] == "concluido"
    assert not {"processoLocalizado", "origemProcesso", "criterioNaoAtendido", "digitosRg"} & set(fim)
