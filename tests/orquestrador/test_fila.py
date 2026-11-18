"""Regras da fila do multi-fluxo (#435): a ordem, os textos e a leitura da resposta. Sem IA."""

from __future__ import annotations

import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA
from maria.ia.classificar_necessidades import Necessidade
from maria.orquestrador import fila as f


def nec(i: str, evidencia: str = "", urgente: bool = False) -> Necessidade:
    return {"id": i, "evidencia": evidencia, "evidenciaClara": True, "urgente": urgente}


def ids(fila: list[f.ItemFila]) -> list[str]:
    return [i["id"] for i in fila]


# ---- a ordem ------------------------------------------------------------------------


def test_ordem_padrao_violencia_pessoa_presa_saude_depois_o_resto() -> None:
    """Decisão da Nicole (2026-11-13): a violência doméstica, a pessoa presa e a saúde, nessa ordem (antes, a saúde
    vinha primeiro)."""
    fila = f.montar_fila([nec("tykhe:novo-processo"), nec(ID_PESSOA_PRESA), nec(ID_VIOLENCIA_DOMESTICA), nec("tykhe:saude")])
    assert ids(fila) == [ID_VIOLENCIA_DOMESTICA, ID_PESSOA_PRESA, "tykhe:saude", "tykhe:novo-processo"]


def test_plano_de_saude_tem_a_prioridade_da_saude() -> None:
    assert ids(f.montar_fila([nec(ID_PROBLEMAS_PLANO_SAUDE), nec(ID_PESSOA_PRESA)])) == [ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE]
    assert ids(f.montar_fila([nec(ID_PROBLEMAS_PLANO_SAUDE), nec("tykhe:saude")])) == [ID_PROBLEMAS_PLANO_SAUDE, "tykhe:saude"]


def test_a_ordem_padrao_vale_mesmo_com_urgencia_em_outro_assunto() -> None:
    """Violência, pessoa presa e saúde nessa ordem, sempre: o sinal de risco não passa um deles na frente."""
    fila = f.montar_fila([nec(ID_PROBLEMAS_PLANO_SAUDE, urgente=True), nec(ID_PESSOA_PRESA)])
    assert ids(fila) == [ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE]
    fila = f.montar_fila([nec(ID_PESSOA_PRESA, urgente=True), nec(ID_VIOLENCIA_DOMESTICA)])
    assert ids(fila) == [ID_VIOLENCIA_DOMESTICA, ID_PESSOA_PRESA]


def test_no_resto_o_urgente_vem_antes_e_a_tykhe_por_ultimo() -> None:
    fila = f.montar_fila([nec("tykhe:outros"), nec("tykhe:agendamentos", urgente=True)])
    assert ids(fila) == ["tykhe:agendamentos", "tykhe:outros"]


def test_mesmo_destino_vira_um_item_e_fora_da_lista_vai_para_outros() -> None:
    fila = f.montar_fila(
        [nec(ID_PESSOA_PRESA, "irmão preso"), nec(ID_PESSOA_PRESA, "filho preso"), nec("fora_da_lista"), nec("tykhe:outros")]
    )
    assert ids(fila) == [ID_PESSOA_PRESA, "tykhe:outros"]
    assert fila[0]["evidencia"] == "irmão preso"


def test_sair_sai_da_fila_quando_ha_outro_assunto() -> None:
    assert ids(f.montar_fila([nec("tykhe:sair"), nec(ID_PESSOA_PRESA)])) == [ID_PESSOA_PRESA]
    assert ids(f.montar_fila([nec("tykhe:sair")])) == ["tykhe:sair"]


# ---- os textos ----------------------------------------------------------------------


def test_texto_com_dois_assuntos_e_urgencia() -> None:
    fila = f.montar_fila([nec(ID_PROBLEMAS_PLANO_SAUDE), nec(ID_PESSOA_PRESA, urgente=True)])
    assert f.texto_ordem(fila) == (
        "Entendi. Você falou de duas coisas: a pessoa presa e o plano de saúde.\n"
        "Vou começar pela pessoa presa, porque parece mais urgente.\n"
        "Depois, falamos do plano de saúde.\n"
        "Pode ser assim?"
    )


def test_texto_com_tres_assuntos_e_a_violencia_com_nome_discreto() -> None:
    fila = f.montar_fila([nec(ID_PESSOA_PRESA), nec(ID_VIOLENCIA_DOMESTICA), nec("tykhe:saude")])
    assert f.texto_ordem(fila) == (
        "Entendi. Você falou de três coisas:\n"
        "• a situação que você contou\n• a pessoa presa\n• a saúde\n"
        "Vou começar pela situação que você contou.\n"
        "Depois, falamos das outras.\n"
        "Pode ser assim?"
    )
    # Decisão da Nicole (2026-11-13): numerada, com a legenda, e com botões do mesmo número.
    assert f.texto_qual_primeiro(fila) == (
        "Tudo bem. Qual você quer resolver primeiro?\n\n"
        "1. A situação que você contou\n2. A pessoa presa\n3. A saúde\n\n"
        "Responda com o número da opção."
    )
    assert f.opcoes_qual_primeiro(fila) == ["1. A situação que você contou", "2. A pessoa presa", "3. A saúde"]
    assert f.assunto_escolhido("2. A pessoa presa", fila) == 1


