"""Testes novos da spec do módulo fluxos (spec 05, seção 6).

Os valores esperados (textos, metadados, corpos enviados ao Verde, exceções)
foram obtidos executando develop @ 0aecd98 nos mesmos cenários, na conferência
diferencial registrada no PR do módulo. Quando o Python diverge de propósito
(divergência aceita), o teste fixa o comportamento escolhido e cita o motivo.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from maria.fluxos import FLUXO_PADRAO, ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, buscar_fluxo, catalogo_para_classificacao
from maria.fluxos.padrao.graph import _construtor as construtor_padrao
from maria.fluxos.padrao.graph import obter_grafo as obter_padrao
from maria.fluxos.pessoa_presa.api import extrair_metadados_pessoa_presa
from maria.fluxos.pessoa_presa.graph import _construtor as construtor_pp
from maria.fluxos.pessoa_presa.graph import normalizar_situacao, rg_formato_valido
from maria.fluxos.pessoa_presa.graph import obter_grafo as obter_pp
from maria.fluxos.violencia_domestica.api import extrair_metadados_violencia_domestica
from maria.fluxos.violencia_domestica.graph import _construtor as construtor_vd
from maria.fluxos.violencia_domestica.graph import numero_processo_formato_valido
from maria.fluxos.violencia_domestica.graph import obter_grafo as obter_vd
from maria.shared._js import json_stringify
from maria.shared.fluxos_planejados_db import adicionar_planejado_de_teste, remover_planejado_de_teste, texto_para_classificacao
from tests.fluxos.conftest import Fluxo, novo_config, pergunta
from tests.integracoes.conftest import TransporteFalso

SEMENTE = {"input": 100, "output": 50, "total": 150}
SIM_NAO = ["Sim", "Não"]
VD_ATE_CPF_SEM_RO = ["Sim", "Não", "Não"]
VD_ATE_CPF_COM_RO = ["Sim", "Não", "Sim"]
PP_COM = ["Sim", "0000088-95.2026.8.19.0010"]
CADASTRO = ["Maria de Teste", "01/01/1990", "20000-000", "123", "não"]
FIXTURES = "tests/fixtures/contrato/http"


async def _conversa(grafo: Any, entrada: dict[str, Any], respostas: list[str]) -> tuple[Fluxo, list[dict[str, Any]], dict[str, Any]]:
    """Roda a conversa; devolve as perguntas feitas e o último resultado."""
    f = Fluxo(grafo, "teste-spec")
    r = await f.iniciar(entrada)
    perguntas = [p] if (p := pergunta(r)) else []
    for resposta in respostas:
        assert pergunta(r) is not None, f"sem pergunta pendente para {resposta!r}"
        r = await f.responder(resposta)
        if p := pergunta(r):
            perguntas.append(p)
    return f, perguntas, r


async def _metadados(f: Fluxo, extrair: Callable[[Any], dict[str, Any]]) -> str:
    return json_stringify(extrair(await f.estado()))


Rota = tuple[int, object]


def _verde(transporte: TransporteFalso, rotas: dict[tuple[str, str], Rota]) -> None:
    """Verde falso por (método, prefixo do caminho depois de /api/integra)."""

    async def responder(requisicao: httpx.Request) -> httpx.Response:
        caminho = requisicao.url.raw_path.decode().removeprefix("/api/integra")
        for (metodo, prefixo), (status, corpo) in rotas.items():
            if requisicao.method == metodo and caminho.startswith(prefixo):
                return httpx.Response(status, json=corpo)
        return httpx.Response(404, json={"dados": None})

    transporte.tratador = responder


def _enviados(transporte: TransporteFalso, prefixo: str) -> list[str]:
    return [
        f"{r.url.raw_path.decode().removeprefix('/api/integra')} {c.decode()}".strip()
        for r, c in zip(transporte.requisicoes, transporte.corpos, strict=True)
        if r.url.raw_path.decode().removeprefix("/api/integra").startswith(prefixo)
    ]


PESSOA = {"idPessoa": 4242, "nome": "Pessoa Falsa", "genero": "F", "enderecoDetalhado": {"cep": "20000000"}}
CEP = {"uf": {"id": 19, "sigla": "RJ"}, "bairro": {"id": 9948, "nome": "Centro"}, "municipio": {"id": 3643, "nome": "Rio"}}
ORGAOS = [{"id": 77, "nome": "Núcleo Falso", "enderecos": [{"municipio": "Niterói", "idLocalAtendimento": 555}]}]
APENADO = {"idSeap": 1, "idPessoa": 9, "nome": "Apenado Falso", "situacao": "ATIVO", "tipoPreso": "CONDENADO", "regime": "FECHADO"}
PROCESSO = {"id": 31, "origem": "SEEU", "nomeAssunto": "Execução"}


def _rotas_vd(**troca: Rota) -> dict[tuple[str, str], Rota]:
    rotas: dict[str, Rota] = {
        "pessoa": (200, {"dados": PESSOA}),
        "cep": (200, {"dados": CEP}),
        "plantao": (200, {"dados": []}),
        "orgaos_plantao": (200, {"dados": ORGAOS}),
        "orgaos": (200, {"dados": ORGAOS}),
        "encaminhar": (200, {"dados": {"id": 31337}}),
        "cadastro": (200, {"dados": {"idPessoa": 5150}}),
    }
    rotas.update(troca)
    return {
        ("GET", "/pessoa?cpf="): rotas["pessoa"],
        ("GET", "/cep/"): rotas["cep"],
        ("GET", "/plantao/vigente"): rotas["plantao"],
        ("GET", "/orgao/plantao/violencia-domestica"): rotas["orgaos_plantao"],
        ("GET", "/orgao/violencia-domestica"): rotas["orgaos"],
        ("POST", "/encaminhamento/encaminhar"): rotas["encaminhar"],
        ("POST", "/pessoa"): rotas["cadastro"],
    }


def _rotas_pp(apenado: object = APENADO, pessoa: object = PESSOA) -> dict[tuple[str, str], Rota]:
    return {
        ("POST", "/apenado"): (200, {"dados": apenado}),
        ("GET", "/processo/consultar/"): (200, {"dados": PROCESSO}),
        ("GET", "/pessoa?cpf="): (200, {"dados": pessoa}),
        ("POST", "/pessoa"): (200, {"dados": {"idPessoa": 5150}}),
        ("GET", "/cep/"): (200, {"dados": CEP}),
    }


# ---- teste 1: topologia igual à de develop ---------------------------------------
# Extraída de develop @ 0aecd98 (addEdge e addConditionalEdges dos graph.ts).

ARESTAS_VD = {
    ("__start__", "prepararPerguntaEhVitima"),
    ("assistidoNaoConfirmado", "__end__"),
    ("cadastroPessoa", "assistidoNaoConfirmado"),
    ("cadastroPessoa", "consultarCep"),
    ("cadastroPessoa", "falhaCadastro"),
    ("concluir", "__end__"),
    ("consultarCep", "consultarPlantao"),
    ("consultarOrgaos", "criarEncaminhamento"),
    ("consultarOrgaos", "semOrgaoDisponivel"),
    ("consultarPlantao", "consultarOrgaos"),
    ("consultarProcesso", "prepararPerguntaTemRO"),
    ("consultarProcesso", "prepararPerguntaTentarNovamenteProcesso"),
    ("cpfEsgotado", "__end__"),
    ("criarEncaminhamento", "concluir"),
    ("criarEncaminhamento", "falhaEncaminhamento"),
    ("falhaCadastro", "__end__"),
    ("falhaEncaminhamento", "__end__"),
    ("falhaInfraVerde", "__end__"),
    ("identificarAssistido", "assistidoNaoConfirmado"),
    ("identificarAssistido", "cadastroPessoa"),
    ("identificarAssistido", "consultarCep"),
    ("identificarAssistido", "cpfEsgotado"),
    ("identificarAssistido", "falhaInfraVerde"),
    ("naoEhVitima", "__end__"),
    ("pedirEhVitima", "naoEhVitima"),
    ("pedirEhVitima", "prepararPerguntaTemProcesso"),
    ("pedirNumeroProcesso", "consultarProcesso"),
    ("pedirTemProcesso", "consultarProcesso"),
    ("pedirTemProcesso", "prepararPerguntaNumeroProcesso"),
    ("pedirTemProcesso", "prepararPerguntaTemRO"),
    ("pedirTemRO", "identificarAssistido"),
    ("perguntaTentarNovamenteProcesso", "consultarProcesso"),
    ("perguntaTentarNovamenteProcesso", "prepararPerguntaNumeroProcesso"),
    ("perguntaTentarNovamenteProcesso", "prepararPerguntaTemRO"),
    ("prepararPerguntaEhVitima", "pedirEhVitima"),
    ("prepararPerguntaNumeroProcesso", "pedirNumeroProcesso"),
    ("prepararPerguntaTemProcesso", "pedirTemProcesso"),
    ("prepararPerguntaTemRO", "pedirTemRO"),
    ("prepararPerguntaTentarNovamenteProcesso", "perguntaTentarNovamenteProcesso"),
    ("semOrgaoDisponivel", "__end__"),
}

ARESTAS_PP = {
    ("__start__", "prepararPerguntaLivre"),
    ("__start__", "prepararPerguntaTemProcesso"),
    ("assistidoNaoConfirmado", "__end__"),
    ("cadastroPessoa", "assistidoNaoConfirmado"),
    ("cadastroPessoa", "concluir"),
    ("cadastroPessoa", "falhaCadastro"),
    ("concluir", "__end__"),
    ("consultarApenado", "naoConfirmado"),
    ("consultarApenado", "prepararPerguntaConfirmaNome"),
    ("consultarApenado", "prepararPerguntaTentarNovamente"),
    ("consultarProcesso", "prepararPerguntaRg"),
    ("falhaCadastro", "__end__"),
    ("falhaInfraAssistido", "__end__"),
    ("identificarAssistido", "assistidoNaoConfirmado"),
    ("identificarAssistido", "cadastroPessoa"),
    ("identificarAssistido", "concluir"),
    ("identificarAssistido", "falhaInfraAssistido"),
    ("naoConfirmado", "__end__"),
    ("pedirConfirmaNome", "naoConfirmado"),
    ("pedirConfirmaNome", "prepararPerguntaParentesco"),
    ("pedirLivre", "prepararPerguntaTemProcesso"),
    ("pedirNumeroProcesso", "consultarProcesso"),
    ("pedirParentesco", "concluir"),
    ("pedirParentesco", "identificarAssistido"),
    ("pedirRg", "consultarApenado"),
    ("pedirRg", "prepararPerguntaRgInvalido"),
    ("pedirTemProcesso", "prepararPerguntaNumeroProcesso"),
    ("pedirTemProcesso", "prepararPerguntaRg"),
    ("perguntaTentarNovamente", "consultarApenado"),
    ("perguntaTentarNovamente", "naoConfirmado"),
    ("perguntaTentarNovamente", "prepararPerguntaRg"),
    ("prepararPerguntaConfirmaNome", "pedirConfirmaNome"),
    ("prepararPerguntaLivre", "pedirLivre"),
    ("prepararPerguntaNumeroProcesso", "pedirNumeroProcesso"),
    ("prepararPerguntaParentesco", "pedirParentesco"),
    ("prepararPerguntaRg", "pedirRg"),
    ("prepararPerguntaRgInvalido", "pedirRg"),
    ("prepararPerguntaTemProcesso", "pedirTemProcesso"),
    ("prepararPerguntaTentarNovamente", "perguntaTentarNovamente"),
}

ARESTAS_PADRAO = {("__start__", "concluir"), ("concluir", "__end__")}


@pytest.mark.parametrize(
    ("construtor", "esperado"),
    [
        pytest.param(construtor_vd, ARESTAS_VD, id="violencia-domestica"),
        pytest.param(construtor_pp, ARESTAS_PP, id="pessoa-presa"),
        pytest.param(construtor_padrao, ARESTAS_PADRAO, id="padrao"),
    ],
)
def test_1_topologia_igual_a_de_develop(construtor: Any, esperado: set[tuple[str, str]]) -> None:
    assert {(a.source, a.target) for a in construtor.compile().get_graph().edges} == esperado


async def test_1_criar_grafo_devolve_grafo_sem_checkpointer() -> None:
    from maria.fluxos.pessoa_presa.graph import criar_grafo as criar_pp
    from maria.fluxos.violencia_domestica.graph import criar_grafo as criar_vd

    for criar in (criar_pp, criar_vd):
        grafo = await criar({})
        assert grafo.checkpointer is None


# ---- teste 2: interrupts ----------------------------------------------------------

PERGUNTAS_VD_CADASTRO = [
    {"pergunta": "Você é a vítima de violência doméstica?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Existe algum processo relacionado ao seu caso?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Você já registrou o Boletim de Ocorrência (RO) na delegacia?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Qual o seu CPF? Informe apenas os números.", "tipo": "texto"},
    {"pergunta": "Não encontrei ninguém com esse CPF (tentativa 1 de 3). Quer tentar de novo?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Não encontrei seu cadastro no sistema. Pra criar um novo, qual o seu nome completo?", "tipo": "texto"},
    {"pergunta": "Qual a sua data de nascimento? (dd/mm/aaaa)", "tipo": "texto"},
    {"pergunta": "Qual o CEP do seu endereço?", "tipo": "texto"},
    {"pergunta": "Qual o número?", "tipo": "texto"},
    {"pergunta": 'Tem complemento (apartamento, bloco, etc)? Se não tiver, pode responder "não".', "tipo": "texto"},
    {"pergunta": "Confirma que seus dados são: Maria de Teste?", "tipo": "sim_nao", "opcoes": SIM_NAO},
]

PERGUNTAS_VD_PROCESSO = [
    {"pergunta": "Você é a vítima de violência doméstica?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Existe algum processo relacionado ao seu caso?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Qual o número do processo? Informe apenas os números.", "tipo": "texto"},
    {"pergunta": "Não encontrei esse número de processo (tentativa 1 de 3). Quer tentar de novo?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Qual o número do processo? Informe apenas os números.", "tipo": "texto"},
    {"pergunta": "Não encontrei esse número de processo (tentativa 2 de 3). Quer tentar de novo?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Qual o número do processo? Informe apenas os números.", "tipo": "texto"},
    {"pergunta": "Você já registrou o Boletim de Ocorrência (RO) na delegacia?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Qual o seu CPF? Informe apenas os números.", "tipo": "texto"},
]

PERGUNTAS_PP_LIVRE_E_RG_INVALIDO = [
    {
        "pergunta": (
            "Pode me contar a situação com suas palavras? Se já souber, pode falar o número do processo, "
            "o RG da pessoa presa e seu parentesco com ela — tudo de uma vez."
        ),
        "tipo": "texto",
    },
    {"pergunta": "Você tem o número do processo da pessoa que está presa?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Qual o número do processo? Informe apenas os números.", "tipo": "texto"},
    {"pergunta": "Qual o RG da pessoa presa? Informe apenas os números.", "tipo": "texto"},
    {"pergunta": "O RG deve conter apenas números. Qual o RG da pessoa presa? Informe apenas os números.", "tipo": "texto"},
    {"pergunta": "Confirma que a pessoa presa é Pessoa de Teste (mock)?", "tipo": "sim_nao", "opcoes": SIM_NAO},
    {"pergunta": "Qual seu parentesco com a pessoa presa?", "tipo": "texto"},
]


async def test_2_interrupts_violencia_domestica_com_cadastro() -> None:
    _, perguntas, _ = await _conversa(obter_vd(), {"viaOrquestrador": True}, [*VD_ATE_CPF_COM_RO, "00000000000", "Não", *CADASTRO])
    assert json_stringify(perguntas) == json_stringify(PERGUNTAS_VD_CADASTRO)


async def test_2_interrupts_violencia_domestica_retry_de_processo() -> None:
    respostas = ["Sim", "Sim", "000000000", "Sim", "000000000", "Sim", "000000000", "Não"]
    _, perguntas, _ = await _conversa(obter_vd(), {}, respostas)
    assert json_stringify(perguntas) == json_stringify(PERGUNTAS_VD_PROCESSO)


async def test_2_interrupts_pessoa_presa_relato_livre_e_rg_invalido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACAO_LIVRE_IA", "true")
    _, perguntas, _ = await _conversa(obter_pp(), {}, ["relato", *PP_COM, "abc", "11111111111", "Sim"])
    # `opcoes` só nos sim_nao: a chave nem existe nos de texto.
    assert json_stringify(perguntas) == json_stringify(PERGUNTAS_PP_LIVRE_E_RG_INVALIDO)


# ---- teste 3: tabela 0.2 da spec, um teste por linha --------------------------------


async def test_3_cpf_null_da_tykhe_pula_a_pergunta_como_em_develop() -> None:
    # Presença da chave: develop pula e consulta "" (o mock encontra).
    _, perguntas, r = await _conversa(obter_vd(), {"cpf": None}, VD_ATE_CPF_SEM_RO)
    assert "Qual o seu CPF? Informe apenas os números." not in [p["pergunta"] for p in perguntas]
    assert r["statusFinal"] == "concluido"


async def test_3_rg_null_da_tykhe_pergunta_o_rg_divergencia_aceita() -> None:
    # Conflito (spec 05, decisão 1). Develop pula a primeira pergunta, "" falha
    # no formato e pergunta "O RG deve conter apenas números..."; o Python
    # trata None como undefined e faz a pergunta normal. Só o texto muda.
    _, perguntas, _ = await _conversa(obter_pp(), {"rg": None}, ["Não"])
    assert perguntas[-1]["pergunta"] == "Qual o RG da pessoa presa? Informe apenas os números."


async def test_3_rg_none_gravado_pelo_rg_invalido_nao_sobrevive_ao_passo() -> None:
    # Regra de estado: o `rg: undefined` de prepararPerguntaRgInvalido vira None
    # e sobrescreve o RG inválido (omitir manteria "abc" e o bypass pularia).
    f, perguntas, _ = await _conversa(obter_pp(), {}, ["Não", "abc"])
    assert perguntas[-1]["pergunta"].startswith("O RG deve conter apenas números.")
    assert (await f.estado())["rg"] is None


async def test_3_tem_processo_null_pula_e_cai_em_origem_nao_suportada() -> None:
    # Achado 6 do inventário: `temProcesso: null` não é `=== false`, e não há
    # dadosProcesso, então o desfecho é origem_processo_nao_suportada.
    _, perguntas, r = await _conversa(obter_pp(), {"temProcesso": None}, ["11111111111", "Sim", "amigo"])
    assert perguntas[0]["pergunta"] == "Qual o RG da pessoa presa? Informe apenas os números."
    assert r["motivoHandoff"] == "origem_processo_nao_suportada"


async def test_3_numero_processo_null_pula_e_consulta_vazio() -> None:
    _, perguntas, r = await _conversa(obter_pp(), {"temProcesso": True, "numeroProcesso": None}, ["11111111111", "Sim", "amigo"])
    assert perguntas[0]["pergunta"] == "Qual o RG da pessoa presa? Informe apenas os números."
    assert r["dadosProcesso"]["origem"] == "SEEU"
    assert r["statusFinal"] == "concluido"


async def test_3_parentesco_null_pula_e_vai_como_null_nos_metadados() -> None:
    f, perguntas, _ = await _conversa(obter_pp(), {"parentesco": None}, ["Não", "11111111111", "Sim"])
    assert "Qual seu parentesco com a pessoa presa?" not in [p["pergunta"] for p in perguntas]
    assert await _metadados(f, extrair_metadados_pessoa_presa) == (
        '{"parentesco":null,"temProcesso":false,"rg":"11111111111","dadosApenado":{"idSeap":999999,"idPessoa":999999,'
        '"nome":"Pessoa de Teste (mock)","situacao":"ATIVO","tipoPreso":"CONDENADO","regime":"SEMIABERTO"},'
        '"motivoHandoff":"sem_numero_processo"}'
    )


async def test_3_encaminhamento_id_null_vai_para_falha_divergencia_aceita(verde_real: TransporteFalso) -> None:
    # Conflito (spec 05, decisão 1): develop conclui com "Protocolo: null.".
    # O Python vai para falha, para não mostrar protocolo inválido (#238).
    _verde(verde_real, _rotas_vd(encaminhar=(200, {"dados": {"id": None}})))
    f, _, r = await _conversa(obter_vd(), {}, [*VD_ATE_CPF_SEM_RO, "12345678901"])
    assert r["motivoHandoff"] == "falha_encaminhamento"
    assert "encaminhamentoId" not in json.loads(await _metadados(f, extrair_metadados_violencia_domestica))


async def test_3_encaminhamento_sem_id_vai_para_falha_como_em_develop_238(verde_real: TransporteFalso) -> None:
    _verde(verde_real, _rotas_vd(encaminhar=(200, {"dados": {}})))
    _, _, r = await _conversa(obter_vd(), {}, [*VD_ATE_CPF_SEM_RO, "12345678901"])
    assert r["motivoHandoff"] == "falha_encaminhamento"


async def test_3_pergunta_atual_texto_e_reescrito_a_cada_pergunta() -> None:
    # `perguntaAtualTexto: undefined` do prepararPergunta vira None e apaga um
    # valor pré-preenchido, como em develop.
    _, perguntas, _ = await _conversa(obter_vd(), {"perguntaAtualTexto": "texto velho"}, [])
    assert perguntas[0]["pergunta"] == "Você é a vítima de violência doméstica?"


async def test_3_id_pessoa_null_do_verde_fica_null_e_vira_zero_nas_consultas(verde_real: TransporteFalso) -> None:
    _verde(verde_real, _rotas_vd(pessoa=(200, {"dados": {**PESSOA, "idPessoa": None}})))
    _, _, r = await _conversa(obter_vd(), {}, [*VD_ATE_CPF_SEM_RO, "12345678901"])
    assert r["dadosPessoa"]["idPessoa"] is None
    assert _enviados(verde_real, "/orgao/violencia-domestica") == ["/orgao/violencia-domestica?indicacaoRO=false&idPessoa=0"]
    assert _enviados(verde_real, "/encaminhamento")[0].startswith('/encaminhamento/encaminhar {"idPessoa":0,')


async def test_3_endereco_detalhado_remove_ids_que_o_cep_nao_trouxe(verde_real: TransporteFalso) -> None:
    pessoa = {**PESSOA, "enderecoDetalhado": {"cep": "20000000", "idUf": 1, "idBairro": 2, "idMunicipio": 3, "logradouro": "Rua Y"}}
    _verde(verde_real, _rotas_vd(pessoa=(200, {"dados": pessoa}), cep=(200, {"dados": {"uf": {"id": 19, "sigla": "RJ"}}})))
    f, _, _ = await _conversa(obter_vd(), {}, [*VD_ATE_CPF_SEM_RO, "12345678901"])
    metadados = await _metadados(f, extrair_metadados_violencia_domestica)
    assert '"enderecoDetalhado":{"cep":"20000000","idUf":19,"logradouro":"Rua Y"}' in metadados


async def test_3_endereco_detalhado_mantem_a_posicao_das_chaves(verde_real: TransporteFalso) -> None:
    # O spread de develop sobrescreve no lugar; chave nova vai para o fim.
    pessoa = {**PESSOA, "enderecoDetalhado": {"idMunicipio": 3, "cep": "20000000", "idUf": 1, "logradouro": "Rua Y"}}
    _verde(verde_real, _rotas_vd(pessoa=(200, {"dados": pessoa})))
    f, _, _ = await _conversa(obter_vd(), {}, [*VD_ATE_CPF_SEM_RO, "12345678901"])
    metadados = await _metadados(f, extrair_metadados_violencia_domestica)
    assert '"enderecoDetalhado":{"idMunicipio":3643,"cep":"20000000","idUf":19,"logradouro":"Rua Y","idBairro":9948}' in metadados


@pytest.mark.parametrize(
    ("orgaos", "corpo_esperado", "mensagem"),
    [
        pytest.param(
            [{"id": 7, "nome": "X", "enderecos": [{"idLocalAtendimento": None, "municipio": "Niterói"}]}],
            '{"idPessoa":4242,"idOrgao":7,"idLocalAtendimento":null,"urgencia":false,'
            '"preferenciaAtendimento":"Remoto","fluxoEncaminhamento":"VIOLENCIA_DOMESTICA"}',
            "Vou encaminhar seu caso para X (Niterói). Protocolo: 31337.",
            id="null-vai-como-null",
        ),
        pytest.param(
            [{"id": 7, "nome": "X"}],
            '{"idPessoa":4242,"idOrgao":7,"urgencia":false,"preferenciaAtendimento":"Remoto","fluxoEncaminhamento":"VIOLENCIA_DOMESTICA"}',
            "Vou encaminhar seu caso para X. Protocolo: 31337.",
            id="ausente-e-omitido",
        ),
        pytest.param(
            [{"id": 7, "nome": None, "enderecos": [{"municipio": ""}]}],
            '{"idPessoa":4242,"idOrgao":7,"urgencia":false,"preferenciaAtendimento":"Remoto","fluxoEncaminhamento":"VIOLENCIA_DOMESTICA"}',
            "Vou encaminhar seu caso para . Protocolo: 31337.",
            id="nome-null-e-municipio-vazio",
        ),
    ],
)
async def test_3_id_local_atendimento(verde_real: TransporteFalso, orgaos: list[Any], corpo_esperado: str, mensagem: str) -> None:
    _verde(verde_real, _rotas_vd(orgaos=(200, {"dados": orgaos})))
    _, _, r = await _conversa(obter_vd(), {}, [*VD_ATE_CPF_SEM_RO, "12345678901"])
    assert _enviados(verde_real, "/encaminhamento") == [f"/encaminhamento/encaminhar {corpo_esperado}"]
    assert r["mensagemFinal"] == mensagem


async def test_3_terminal_sem_mensagem_deixa_a_chave_ausente() -> None:
    # A rota usa `values.mensagemFinal ?? mensagemHandoff`: a chave não pode
    # existir com None depois de falhaInfraVerde.
    f, _, r = await _conversa(obter_vd(), {}, [*VD_ATE_CPF_SEM_RO, "66666666666"])
    assert r["motivoHandoff"] == "falha_infra_verde"
    assert "mensagemFinal" not in await f.estado()


async def test_3_mensagem_final_null_da_tykhe_fica_null_no_canal() -> None:
    f, _, r = await _conversa(obter_pp(), {"mensagemFinal": None}, ["Não", "11111111111", "Não"])
    assert r["motivoHandoff"] == "nome_nao_confirmado"
    assert (await f.estado())["mensagemFinal"] is None


async def test_3_cadastro_erro_null_da_tykhe_vai_para_falha_sem_confirmacao() -> None:
    # Presença da chave, no fluxo e no subgrafo (corrigido em código mergeado).
    _, perguntas, r = await _conversa(
        obter_vd(), {"viaOrquestrador": True, "cadastroErro": None}, [*VD_ATE_CPF_COM_RO, "00000000000", "Não", *CADASTRO]
    )
    assert pergunta(r) is None
    assert perguntas[-1]["pergunta"].startswith("Tem complemento")
    assert r["motivoHandoff"] == "falha_cadastro"
    assert r["mensagemFinal"] == (
        "Não consegui localizar nem cadastrar seus dados no sistema. Vou encaminhar seu atendimento pra um atendente confirmar manualmente."
    )


# ---- teste 4: metadados, chaves e ordem iguais às de develop ------------------------


def _fixture_metadados(nome: str) -> str:
    with open(f"{FIXTURES}/{nome}.json", encoding="utf-8") as arquivo:
        fixture = json.load(arquivo)
    # json.load preserva a ordem do corpoBruto gravado de develop.
    return json_stringify(json.loads(fixture["resposta"]["corpoBruto"])["metadados"])


async def test_4_metadados_violencia_domestica_iguais_a_fixture_nao_vitima() -> None:
    f, _, _ = await _conversa(obter_vd(), {"cpf": "12345678901"}, ["false"])
    assert await _metadados(f, extrair_metadados_violencia_domestica) == _fixture_metadados("violencia-domestica-handoff-nao-vitima-200")


async def test_4_metadados_pessoa_presa_iguais_a_fixture_parciais() -> None:
    f, _, _ = await _conversa(obter_pp(), {}, ["false", "123456789"])
    assert await _metadados(f, extrair_metadados_pessoa_presa) == _fixture_metadados("pessoa-presa-get-metadados-parciais-200")


async def test_4_metadados_violencia_domestica_concluido_byte_a_byte() -> None:
    f, _, _ = await _conversa(obter_vd(), {}, [*VD_ATE_CPF_COM_RO, "11111111111"])
    assert await _metadados(f, extrair_metadados_violencia_domestica) == (
        '{"ehVitima":true,"temProcesso":false,"temRegistroOcorrencia":true,"dadosPessoa":{"encontrado":true,"idPessoa":999999,'
        '"nome":"Pessoa de Teste (mock)","genero":"Feminino","endereco":"Rua de Teste, 123 (mock)","enderecoDetalhado":{"cep":"20000-000",'
        '"idUf":19,"idBairro":9948,"idMunicipio":3643}},"orgaosViolenciaDomestica":{"encontrado":true,"orgaos":[{"id":274,'
        '"nome":"DP de Defesa da Mulher junto ao Juizado de Violência Doméstica (mock)","enderecos":[{"municipio":"Município de Teste",'
        '"idLocalAtendimento":222}]}]},"tipoEncaminhamento":"urgente","encaminhamentoId":999999}'
    )


async def test_4_metadados_pessoa_presa_concluido_byte_a_byte() -> None:
    f, _, _ = await _conversa(obter_pp(), {}, [*PP_COM, "11111111111", "Sim", "amigo"])
    assert await _metadados(f, extrair_metadados_pessoa_presa) == (
        '{"parentesco":"Outro","temProcesso":true,"numeroProcesso":"0000088-95.2026.8.19.0010","dadosProcesso":{"id":999999,"origem":"SEEU"},'
        '"rg":"11111111111","dadosApenado":{"idSeap":999999,"idPessoa":999999,"nome":"Pessoa de Teste (mock)","situacao":"ATIVO",'
        '"tipoPreso":"CONDENADO","regime":"SEMIABERTO"}}'
    )


def test_4_metadados_pessoa_presa_resumos_mantem_null_e_omitem_ausente() -> None:
    valores = {"temProcesso": False, "rg": "123456", "dadosApenado": {"encontrado": True, "idSeap": None, "idPessoa": None, "nome": "Z"}}
    assert json_stringify(extrair_metadados_pessoa_presa(valores)) == (
        '{"temProcesso":false,"rg":"123456","dadosApenado":{"idSeap":null,"idPessoa":null,"nome":"Z"}}'
    )
    # dadosProcesso null (Tykhe) e `{}` (verdadeiro em JS).
    assert "dadosProcesso" not in extrair_metadados_pessoa_presa({"dadosProcesso": None})
    assert extrair_metadados_pessoa_presa({"dadosProcesso": {}})["dadosProcesso"] == {}


# ---- teste 5: TypeError do concluir com null do Verde --------------------------------


@pytest.mark.parametrize("campo", ["situacao", "tipoPreso", "regime"])
async def test_5_null_do_verde_no_apenado_lanca_type_error_como_em_develop(verde_real: TransporteFalso, campo: str) -> None:
    _verde(verde_real, _rotas_pp(apenado={**APENADO, campo: None}))
    with pytest.raises(TypeError, match=r"^Cannot read properties of null \(reading 'toUpperCase'\)"):
        await _conversa(obter_pp(), {}, [*PP_COM, "123456", "Sim", "amigo"])


async def test_5_situacao_numero_lanca_como_em_develop(verde_real: TransporteFalso) -> None:
    _verde(verde_real, _rotas_pp(apenado={**APENADO, "situacao": 5}))
    with pytest.raises(TypeError, match=r"^situacao\.toUpperCase is not a function"):
        await _conversa(obter_pp(), {}, [*PP_COM, "123456", "Sim", "amigo"])


async def test_5_curto_circuito_situacao_fora_da_lista_nao_le_tipo_preso_null(verde_real: TransporteFalso) -> None:
    _verde(verde_real, _rotas_pp(apenado={**APENADO, "situacao": "LIBERTADO", "tipoPreso": None}))
    _, _, r = await _conversa(obter_pp(), {}, [*PP_COM, "123456", "Sim", "amigo"])
    assert r["motivoHandoff"] == "dados_pessoa_nao_atendidos"


async def test_5_campo_ausente_nao_lanca(verde_real: TransporteFalso) -> None:
    _verde(verde_real, _rotas_pp(apenado={k: v for k, v in APENADO.items() if k != "regime"}))
    _, _, r = await _conversa(obter_pp(), {}, [*PP_COM, "123456", "Sim", "amigo"])
    assert r["motivoHandoff"] == "dados_pessoa_nao_atendidos"


# ---- teste 6: texto (\d, \s e trim do JS) ---------------------------------------------


@pytest.mark.parametrize(
    ("rg", "valido"),
    [
        ("11111111111", True),
        (" 11111111111 ", True),  # o trim do zod só vale para validar
        ("\ufeff123", True),  # o trim do JS remove o BOM
        ("\x1c123", False),  # e não remove \x1c, que o strip() do Python removeria
        ("123\n", True),  # o trim remove a quebra final antes da regex
        ("1\n2", False),
        ("١٢٣", False),  # \d do JS é só ASCII
        ("12a", False),
        ("", False),
        (123, False),  # z.string() recusa número
    ],
)
def test_6_rg_formato_como_zod(rg: object, valido: bool) -> None:
    assert rg_formato_valido(rg) is valido


@pytest.mark.parametrize(
    ("numero", "valido"),
    [
        ("0000088-95.2026.8.19.0010", True),
        ("0000088.95/2026 8 19 0010", True),
        ("٠٠٠٠٠٨٨٩٥٢٠٢٦٨١٩٠٠١٠", False),
        ("000000000", False),
    ],
)
def test_6_numero_processo_20_digitos_ascii(numero: str, valido: bool) -> None:
    assert numero_processo_formato_valido(numero) is valido


@pytest.mark.parametrize(
    ("situacao", "normalizada"),
    [
        ("EM RESDOM", "RESDOM"),
        ("EM\ufeffRESDOM", "RESDOM"),  # \s do JS inclui U+FEFF
        ("EM\x1cRESDOM", "EM\x1cRESDOM"),  # e não inclui \x1c (o \s do Python inclui)
        (" em\u00a0vpf / em trabalho extramuro ", "VPF/TRABALHO EXTRAMURO"),
        ("aberto/domicílio covid-19", "ABERTO/DOMICÍLIO COVID-19"),
        ("﻿RESDOM", "RESDOM"),  # o trim de cada parte remove o BOM; o strip() do Python, não
        ("\x1cRESDOM", "\x1cRESDOM"),  # e não remove \x1c; o strip() do Python remove
    ],
)
def test_6_normalizar_situacao_com_espacos_do_js(situacao: str, normalizada: str) -> None:
    assert normalizar_situacao(situacao) == normalizada


async def test_6_rg_com_espacos_e_gravado_cru() -> None:
    f, _, _ = await _conversa(obter_pp(), {}, ["Não", " 11111111111 "])
    assert (await f.estado())["rg"] == " 11111111111 "


async def test_6_um_no_retry_do_rg_vira_rg_digitado() -> None:
    f, perguntas, _ = await _conversa(obter_pp(), {}, ["Não", "000000000", "1"])
    estado = await f.estado()
    assert estado["rg"] == "1" and estado["digitouRgDireto"] is True
    assert perguntas[-1]["pergunta"] == "Confirma que a pessoa presa é Pessoa de Teste (mock)?"


async def test_6_processo_pontuado_de_20_digitos_e_digitado_direto_e_gravado_cru() -> None:
    f, perguntas, _ = await _conversa(obter_vd(), {}, ["Sim", "0000088.95/2026 8 19 0010"])
    assert perguntas[-1]["pergunta"] == "Você já registrou o Boletim de Ocorrência (RO) na delegacia?"
    assert (await f.estado())["numeroProcesso"] == "0000088.95/2026 8 19 0010"


# ---- teste 7: lacuna herdada do subgrafos, Verde sem nome ----------------------------

PESSOA_SEM_NOME = {"idPessoa": 4242, "genero": "F", "enderecoDetalhado": {"cep": "20000000"}}


@pytest.mark.parametrize(
    ("resposta", "status", "motivo"), [("Sim", "concluido", None), ("Não", "handoff_humano", "assistido_nao_confirmado")]
)
async def test_7_violencia_domestica_verde_sem_nome(verde_real: TransporteFalso, resposta: str, status: str, motivo: str | None) -> None:
    # Conferido contra develop: "você" no lugar do nome (#236), e o desfecho segue a resposta.
    _verde(verde_real, _rotas_vd(pessoa=(200, {"dados": PESSOA_SEM_NOME})))
    _, perguntas, r = await _conversa(obter_vd(), {"viaOrquestrador": True}, [*VD_ATE_CPF_SEM_RO, "12345678901", resposta])
    assert perguntas[-1] == {"pergunta": "Confirma que seus dados são: você?", "tipo": "sim_nao", "opcoes": SIM_NAO}
    assert r["statusFinal"] == status
    assert r.get("motivoHandoff") == motivo


@pytest.mark.parametrize(
    ("resposta", "status", "motivo"), [("Sim", "concluido", None), ("Não", "handoff_humano", "assistido_nao_confirmado")]
)
async def test_7_pessoa_presa_verde_sem_nome(verde_real: TransporteFalso, resposta: str, status: str, motivo: str | None) -> None:
    _verde(verde_real, _rotas_pp(pessoa=PESSOA_SEM_NOME))
    _, perguntas, r = await _conversa(obter_pp(), {"viaOrquestrador": True}, [*PP_COM, "123456", "Sim", "amigo", "12345678901", resposta])
    assert perguntas[-1] == {"pergunta": "Confirma que seus dados são: você?", "tipo": "sim_nao", "opcoes": SIM_NAO}
    assert r["statusFinal"] == status
    assert r.get("motivoHandoff") == motivo


# ---- teste 8: tokens (semente do orquestrador, #230) ---------------------------------


async def test_8_tokens_violencia_domestica_encontrado_dobra_a_semente() -> None:
    _, _, r = await _conversa(obter_vd(), {"viaOrquestrador": True, "tokensGastos": SEMENTE}, [*VD_ATE_CPF_COM_RO, "11111111111", "sim"])
    assert r["tokensGastos"] == {"input": 200, "output": 100, "total": 300}


@pytest.mark.parametrize("fluxo", ["vd", "pp"])
async def test_8_tokens_com_cadastro_sextuplica_a_semente_como_em_develop(fluxo: str) -> None:
    respostas = (
        [*VD_ATE_CPF_COM_RO, "00000000000", "Não", *CADASTRO, "sim"]
        if fluxo == "vd"
        else [*PP_COM, "11111111111", "Sim", "amigo", "00000000000", "Não", *CADASTRO, "sim"]
    )
    grafo = obter_vd() if fluxo == "vd" else obter_pp()
    _, _, r = await _conversa(grafo, {"viaOrquestrador": True, "tokensGastos": SEMENTE}, respostas)
    assert r["tokensGastos"] == {"input": 600, "output": 300, "total": 900}


async def test_8_tokens_padrao_repassa_a_semente() -> None:
    r = await obter_padrao().ainvoke({"tokensGastos": SEMENTE}, novo_config("teste-spec"))
    assert r["tokensGastos"] == SEMENTE


# ---- catálogo (fluxos/index.ts) --------------------------------------------------------


async def test_catalogo_buscar_fluxo_e_classificacao() -> None:
    assert (await buscar_fluxo(ID_PESSOA_PRESA)).nome == "pessoa-presa"  # type: ignore[union-attr]
    vd = await buscar_fluxo(ID_VIOLENCIA_DOMESTICA)
    assert vd is not None and vd.id_categoria_assunto_verde == 10113
    assert await buscar_fluxo("00000000-0000-0000-0000-00000000ffff") is None
    planejado = "00000000-0000-0000-0000-0000000000c3"
    await adicionar_planejado_de_teste(
        {"id": planejado, "nome": "planejado", "descricao": "desc", "idCategoriaAssuntoVerde": 1, "palavrasChave": ["a"]}
    )
    try:
        assert await buscar_fluxo(planejado) is FLUXO_PADRAO
        catalogo = await catalogo_para_classificacao()
        assert [c["id"] for c in catalogo[:2]] == [ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA]
        assert any(c["id"] == planejado for c in catalogo[2:])
        item = next(c for c in catalogo if c["id"] == planejado)
        assert item["descricao"] == texto_para_classificacao(
            {"id": planejado, "nome": "planejado", "descricao": "desc", "idCategoriaAssuntoVerde": 1, "palavrasChave": ["a"]}
        )
    finally:
        await remover_planejado_de_teste(planejado)


async def test_3_mock_de_parentesco_vazio_passa_como_vazio_pelo_coalesce(monkeypatch: pytest.MonkeyPatch) -> None:
    # `process.env.MOCK_CLASSIFICACAO_PARENTESCO ?? "Outro"`: "" não é nullish.
    monkeypatch.setenv("MOCK_CLASSIFICACAO_PARENTESCO", "")
    f, _, _ = await _conversa(obter_pp(), {}, ["Não", "11111111111", "Sim", "amigo"])
    assert (await f.estado())["parentesco"] == ""


@pytest.mark.parametrize("canal", ["temProcesso", "numeroProcesso", "parentesco"])
async def test_3_preparar_pula_com_null_da_tykhe_sem_reescrever(canal: str) -> None:
    # Com IA ligada, preparar a pergunta custa uma chamada ao Bedrock. O bypass do
    # "preparar" é pela presença da chave, como o do "pedir"; em APP_ENV=test o
    # efeito não aparece no fluxo, por isso o nó é testado direto.
    from maria.fluxos.pessoa_presa import graph as pp

    preparar = {
        "temProcesso": pp.preparar_pergunta_tem_processo,
        "numeroProcesso": pp.preparar_pergunta_numero_processo,
        "parentesco": pp.preparar_pergunta_parentesco,
    }[canal]
    assert await preparar({canal: None}) == {}  # type: ignore[misc]
    assert await preparar({}) != {}


async def test_3_rg_none_do_rg_invalido_nao_vai_para_os_metadados() -> None:
    # Develop grava undefined, que some do JSON; o None do Python não pode virar null.
    f, _, _ = await _conversa(obter_pp(), {}, ["Não", "abc"])
    assert "rg" not in json.loads(await _metadados(f, extrair_metadados_pessoa_presa))
