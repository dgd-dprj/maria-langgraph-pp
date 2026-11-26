"""#231: quem acabou de se cadastrar volta com o CEP em `dadosPessoa.enderecoDetalhado`.

Decisão da Nicole (2026-11-18). O formato é o do Verde para quem já tinha cadastro: `enderecoDetalhado.cep` com 8
dígitos, texto, sem hífen (`"25780000"`, observado ao vivo, `docs/integracao-verde.md`). O POST /pessoa não muda: o
endereço vai ao Verde como foi digitado.
"""

from __future__ import annotations

import json

import httpx
import pytest

from maria.subgrafos.cadastro_pessoa.graph import cep_do_verde
from maria.subgrafos.cadastro_pessoa.graph import grafo as cadastro_pessoa
from maria.subgrafos.cadastro_pessoa.state import CadastroPessoaState
from tests.integracoes.conftest import TransporteFalso
from tests.subgrafos.conftest import Conversa, envelope


def _cadastro() -> Conversa:
    return Conversa(envelope(CadastroPessoaState, cadastro_pessoa))


@pytest.mark.parametrize(
    ("digitado", "esperado"),
    [
        ("20000000", "20000000"),
        ("20000-000", "20000000"),
        ("20.000-000", "20000000"),
        (" 20000 000 ", "20000000"),
        ("2000000", None),  # 7 dígitos
        ("200000000", None),  # 9 dígitos
        ("", None),
        ("não sei", None),
        ("٢٠٠٠٠٠٠٠", None),  # dígitos de outra escrita não contam
        (None, None),
        (20000000, None),  # só texto, como o resto do endereço digitado
    ],
)
def test_231_cep_no_formato_do_verde(digitado: object, esperado: str | None) -> None:
    assert cep_do_verde(digitado) == esperado


async def test_231_cadastro_devolve_o_cep_digitado_com_hifen_sem_o_hifen() -> None:
    c = await (await _cadastro().iniciar({"cpf": "12345678901"})).responder("Fulano de Tal", "01/01/1990", "20000-000", "10", "não")
    dados = (await c.estado())["dadosPessoa"]
    assert dados["enderecoDetalhado"] == {"cep": "20000000"}
    # Mesma ordem das chaves do Verde para quem já tinha cadastro: o endereço depois do nome.
    assert list(dados) == ["encontrado", "idPessoa", "nome", "enderecoDetalhado"]


async def test_231_cep_fora_do_formato_nao_cria_o_endereco() -> None:
    c = await (await _cadastro().iniciar({"cpf": "12345678901"})).responder("Fulano de Tal", "01/01/1990", "2000", "10", "não")
    assert "enderecoDetalhado" not in (await c.estado())["dadosPessoa"]


async def test_231_o_post_pessoa_nao_muda(verde_real: TransporteFalso) -> None:
    # O endereço vai ao Verde como foi digitado (com o hífen); só o `dadosPessoa` devolvido ao fluxo ganha o CEP limpo.
    async def responder(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path.endswith("/pessoa"):
            return httpx.Response(201, json={"dados": {"idPessoa": 4321}})
        return httpx.Response(200, json={"dados": {"uf": {"id": 19, "sigla": "RJ"}, "logradouro": "Rua A"}})

    verde_real.tratador = responder
    c = await (await _cadastro().iniciar({"cpf": "12345678901"})).responder(
        "Fulano de Tal", "01/01/1990", "20000-000", "Centro", "Rio de Janeiro", "10", "não"
    )
    posts = [json.loads(corpo) for req, corpo in zip(verde_real.requisicoes, verde_real.corpos, strict=True) if req.method == "POST"]
    assert len(posts) == 1
    assert posts[0]["endereco"]["cep"] == "20000-000"
    assert "enderecoDetalhado" not in posts[0]
    assert (await c.estado())["dadosPessoa"]["enderecoDetalhado"] == {"cep": "20000000"}
