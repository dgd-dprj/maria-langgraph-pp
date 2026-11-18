"""#296: `dadosConhecidos.cpf` numérico vira texto de 11 dígitos; outro tipo é 400 com motivo."""

from typing import Any

import httpx
import pytest


# #296: `dadosConhecidos.cpf` numérico.
@pytest.mark.parametrize("cpf", [True, 1.5, ["12345678901"], {"n": 1}, -5, 100_000_000_000])
async def test_cpf_conhecido_de_outro_tipo_400_com_motivo(cliente: httpx.AsyncClient, auth: dict[str, str], cpf: Any) -> None:
    corpo = {"mensagem": "Preciso de ajuda", "chatId": "teste-296-invalido", "dadosConhecidos": {"cpf": cpf}}
    r = await cliente.post("/atendimentos/orquestrador", json=corpo, headers=auth)
    assert r.status_code == 400
    assert "dadosConhecidos.cpf deve ser texto" in r.json()["erro"]
    assert str(cpf) not in r.text or isinstance(cpf, bool)


async def test_cpf_conhecido_numerico_vira_texto_de_11_digitos(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    from maria.api.atendimentos import normalizar_cpf_conhecido

    class _Log:
        def __init__(self) -> None:
            self.avisos: list[tuple[str, dict[str, Any]]] = []

        def warn(self, msg: str, **campos: Any) -> None:
            self.avisos.append((msg, campos))

    log = _Log()
    corpo: dict[str, Any] = {"dadosConhecidos": {"cpf": 1234567890}}
    assert normalizar_cpf_conhecido(corpo, log) is None  # type: ignore[arg-type]
    assert corpo["dadosConhecidos"]["cpf"] == "01234567890"
    assert log.avisos[0][1] == {"campo": "dadosConhecidos.cpf", "tipoRecebido": "number"}
    assert "01234567890" not in str(log.avisos) and "1234567890" not in str(log.avisos)


@pytest.mark.parametrize("conhecidos", [{"cpf": "01234567890"}, {"cpf": ""}, {"cpf": None}, {}, None])
async def test_cpf_conhecido_texto_vazio_ou_ausente_fica_igual(conhecidos: Any) -> None:
    from maria.api.atendimentos import normalizar_cpf_conhecido

    corpo = {"dadosConhecidos": conhecidos}
    antes = repr(corpo)
    assert normalizar_cpf_conhecido(corpo, None) is None  # type: ignore[arg-type]
    assert repr(corpo) == antes


async def test_atendimentos_cpf_decimal_400(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    from maria.fluxos import ID_PESSOA_PRESA

    corpo = {"flowId": ID_PESSOA_PRESA, "chatId": "teste-296-atend", "dadosConhecidos": {"cpf": 1.5}}
    r = await cliente.post("/atendimentos", json=corpo, headers=auth)
    assert r.status_code == 400
    assert "dadosConhecidos.cpf deve ser texto" in r.json()["erro"]


async def test_atendimentos_cpf_numerico_aceito_e_dado_coletado_em_texto(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    from maria.fluxos import ID_PESSOA_PRESA

    corpo = {"flowId": ID_PESSOA_PRESA, "chatId": "teste-296-atend-ok", "dadosConhecidos": {"cpf": 1234567890}}
    r = await cliente.post("/atendimentos", json=corpo, headers=auth)
    assert r.status_code == 200
