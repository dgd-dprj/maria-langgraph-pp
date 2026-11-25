"""#231, o caminho inteiro: cadastro → `consultar_cep` da violência doméstica → resposta à Tykhe.

Quem acabou de se cadastrar volta com `enderecoDetalhado` com o `cep` e os ids (`idUf`, `idBairro`, `idMunicipio`),
como quem já tinha cadastro. Só acrescenta a chave na resposta: a pessoa não vê nada diferente.
"""

from __future__ import annotations

import httpx
import pytest

from maria.fluxos import ID_VIOLENCIA_DOMESTICA
from maria.integracoes.verde import CPF_MOCK_NAO_ENCONTRADO

# O cadastro só existe quando a conversa vem do orquestrador; o CPF não encontrado três vezes leva a ele.
RESPOSTAS = [
    "Não",  # processo
    "Não",  # boletim de ocorrência
    CPF_MOCK_NAO_ENCONTRADO,
    "sim",
    CPF_MOCK_NAO_ENCONTRADO,
    "sim",
    CPF_MOCK_NAO_ENCONTRADO,
    "Fulana de Teste",
    "01/01/1990",
    "20000-000",  # com hífen: volta sem ele
    "10",
    "não",  # complemento
    "sim",  # confirma os dados
]


async def test_231_cadastro_novo_volta_com_o_cep_e_os_ids(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", ID_VIOLENCIA_DOMESTICA)
    chat_id = "teste-231-cadastro"
    r = await cliente.post("/atendimentos/orquestrador", json={"chatId": chat_id, "mensagem": "meu marido me ameaçou"}, headers=auth)
    textos = []
    for resposta in RESPOSTAS:
        assert r.json()["status"] == "em_andamento", r.json()
        textos.append(r.json()["resposta"])
        r = await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": resposta}, headers=auth)

    assert any(t.startswith("Não encontrei seu cadastro no sistema") for t in textos), "o caminho passou pelo cadastro"
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "concluido"
    assert corpo["metadados"]["dadosPessoa"]["enderecoDetalhado"] == {"cep": "20000000", "idUf": 19, "idBairro": 9948, "idMunicipio": 3643}
