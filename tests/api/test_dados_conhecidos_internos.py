"""#240: campo interno dos fluxos em `dadosConhecidos` é descartado, e o nome vai para o log (decisão da Nicole,
2026-11-17: barrar os campos internos; os dados da pessoa continuam passando)."""

from __future__ import annotations

import json
from itertools import count
from typing import Any

import httpx
import pytest

from maria.api.dados_conhecidos import eh_interno, sem_campos_internos
from maria.fluxos import ID_VIOLENCIA_DOMESTICA

_ids = count(1)


class _LogFalso:
    def __init__(self) -> None:
        self.avisos: list[dict[str, Any]] = []

    def warn(self, mensagem: str, **campos: Any) -> None:
        self.avisos.append({"msg": mensagem, **campos})


# ---- o filtro --------------------------------------------------------------------


@pytest.mark.parametrize(
    "campo",
    [
        "encaminhamentoId",
        "statusFinal",
        "motivoHandoff",
        "mensagemFinal",
        "tokensGastos",
        "tentativasCpf",
        "recusasRgFormato",
        "dadosPessoa",
        "perguntaAtualTexto",
    ],
)
def test_campo_interno_e_descartado(campo: str) -> None:
    assert eh_interno(campo)


@pytest.mark.parametrize("campo", ["cpf", "nome", "idPessoa", "email", "telefone", "endereco", "dataNascimento", "parentesco"])
def test_dado_da_pessoa_passa(campo: str) -> None:
    assert not eh_interno(campo)


def test_log_traz_so_os_nomes_e_nunca_os_valores() -> None:
    log = _LogFalso()
    saida = sem_campos_internos({"cpf": "52998224725", "encaminhamentoId": 424242, "statusFinal": "concluido"}, log, "atendimentos")
    assert saida == {"cpf": "52998224725"}
    [aviso] = log.avisos
    assert (aviso["evento"], aviso["campos"], aviso["origem"]) == (
        "dados_conhecidos_descartados",
        ["encaminhamentoId", "statusFinal"],
        "atendimentos",
    )
    assert "424242" not in json.dumps(aviso) and "52998224725" not in json.dumps(aviso)


def test_sem_campo_interno_nao_ha_aviso_e_o_resto_volta_igual() -> None:
    log = _LogFalso()
    assert sem_campos_internos({"cpf": "1"}, log, "atendimentos") == {"cpf": "1"}
    assert sem_campos_internos(None, log, "atendimentos") is None
    assert log.avisos == []


# ---- pela API (Verde em mock) ---------------------------------------------------------


async def _vd_ate_o_fim(cliente: httpx.AsyncClient, auth: dict[str, str], extra: dict[str, Any]) -> dict[str, Any]:
    chat_id = f"teste-240-{next(_ids)}"
    dados = {"cpf": "11111111111", **extra}
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_VIOLENCIA_DOMESTICA, "dadosConhecidos": dados}, headers=auth)
    for resposta in ("true", "false"):
        await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": resposta}, headers=auth)
    return dict((await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": "true"}, headers=auth)).json())


async def test_encaminhamento_id_pre_preenchido_nao_vira_protocolo_falso(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O caso da issue: o encaminhamento falha, e antes a pessoa recebia "Protocolo: 424242"."""
    monkeypatch.setenv("MOCK_ENCAMINHAMENTO_FALHA", "true")
    capsys.readouterr()
    corpo = await _vd_ate_o_fim(cliente, auth, {"encaminhamentoId": 424242})
    assert (corpo["status"], corpo["metadados"]["motivoHandoff"]) == ("handoff_humano", "falha_encaminhamento")
    assert "424242" not in corpo["resposta"]
    [aviso] = [json.loads(x) for x in capsys.readouterr().out.splitlines() if '"dados_conhecidos_descartados"' in x]
    assert aviso["campos"] == ["encaminhamentoId"]
    assert "424242" not in json.dumps(aviso)


async def test_contador_pre_preenchido_nao_muda_o_fluxo(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Com `tentativasCpf` de fora, o fluxo seguia outro caminho; agora termina como sem o campo."""
    monkeypatch.setenv("MOCK_ENCAMINHAMENTO_FALHA", "true")
    com, sem = await _vd_ate_o_fim(cliente, auth, {"tentativasCpf": 99}), await _vd_ate_o_fim(cliente, auth, {})
    assert (com["status"], com["metadados"].get("motivoHandoff")) == (sem["status"], sem["metadados"].get("motivoHandoff"))


async def test_orquestrador_descarta_campo_interno(
    cliente: httpx.AsyncClient, auth: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    corpo = {
        "chatId": f"teste-240-orq-{next(_ids)}",
        "mensagem": "meu filho foi preso",
        "dadosConhecidos": {"cpf": "11111111111", "statusFinal": "concluido"},
    }
    r = await cliente.post("/atendimentos/orquestrador", json=corpo, headers=auth)
    assert r.status_code == 200
    avisos = [json.loads(x) for x in capsys.readouterr().out.splitlines() if '"dados_conhecidos_descartados"' in x]
    assert [(a["campos"], a["origem"]) for a in avisos] == [(["statusFinal"], "orquestrador")]
