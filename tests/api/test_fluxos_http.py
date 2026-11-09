"""Traduzido de `src/fluxos/{violenciaDomestica,pessoaPresa}/http.test.ts` (develop @ 1157a6d).

PR 1 do api: a 1ª pergunta de cada fluxo pela rota. PR 2: os outros 8 (6 de
violência doméstica e 2 de pessoa presa), que respondem pelo
`POST /atendimentos/respostas`.
"""

import json
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
    assert corpo["opcoes"] == ["Sim", "Não"]
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


# O fluxo confere o município pelo CEP antes de perguntar (#331); o mock do Verde devolve o Rio.
PLANO_SAUDE_COM_CEP = {"endereco": {"cep": "20000000"}}


@pytest.fixture
def no_release(cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # O fluxo está em teste (#324): só liga onde MARIA_AMBIENTE é "release". Depende do `cliente`,
    # que apaga a variável ao subir, para ligar depois dele.
    monkeypatch.setenv("MARIA_AMBIENTE", "release")


@pytest.mark.usefixtures("no_release")
async def test_plano_saude_primeira_pergunta_e_para_quem_sem_a_pergunta_do_canal(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    r = await cliente.post(
        "/atendimentos",
        json={"chatId": f"teste-ps-http-{next(_ids)}", "flowId": ID_PROBLEMAS_PLANO_SAUDE, "dadosConhecidos": PLANO_SAUDE_COM_CEP},
        headers=auth,
    )
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["status"] == "em_andamento"
    assert corpo["tipoResposta"] == "sim_nao"  # #430: a pergunta do canal saiu do fluxo
    assert corpo["opcoes"] == ["Sim", "Não"]
    assert "para você" in corpo["resposta"]
    assert "canal" not in corpo["metadados"]


@pytest.mark.usefixtures("no_release")
async def test_plano_saude_outra_pessoa_pergunta_o_cpf_e_cpf_invalido_tres_vezes_vai_ao_atendimento_humano(
    cliente: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    chat_id = f"teste-ps-http-{next(_ids)}"
    await cliente.post(
        "/atendimentos",
        json={"chatId": chat_id, "flowId": ID_PROBLEMAS_PLANO_SAUDE, "dadosConhecidos": PLANO_SAUDE_COM_CEP},
        headers=auth,
    )
    r = await _responder(cliente, auth, chat_id, "false")
    corpo = r.json()
    assert (r.status_code, corpo["status"], corpo["tipoResposta"]) == (200, "em_andamento", "texto")
    assert "CPF da pessoa que será atendida" in corpo["resposta"]
    assert corpo["metadados"]["paraSi"] is False
    await _responder(cliente, auth, chat_id, "123")
    await _responder(cliente, auth, chat_id, "456")
    r = await _responder(cliente, auth, chat_id, "789")
    corpo = r.json()
    assert corpo["status"] == "handoff_humano"
    assert corpo["destino"] == "atendimento_humano"
    assert corpo["metadados"]["motivoHandoff"] == "cpf_outra_pessoa_invalido"


CPF_SOLICITANTE_HTTP = "00000000000"
CPF_ATENDIDO_HTTP = "52998224725"
DADOS_PERSONAGEM = {
    **PLANO_SAUDE_COM_CEP,
    "cpf": CPF_SOLICITANTE_HTTP,
    "nome": "Pessoa de Teste",
    "imagensRecebidas": True,
    "relato": "o plano negou",
}


@pytest.mark.usefixtures("no_release")
async def test_plano_saude_outra_pessoa_devolve_solicitante_e_pessoa_atendida_em_dados_coletados_e_nao_em_metadados_nem_log(
    cliente: httpx.AsyncClient, auth: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    # #448: o dado de terceiro volta em `dadosColetados` (padrão dos outros fluxos); `metadados` e log seguem sem ele.
    chat_id = f"teste-ps-http-{next(_ids)}"
    await cliente.post(
        "/atendimentos", json={"chatId": chat_id, "flowId": ID_PROBLEMAS_PLANO_SAUDE, "dadosConhecidos": DADOS_PERSONAGEM}, headers=auth
    )
    await _responder(cliente, auth, chat_id, "false")
    r = await _responder(cliente, auth, chat_id, CPF_ATENDIDO_HTTP)  # Verde simulado (mock): encontra qualquer CPF
    corpo = r.json()
    assert (r.status_code, corpo["status"], corpo["tipoResposta"]) == (200, "em_andamento", "texto"), "imagens já vieram: vai à renda"
    coletados = corpo["dadosColetados"]
    assert coletados["cpf"] == CPF_SOLICITANTE_HTTP, "o cpf de cima continua o de quem fala"
    assert coletados["solicitante"] == {"nome": "Pessoa de Teste", "cpf": CPF_SOLICITANTE_HTTP}
    assert coletados["outraPessoa"]["cpf"] == CPF_ATENDIDO_HTTP and coletados["outraPessoa"]["origem"] == "verde"
    assert coletados["outraPessoa"]["nome"] == "Pessoa de Teste (mock)" and coletados["outraPessoa"]["email"] == "teste@exemplo.org"
    metadados = json.dumps(corpo["metadados"], ensure_ascii=False)
    saida = capsys.readouterr().out
    for dado in (CPF_ATENDIDO_HTTP, "Pessoa de Teste", "teste@exemplo.org", "21999990000"):
        assert dado not in metadados, "metadados continua sem dado pessoal"
        assert dado not in saida, "log continua sem dado pessoal, mesmo com o dado na resposta"


@pytest.mark.usefixtures("no_release")
async def test_plano_saude_para_si_mesmo_nao_traz_solicitante_nem_outra_pessoa(cliente: httpx.AsyncClient, auth: dict[str, str]) -> None:
    chat_id = f"teste-ps-http-{next(_ids)}"
    await cliente.post(
        "/atendimentos", json={"chatId": chat_id, "flowId": ID_PROBLEMAS_PLANO_SAUDE, "dadosConhecidos": DADOS_PERSONAGEM}, headers=auth
    )
    r = await _responder(cliente, auth, chat_id, "true")
    assert r.json()["dadosColetados"] == {"cpf": CPF_SOLICITANTE_HTTP}


@pytest.mark.usefixtures("no_release")
async def test_plano_saude_cpf_do_solicitante_e_o_da_pessoa_atendida_ficam_separados_ate_o_email(
    cliente: httpx.AsyncClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from maria.integracoes.email_nudecon import ResultadoEmail

    enviados: list[dict[str, str]] = []

    async def enviar(protocolo: str, dados: dict[str, str], imagens: dict[str, str]) -> ResultadoEmail:
        enviados.append(dados)
        return ResultadoEmail(True)

    monkeypatch.setattr("maria.fluxos.plano_saude.graph.enviar_email_nudecon", enviar)
    chat_id = f"teste-ps-http-{next(_ids)}"
    await cliente.post(
        "/atendimentos", json={"chatId": chat_id, "flowId": ID_PROBLEMAS_PLANO_SAUDE, "dadosConhecidos": DADOS_PERSONAGEM}, headers=auth
    )
    for resposta in ("false", CPF_ATENDIDO_HTTP, "2500"):
        await _responder(cliente, auth, chat_id, resposta)
    r = await _responder(cliente, auth, chat_id, "true")
    corpo = r.json()
    assert corpo["status"] == "concluido"
    assert corpo["dadosColetados"]["solicitante"]["cpf"] == CPF_SOLICITANTE_HTTP
    assert corpo["dadosColetados"]["outraPessoa"]["cpf"] == CPF_ATENDIDO_HTTP
    [dados] = enviados
    assert dados["CPF"] == CPF_ATENDIDO_HTTP and dados["Solicitante - CPF"] == CPF_SOLICITANTE_HTTP
    assert dados["Solicitante - Nome"] == "Pessoa de Teste"


@pytest.mark.usefixtures("no_release")
async def test_plano_saude_sem_endereco_nao_encerra_na_criacao_e_comeca_em_para_voce(
    cliente: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    # #439: sem verificação de município, o CEP deixou de ser exigido.
    r = await cliente.post(
        "/atendimentos", json={"chatId": f"teste-ps-http-{next(_ids)}", "flowId": ID_PROBLEMAS_PLANO_SAUDE}, headers=auth
    )
    corpo = r.json()
    assert r.status_code == 200
    assert (corpo["status"], corpo["tipoResposta"], corpo["opcoes"]) == ("em_andamento", "sim_nao", ["Sim", "Não"])
    assert "para você" in corpo["resposta"]
    assert "destino" not in corpo


LINK_FRENTE_HTTP = "https://downloads.tykhe.dev/arquivos/id-frente-http?token=segredo-frente-http"
LINK_VERSO_HTTP = "https://downloads.tykhe.dev/arquivos/id-verso-http?token=segredo-verso-http"


@pytest.mark.usefixtures("no_release")
async def test_plano_saude_imagens_por_link_do_pedido_a_resposta_final_398(
    cliente: httpx.AsyncClient, auth: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    chat_id = f"teste-ps-http-{next(_ids)}"
    dados = {**PLANO_SAUDE_COM_CEP, "relato": "o plano negou a minha cirurgia"}
    await cliente.post(
        "/atendimentos", json={"chatId": chat_id, "flowId": ID_PROBLEMAS_PLANO_SAUDE, "dadosConhecidos": dados}, headers=auth
    )
    r = await _responder(cliente, auth, chat_id, "true")
    assert r.json()["tipoResposta"] == "link_imagem"
    assert r.json()["tipoImagem"] == "carteirinha_frente"
    r = await _responder(cliente, auth, chat_id, LINK_FRENTE_HTTP)
    assert r.json()["tipoResposta"] == "link_imagem"
    assert r.json()["tipoImagem"] == "carteirinha_verso"
    assert "imagens" not in r.json()["dadosColetados"]
    r = await _responder(cliente, auth, chat_id, LINK_VERSO_HTTP)
    assert "renda" in r.json()["resposta"]
    assert "tipoImagem" not in r.json()
    await _responder(cliente, auth, chat_id, "2500")
    r = await _responder(cliente, auth, chat_id, "true")
    corpo = r.json()
    assert corpo["status"] == "concluido"
    assert corpo["destino"] == "email_enviado"
    assert corpo["dadosColetados"]["imagens"] == {"carteirinhaFrente": LINK_FRENTE_HTTP, "carteirinhaVerso": LINK_VERSO_HTTP}
    assert "imagens" not in str(corpo["metadados"])
    saida = capsys.readouterr()
    assert "segredo-frente-http" not in saida.out + saida.err
    assert "segredo-verso-http" not in saida.out + saida.err
    assert "id-frente-http" not in saida.out + saida.err