def test_textos_nao_prometem_tudo_na_mesma_conversa() -> None:
    """Fase 1a: o próximo assunto depende da Tykhe, então a Maria não diz "tudo aqui mesmo"."""
    fila = f.montar_fila([nec(ID_PESSOA_PRESA), nec(ID_VIOLENCIA_DOMESTICA), nec("tykhe:saude")])
    assert "aqui mesmo" not in f.texto_ordem(fila) + f.texto_ordem(fila[:2])


def test_texto_comecando() -> None:
    assert f.texto_comecando(f.montar_fila([nec(ID_PESSOA_PRESA)])[0]) == "Combinado. Vamos começar pela pessoa presa."
    assert f.texto_comecando(f.montar_fila([nec(ID_PROBLEMAS_PLANO_SAUDE)])[0]) == "Combinado. Vamos começar pelo plano de saúde."


# ---- a leitura da resposta ----------------------------------------------------------


@pytest.mark.parametrize("resposta", ["Sim", "sim", "true", "s", "Pode", "pode!", "pode ser", "ss", "blz", "Ok", "isso", "aham", "tá bom"])
def test_aceitou(resposta: str) -> None:
    assert f.aceitou(resposta)
    assert not f.recusou(resposta)


@pytest.mark.parametrize("resposta", ["Não", "nao", "false", "n", "não quero", "Não, prefiro outro", "acho que nao"])
def test_recusou(resposta: str) -> None:
    assert f.recusou(resposta)
    assert not f.aceitou(resposta)


@pytest.mark.parametrize("resposta", ["não sei", "nao sei dizer", "o do meu filho", "talvez"])
def test_nem_aceitou_nem_recusou(resposta: str) -> None:
    assert not f.aceitou(resposta)
    assert not f.recusou(resposta)


def _tres() -> list[f.ItemFila]:
    return f.montar_fila(
        [
            nec("tykhe:saude", "o hospital do sus n tem vaga"),
            nec(ID_VIOLENCIA_DOMESTICA, "meu companheiro me ameaça"),
            nec(ID_PESSOA_PRESA, "meu filho foi preso"),
        ]
    )


@pytest.mark.parametrize(
    ("resposta", "posicao"),
    [
        # A ordem: a violência (0), a pessoa presa (1) e a saúde (2).
        ("3", 2),
        (" 1 ", 0),
        ("a do meu filho", 1),
        ("a pessoa presa", 1),
        ("o da cadeia", 1),
        ("a saude", 2),
        ("o hospital", 2),
        ("a situação", 0),
        ("a ameaça", 0),
    ],
)
def test_assunto_escolhido(resposta: str, posicao: int) -> None:
    assert f.assunto_escolhido(resposta, _tres()) == posicao


@pytest.mark.parametrize("resposta", ["9", "0", "tanto faz", "sim", "", "qualquer um"])
def test_assunto_escolhido_sem_saber(resposta: str) -> None:
    assert f.assunto_escolhido(resposta, _tres()) is None


def test_para_frente() -> None:
    fila = _tres()
    assert ids(f.para_frente(fila, 2)) == ["tykhe:saude", ID_VIOLENCIA_DOMESTICA, ID_PESSOA_PRESA]


def test_pendente_leva_flow_id_do_fluxo_da_maria_e_tipo_caso_da_tykhe() -> None:
    fila = _tres()
    assert f.pendente(fila[1]) == {
        "nome": "a pessoa presa",
        "urgente": False,
        "urgencia": "urgente",
        "flowId": ID_PESSOA_PRESA,
        "dadosConhecidos": {"perguntaParentesco": "Você é a mãe ou o pai dele?", "opcoesParentesco": {"mae": "Mãe", "pai": "Pai"}},
    }
    assert f.pendente(fila[2]) == {"nome": "a saúde", "urgente": False, "urgencia": "urgente", "tipoCaso": "saude"}


def test_pendente_nao_leva_o_trecho_do_relato() -> None:
    """O trecho do relato fica na Maria: a Tykhe já tem o relato, e o campo não precisa repetir texto da pessoa."""
    assert "evidencia" not in f.pendente(_tres()[0])


def test_com_dados_do_fim_leva_o_cpf_so_para_os_fluxos_da_maria() -> None:
    """#442: o CPF informado no 1º assunto segue para os próximos fluxos; a Tykhe não precisa dele de volta."""
    pendentes = [f.pendente(i) for i in _tres()]
    saida = f.com_dados_do_fim(pendentes, {"cpf": "11111111111"})
    assert "dadosConhecidos" not in saida[2]  # a saúde é da Tykhe
    assert saida[1]["dadosConhecidos"]["cpf"] == "11111111111"
    assert saida[1]["dadosConhecidos"]["perguntaParentesco"] == "Você é a mãe ou o pai dele?"
    assert f.com_dados_do_fim(pendentes, {}) == pendentes
    assert "cpf" not in pendentes[1].get("dadosConhecidos", {})  # não muda a lista original
