"""O roteiro de ponta a ponta (#502): a conferência das respostas e os dados de teste.

O roteiro em si roda no job `ponta_a_ponta` do CI, contra a Maria no Docker. Aqui fica o
que não precisa dela: que a conferência acusa o que deve, e que os números de teste
continuam fazendo o papel de cada cenário depois de mudanças na conta do CPF (#497).
"""

from typing import Any

import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA
from maria.integracoes.verde import CPF_MOCK_FALHA_INFRA, CPF_MOCK_NAO_ENCONTRADO
from maria.shared.cpf import cpf_valido
from qa import fluxos_ponta_a_ponta as roteiro


def test_conferencia_aceita_a_resposta_esperada() -> None:
    corpo = {"status": "handoff_humano", "resposta": "Vou te passar para a equipe.", "metadados": {"motivoHandoff": "nao_e_vitima"}}
    espera = {"status": "handoff_humano", "texto": "equipe", "metadados.motivoHandoff": "nao_e_vitima"}
    assert roteiro._diferencas(200, corpo, espera) == []


def test_conferencia_acusa_cada_diferenca() -> None:
    corpo = {"status": "em_andamento", "resposta": "Qual o seu CPF?", "metadados": {}}
    espera = {"status": "concluido", "texto": "Protocolo", "metadados.motivoHandoff": "x"}
    erros = roteiro._diferencas(200, corpo, espera)
    assert len(erros) == 3
    assert any("Protocolo" in e for e in erros)


def test_conferencia_acusa_http_diferente_de_200() -> None:
    assert roteiro._diferencas(500, {}, {}) == ["HTTP 500"]


def test_rodar_para_no_primeiro_passo_errado_e_diz_o_que_veio(monkeypatch: pytest.MonkeyPatch) -> None:
    respostas = iter([(200, {"status": "em_andamento", "resposta": "É vítima?"}), (200, {"status": "em_andamento", "resposta": "Outra"})])
    chamadas: list[str] = []

    def post_falso(base: str, chave: str, caminho: str, corpo: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        chamadas.append(caminho)
        return next(respostas)

    monkeypatch.setattr(roteiro, "_post", post_falso)
    cenario = roteiro.Cenario(
        "teste", (roteiro.iniciar(ID_VIOLENCIA_DOMESTICA), roteiro.responder("Sim", texto="processo"), roteiro.responder("Não"))
    )
    ok, detalhe = roteiro.rodar("http://maria", "chave", cenario, 1)
    assert not ok
    assert detalhe.startswith("passo 2 («Sim»)")
    assert "Outra" in detalhe
    assert chamadas == ["/atendimentos", "/atendimentos/respostas"], "não segue depois do passo errado"


@pytest.mark.parametrize("cenario", [c for grupo in roteiro.GRUPOS.values() for c in grupo], ids=lambda c: c.nome)
def test_todo_cenario_comeca_abrindo_um_dos_fluxos_do_verde(cenario: roteiro.Cenario) -> None:
    primeiro = cenario.passos[0]
    assert primeiro.iniciar is not None
    assert primeiro.iniciar[0] in {ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, ID_PROBLEMAS_PLANO_SAUDE}
    assert cenario.passos[-1].espera, "o último passo confere o desfecho"


def test_numeros_de_teste_fazem_o_papel_de_cada_cenario() -> None:
    # #497: o RG nunca pode passar por CPF válido; os CPFs "bons" fecham a conta; o errado, não.
    assert not cpf_valido(roteiro.RG)
    assert not cpf_valido(roteiro.RG_LIBERTADO)
    assert cpf_valido(roteiro.CPF_VALIDO)
    assert cpf_valido(roteiro.CPF_NO_LUGAR_DO_RG)
    assert not cpf_valido(roteiro.CPF_CONTA_ERRADA)
    assert cpf_valido(CPF_MOCK_NAO_ENCONTRADO)
    assert cpf_valido(CPF_MOCK_FALHA_INFRA)
