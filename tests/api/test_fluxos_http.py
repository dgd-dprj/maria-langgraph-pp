"""Traduzido de `src/fluxos/{violenciaDomestica,pessoaPresa}/http.test.ts` (develop @ 1157a6d).

PR 1 do api: a 1ª pergunta de cada fluxo pela rota. PR 2: os outros 8 (6 de
violência doméstica e 2 de pessoa presa), que respondem pelo
`POST /atendimentos/respostas`.
"""

from itertools import count

import httpx
import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA

_ids = count(1)


async def test_violencia_domestica_primeira_pergunta_sim_nao_sobre_ser_vitima(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post("/atendimentos", json={"chatId": f"teste-vd-http-{next(_ids)}", "flowId": ID_VIOLENCIA_DOMESTICA}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["tipoResposta"] == "sim_nao"
    assert "vítima de violência doméstica" in corpo["resposta"]


async def test_pessoa_presa_primeira_pergunta_sim_nao_sobre_numero_do_processo(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post("/atendimentos", json={"chatId": f"teste-pp-http-{next(_ids)}", "flowId": ID_PESSOA_PRESA}, headers=auth)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["tipoResposta"] == "sim_nao"
    assert "número do processo" in corpo["resposta"]


# --- PR 2 do api: os testes que respondem pelo POST /atendimentos/respostas ---

VD = ID_VIOLENCIA_DOMESTICA
PP = ID_PESSOA_PRESA


async def _responder(cliente: httpx.AsyncClient, auth: dict[str, str], chat_id: str, resposta: str) -> httpx.Response:
    return await cliente.post("/atendimentos/respostas", json={"chatId": chat_id, "resposta": resposta}, headers=auth)


async def test_vd_nao_e_vitima_handoff_com_mensagem_e_motivo(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-http-vd-{next(_ids)}"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": VD}, headers=auth)
    r = await _responder(cliente, auth, chat_id, "false")
    assert r.status_code == 200
    assert r.json()["status"] == "handoff_humano"
    assert "destinado apenas para quem é vítima" in r.json()["resposta"]
    assert r.json()["metadados"]["motivoHandoff"] == "nao_e_vitima"


async def test_vd_completo_com_ro_e_cpf_em_dados_conhecidos_urgente(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-http-vd-{next(_ids)}"
    dados = {"cpf": "11111111111", "idPessoa": 1, "nome": "Teste", "email": "teste@teste.com"}
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": VD, "dadosConhecidos": dados}, headers=auth)
    await _responder(cliente, auth, chat_id, "true")  # é vítima
    await _responder(cliente, auth, chat_id, "false")  # sem processo
    r = await _responder(cliente, auth, chat_id, "true")  # tem RO; o cpf já veio: conclui direto (#191)
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "concluido"
    assert corpo["metadados"]["tipoEncaminhamento"] == "urgente"
    assert "Juizado" in corpo["resposta"]
    assert corpo["metadados"]["encaminhamentoId"] == 999999, "o encaminhamento (mock) deveria ter sido criado"
    assert "Protocolo: 999999" in corpo["resposta"]


async def test_vd_encaminhamento_falha_handoff_sem_sucesso_falso(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_ENCAMINHAMENTO_FALHA", "true")
    chat_id = f"teste-http-vd-{next(_ids)}"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": VD, "dadosConhecidos": {"cpf": "11111111111"}}, headers=auth)
    await _responder(cliente, auth, chat_id, "true")
    await _responder(cliente, auth, chat_id, "false")
    r = await _responder(cliente, auth, chat_id, "true")
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "handoff_humano"
    assert corpo["metadados"]["motivoHandoff"] == "falha_encaminhamento"
    assert "encaminhamentoId" not in corpo["metadados"]


async def test_vd_completo_sem_ro_pergunta_cpf_e_conclui_padrao(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-http-vd-{next(_ids)}"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": VD}, headers=auth)
    await _responder(cliente, auth, chat_id, "true")
    await _responder(cliente, auth, chat_id, "false")
    r_cpf = await _responder(cliente, auth, chat_id, "false")  # sem RO: pergunta o CPF
    assert "Qual o seu CPF" in r_cpf.json()["resposta"]
    r = await _responder(cliente, auth, chat_id, "11111111111")
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "concluido"
    assert corpo["metadados"]["tipoEncaminhamento"] == "padrao"
    assert corpo["metadados"]["dadosPessoa"]["encontrado"] is True
    assert "Coordenação de Defesa" in corpo["resposta"]
    assert corpo["dadosColetados"]["cpf"] == "11111111111", "o cpf coletado no fluxo aparece em dadosColetados"


async def test_vd_cpf_em_dados_conhecidos_aparece_desde_a_primeira_resposta(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-http-vd-{next(_ids)}"
    r = await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": VD, "dadosConhecidos": {"cpf": "22222222222"}}, headers=auth)
    assert r.json()["status"] == "em_andamento"
    assert r.json()["dadosColetados"]["cpf"] == "22222222222"


async def test_vd_via_orquestrador_em_dados_conhecidos_e_ignorado_191(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-http-vd-{next(_ids)}"
    dados = {"cpf": "11111111111", "viaOrquestrador": True}
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": VD, "dadosConhecidos": dados}, headers=auth)
    await _responder(cliente, auth, chat_id, "true")
    await _responder(cliente, auth, chat_id, "false")
    r = await _responder(cliente, auth, chat_id, "true")  # conclui direto, SEM pedir confirmação
    corpo = r.json()
    assert r.status_code == 200
    assert "resposta" in corpo
    assert "Confirma que seus dados são" not in corpo["resposta"], "viaOrquestrador de dadosConhecidos deve ser ignorado"
    assert corpo["status"] == "concluido"


async def test_pp_post_2x_no_mesmo_chat_id_continua_na_pergunta_do_rg(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-http-pp-{next(_ids)}"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": PP}, headers=auth)
    await _responder(cliente, auth, chat_id, "false")  # sem processo: vai para o RG
    r = await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": PP}, headers=auth)
    assert r.status_code == 200
    assert "RG da pessoa presa" in r.json()["resposta"], "deveria continuar no RG, sem voltar ao início"


async def test_pp_completo_sem_processo_handoff_com_metadados_preenchidos_49(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = f"teste-http-pp-{next(_ids)}"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": PP}, headers=auth)
    await _responder(cliente, auth, chat_id, "false")  # sem processo
    await _responder(cliente, auth, chat_id, "11111111111")  # RG
    await _responder(cliente, auth, chat_id, "true")  # confirma o nome
    monkeypatch.setenv("MOCK_CLASSIFICACAO_PARENTESCO", "Amigo(a)")  # #17
    r = await _responder(cliente, auth, chat_id, "amigo")
    monkeypatch.delenv("MOCK_CLASSIFICACAO_PARENTESCO")
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "handoff_humano"
    assert corpo["metadados"]["motivoHandoff"] == "sem_numero_processo"
    assert corpo["metadados"]["parentesco"] == "Amigo(a)"
    # dadosApenado nos metadados é um recorte (decisão de 2026-09-09), sem `encontrado`.
    apenado = corpo["metadados"]["dadosApenado"]
    assert apenado["idPessoa"] == 999999
    assert "encontrado" not in apenado
    assert apenado["tipoPreso"] == "CONDENADO"
    assert apenado["regime"] == "SEMIABERTO"


# --- Problemas com plano de saúde (NUDECON, #329) ---


async def test_plano_saude_primeira_pergunta_e_o_canal(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(
        "/atendimentos", json={"chatId": f"teste-ps-http-{next(_ids)}", "flowId": ID_PROBLEMAS_PLANO_SAUDE}, headers=auth
    )
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "em_andamento"
    assert corpo["tipoResposta"] == "texto"
    assert "das 11h às 16h" in corpo["resposta"]


async def test_plano_saude_outra_pessoa_handoff_com_destino_e_motivo(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-ps-http-{next(_ids)}"
    await cliente.post("/atendimentos", json={"chatId": chat_id, "flowId": ID_PROBLEMAS_PLANO_SAUDE}, headers=auth)
    await _responder(cliente, auth, chat_id, "por aqui")
    r = await _responder(cliente, auth, chat_id, "false")
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "handoff_humano"
    assert corpo["destino"] == "atendimento_humano"
    assert corpo["metadados"]["motivoHandoff"] == "outra_pessoa"
    assert "outra pessoa" in corpo["resposta"]
