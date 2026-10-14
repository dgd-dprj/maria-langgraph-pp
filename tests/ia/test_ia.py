"""Testes novos da spec do módulo ia (seção 7), contra o Bedrock falso local.

Cada número refere-se à seção 7 da spec; os casos "NN-..." são os da
caracterização de develop @ 4e695f2 (`tests/fixtures/ia/resultados-develop.json`).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from maria.ia import classificar_fluxos, desambiguar, extrair, reescrever, sumarizar
from maria.ia.classificar import classificar_entre_opcoes, classificar_multiplo_entre_opcoes
from maria.ia.classificar_fluxos import classificar_fluxos_plausiveis
from maria.ia.desambiguar import gerar_pergunta_desambiguacao
from maria.ia.extrair import extrair_campos_livre
from maria.ia.reescrever import preparar_pergunta, reescrever_pergunta
from maria.ia.sumarizar import sumarizar_relato
from tests.ia.conftest import ERRO_500, SO_TEXTO, THROTTLE, VALIDACAO_400, BedrockFalso, ferramenta, linhas_de_log

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ia"
SIS = "sistema de teste"
TOKENS = {"tokensEntrada": 11, "tokensSaida": 7, "tokensTotal": 18}


def _com_ordem(valor: Any) -> Any:
    """Objeto JSON como lista de pares, para comparar também a ordem das chaves."""
    if isinstance(valor, dict):
        return [(k, _com_ordem(v)) for k, v in valor.items()]
    if isinstance(valor, list):
        return [_com_ordem(v) for v in valor]
    return valor


def _fixture(nome: str) -> dict[str, Any]:
    dados: dict[str, Any] = json.loads((FIXTURES / f"{nome}.requisicao.json").read_text(encoding="utf-8"))
    return dados


# ---- 1 e 1b: requisição idêntica à de develop ---------------------------------


CASOS_DE_REQUISICAO = [
    ("01-escolha-unica-valida", {"escolhaId": "b"}, lambda: classificar_entre_opcoes("msg", SIS, ["a", "b"])),
    ("06-multipla-fora-da-lista", {"idsPlausiveis": ["a", "inventado"]}, lambda: classificar_multiplo_entre_opcoes("msg", SIS, ["a", "b"])),
    (
        "14-desambiguar-tipo-errado",
        {"pergunta": ["a", "b"]},
        lambda: gerar_pergunta_desambiguacao(
            "relato", [{"id": "a", "nome": "A", "descricao": "da"}, {"id": "b", "nome": "B", "descricao": "db"}]
        ),
    ),
    ("15-sumarizar-ok", {"resumo": "resumo curto"}, lambda: sumarizar_relato("relato longo")),
    (
        "20-prompt-classificar-fluxos",
        {"idsPlausiveis": ["f1"]},
        lambda: classificar_fluxos_plausiveis(
            "meu marido me bateu",
            [
                {"id": "f1", "nome": "Violência doméstica", "descricao": "agressão em casa"},
                {"id": "f2", "nome": "Pessoa presa", "descricao": "parente preso"},
            ],
        ),
    ),
    ("21-prompt-extrair", {"rg": "123"}, lambda: extrair_campos_livre("rg 123")),
    ("22-prompt-reescrever", {"pergunta": "Qual é o seu RG? 🙂"}, lambda: reescrever_pergunta("rg", "Qual o RG?")),
]


@pytest.mark.parametrize(("caso", "entrada", "chamar"), CASOS_DE_REQUISICAO, ids=[c[0] for c in CASOS_DE_REQUISICAO])
async def test_1_corpo_converse_igual_ao_de_develop(bedrock: BedrockFalso, caso: str, entrada: Any, chamar: Any) -> None:
    bedrock.roteirizar(ferramenta(entrada))
    await chamar()
    esperado = _fixture(caso)
    assert len(bedrock.requisicoes) == 1
    assert bedrock.requisicoes[0].caminho == esperado["caminho"]
    # Estrutura E ordem das chaves: system, messages, toolConfig completo e
    # nenhum inferenceConfig (o langchain-aws Python manda um vazio por padrão).
    assert _com_ordem(bedrock.requisicoes[0].corpo) == _com_ordem(esperado["corpo"])
    assert "inferenceConfig" not in bedrock.requisicoes[0].corpo


async def test_1b_tool_choice_por_nome_com_o_modelo_de_producao(bedrock: BedrockFalso) -> None:
    bedrock.roteirizar(ferramenta({"escolhaId": "a"}))
    await classificar_entre_opcoes("msg", SIS, ["a", "b"])
    corpo = bedrock.requisicoes[0].corpo
    assert bedrock.requisicoes[0].caminho == "/model/us.anthropic.claude-haiku-4-5-20251001-v1:0/converse"
    assert corpo["toolConfig"]["toolChoice"] == {"tool": {"name": "extract"}}


# ---- 2, 2b, 2c e 3: saída sem validação (ponto 4 da #208) -----------------------

# A ausência de validação é DELIBERADA e TEMPORÁRIA: reproduz develop @ 4e695f2,
# onde o z.enum só descrevia a saída no prompt e nada era barrado na volta.
# Hoje um id inventado é aceito, e no parentesco chega à Tykhe.
# Defeito registrado em https://github.com/dgd-dprj/maria-langgraph-pp/issues/212
# Não "corrija" validando aqui: isso muda desfecho de atendimento sem ninguém notar.
# A correção é feita naquela issue, que substitui este teste.


async def test_2_id_fora_da_lista_passa_como_em_develop(bedrock: BedrockFalso) -> None:
    # Ver o comentário acima: defeito de develop reproduzido, #212.
    bedrock.roteirizar(ferramenta({"escolhaId": "inventado"}))
    assert await classificar_entre_opcoes("msg", SIS, ["a", "b"]) == {"escolhaId": "inventado", "viaIA": True, **TOKENS}


async def test_2_tipo_errado_passa_como_em_develop(bedrock: BedrockFalso) -> None:
    # #212: caso 04.
    bedrock.roteirizar(ferramenta({"escolhaId": 7}))
    assert await classificar_entre_opcoes("msg", SIS, ["a", "b"]) == {"escolhaId": 7, "viaIA": True, **TOKENS}


async def test_2b_multipla_sem_validacao(bedrock: BedrockFalso) -> None:
    # #212: casos 06 e 07. Com string, devolve a string (o orquestrador lança
    # TypeError em develop ao fazer ids.map; isso é do módulo orquestrador).
    bedrock.roteirizar(ferramenta({"idsPlausiveis": ["a", "inventado"]}))
    assert await classificar_multiplo_entre_opcoes("msg", SIS, ["a", "b"]) == {"ids": ["a", "inventado"], "viaIA": True, **TOKENS}
    bedrock.roteirizar(ferramenta({"idsPlausiveis": "a"}))
    assert await classificar_multiplo_entre_opcoes("msg", SIS, ["a", "b"]) == {"ids": "a", "viaIA": True, **TOKENS}


async def test_2c_nenhum_e_chave_ausente(bedrock: BedrockFalso) -> None:
    bedrock.roteirizar(ferramenta({"escolhaId": "nenhum"}))
    assert await classificar_entre_opcoes("msg", SIS, ["a", "b"]) == {"escolhaId": None, "viaIA": True, **TOKENS}
    bedrock.roteirizar(ferramenta({}))
    assert await classificar_entre_opcoes("msg", SIS, ["a", "b"]) == {"viaIA": True, **TOKENS}


async def test_3_outros_esquemas_sem_validacao(bedrock: BedrockFalso) -> None:
    # #212: casos 12, 13 e 14.
    bedrock.roteirizar(ferramenta({}))
    assert await reescrever_pergunta("rg", "Qual o RG?") == {"viaIA": True, **TOKENS}  # sem `texto`, e não o original
    bedrock.roteirizar(ferramenta({"temProcesso": "sim", "rg": 123456, "extra": "x"}))
    assert await extrair_campos_livre("meu filho tá preso, rg 123456") == {
        "temProcesso": "sim",
        "rg": 123456,
        "extra": "x",
        "viaIA": True,
        **TOKENS,
    }
    bedrock.roteirizar(ferramenta({"pergunta": ["a", "b"]}))
    candidatos: list[desambiguar.CandidatoParaDesambiguar] = [
        {"id": "a", "nome": "A", "descricao": "da"},
        {"id": "b", "nome": "B", "descricao": "db"},
    ]
    assert await gerar_pergunta_desambiguacao("relato", candidatos) == {"pergunta": ["a", "b"], "viaIA": True, **TOKENS}


async def test_3_extrair_espalha_args_e_sobrescreve_com_os_proprios_campos(bedrock: BedrockFalso) -> None:
    # {...parsed, viaIA, tokensEntrada: uso?.input_tokens}: o que o modelo
    # mandar com esses nomes é sobrescrito; sem `usage`, as chaves somem.
    bedrock.roteirizar(ferramenta({"rg": "1", "viaIA": "x", "tokensEntrada": 99}))
    assert await extrair_campos_livre("rg 1") == {"rg": "1", "viaIA": True, **TOKENS}


# ---- 4: resposta sem a ferramenta ------------------------------------------------


async def test_4_sem_tool_use_uma_requisicao_e_fallback(bedrock: BedrockFalso, capsys: pytest.CaptureFixture[str]) -> None:
    bedrock.roteirizar(SO_TEXTO)
    capsys.readouterr()
    assert await classificar_entre_opcoes("msg", SIS, ["a", "b"]) == {"escolhaId": None, "viaIA": False}
    assert len(bedrock.requisicoes) == 1  # falha de parse não dispara retry
    (linha,) = linhas_de_log(capsys)
    assert linha["level"] == 50
    assert linha["err"]["type"] == "TypeError"


async def test_4_extrair_sem_tool_use_nao_cai_no_fallback(bedrock: BedrockFalso) -> None:
    # Espalhar null em JS não lança: {...null, viaIA: true, tokens}.
    bedrock.roteirizar(SO_TEXTO)
    assert await extrair_campos_livre("texto") == {"viaIA": True, **TOKENS}
    assert len(bedrock.requisicoes) == 1


# ---- 5 e 5b: tokens (ponto 5 da #208) ---------------------------------------------


async def test_5_as_seis_funcoes_devolvem_a_contagem_de_tokens(bedrock: BedrockFalso) -> None:
    # Se a contagem não chegar (biblioteca, versão ou leitura com getattr), falha.
    bedrock.roteirizar(ferramenta({"escolhaId": "a", "idsPlausiveis": ["a"], "pergunta": "p", "resumo": "r", "rg": "1"}))
    candidatos: list[desambiguar.CandidatoParaDesambiguar] = [{"id": "a", "nome": "A", "descricao": "d"}]
    fluxos: list[classificar_fluxos.FluxoParaClassificar] = [{"id": "a", "nome": "A", "descricao": "d"}]
    resultados: list[Any] = [
        await classificar_entre_opcoes("m", SIS, ["a"]),
        await classificar_multiplo_entre_opcoes("m", SIS, ["a"]),
        await classificar_fluxos_plausiveis("m", fluxos),
        await gerar_pergunta_desambiguacao("m", candidatos),
        await extrair_campos_livre("m"),
        await reescrever_pergunta("rg", "Qual?"),
        await sumarizar_relato("m"),
    ]
    for r in resultados:
        assert {k: r.get(k) for k in TOKENS} == TOKENS
    preparado = await preparar_pergunta("rg", "Qual?")
    assert preparado["tokensGastos"] == {"input": 11, "output": 7, "total": 18}
    assert preparado["perguntaAtualTokensTotal"] == 18


async def test_5b_sem_usage_diverge_de_develop_e_cai_no_fallback(bedrock: BedrockFalso, capsys: pytest.CaptureFixture[str]) -> None:
    # DIVERGÊNCIA REGISTRADA (MIGRACAO.md): em develop, resposta sem `usage` dá
    # viaIA: true sem tokens, e o prepararPergunta grava {0,0,0} (casos 09 e 10).
    # O langchain-aws Python lança KeyError('usage') ao ler a resposta: a chamada
    # é retentada (3 requisições) e cai no fallback. O caminho só existe com um
    # Bedrock que viole o contrato: `usage` é obrigatório na resposta Converse
    # (modelo de serviço do botocore, ConverseResponse.required).
    bedrock.roteirizar(ferramenta({"escolhaId": "a"}, uso=None))
    capsys.readouterr()
    assert await classificar_entre_opcoes("msg", SIS, ["a", "b"]) == {"escolhaId": None, "viaIA": False}
    assert len(bedrock.requisicoes) == 3
    (linha,) = linhas_de_log(capsys)
    assert linha["err"]["type"] == "KeyError"


async def test_5b_preparar_sem_ia_grava_none_no_canal(bedrock: BedrockFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REESCREVER_IA")
    assert await preparar_pergunta("rg", "Qual o RG?") == {
        "perguntaAtualTexto": "Qual o RG?",
        "perguntaAtualViaIA": False,
        # Presente com None: em develop o `undefined` é gravado no canal do
        # estado (Object.entries mantém a chave); omitir manteria o valor anterior.
        "perguntaAtualTokensTotal": None,
        "tokensGastos": {"input": 0, "output": 0, "total": 0},
    }


async def test_5b_preparar_com_texto_ausente_grava_none(bedrock: BedrockFalso) -> None:
    # Caso 12 através do preparar: `texto` ausente vira perguntaAtualTexto None (#212).
    bedrock.roteirizar(ferramenta({}))
    assert (await preparar_pergunta("rg", "Qual o RG?"))["perguntaAtualTexto"] is None


# ---- 6: guard de ids vazio ---------------------------------------------------------


async def test_6_ids_vazio_nao_chama_o_bedrock(bedrock: BedrockFalso) -> None:
    bedrock.roteirizar(ferramenta({"escolhaId": "a"}))
    assert await classificar_entre_opcoes("msg", SIS, []) == {"escolhaId": None, "viaIA": False}
    assert await classificar_multiplo_entre_opcoes("msg", SIS, []) == {"ids": [], "viaIA": False}
    assert bedrock.requisicoes == []


# ---- 7 a 10: retry ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("roteiro", "requisicoes", "tipo"),
    [(THROTTLE, 9, "ThrottlingException"), (ERRO_500, 9, "InternalServerException"), (VALIDACAO_400, 3, "ValidationException")],
    ids=["7-429", "8-500", "9-400"],
)
async def test_7_a_9_falha_persistente(
    bedrock: BedrockFalso, capsys: pytest.CaptureFixture[str], roteiro: Any, requisicoes: int, tipo: str
) -> None:
    # 3 tentativas do SDK × 3 do runnable; o SDK não retenta 400.
    bedrock.roteirizar(roteiro)
    capsys.readouterr()
    assert await classificar_entre_opcoes("msg", SIS, ["a", "b"]) == {"escolhaId": None, "viaIA": False}
    assert len(bedrock.requisicoes) == requisicoes
    (linha,) = linhas_de_log(capsys)  # uma linha, não uma por tentativa
    assert linha["msg"] == "[classificar] falha ao classificar, tratando como não identificado"
    assert linha["err"]["type"] == tipo  # decisão pendente 1: o código AWS, como o nome da exceção em develop
    assert linha["err"]["message"] == roteiro.corpo["message"]


async def test_10_tres_429_e_depois_sucesso(bedrock: BedrockFalso) -> None:
    bedrock.roteirizar(THROTTLE, THROTTLE, THROTTLE, ferramenta({"escolhaId": "a"}))
    assert await classificar_entre_opcoes("msg", SIS, ["a", "b"]) == {"escolhaId": "a", "viaIA": True, **TOKENS}
    assert len(bedrock.requisicoes) == 4


# ---- 11 a 13: guards e mocks ---------------------------------------------------------


async def test_11_app_env_test_nao_chama_e_usa_os_mocks(bedrock: BedrockFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    bedrock.roteirizar(ferramenta({}))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", "")
    assert await classificar_fluxos_plausiveis("m", []) == {"ids": [], "viaIA": False}
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWIDS", " a , ,b ")
    assert await classificar_fluxos_plausiveis("m", []) == {"ids": ["a", "b"], "viaIA": False}
    monkeypatch.delenv("MOCK_CLASSIFICACAO_FLOWIDS")
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", "")
    assert await classificar_fluxos_plausiveis("m", []) == {"ids": [], "viaIA": False}
    monkeypatch.setenv("MOCK_CLASSIFICACAO_FLOWID", "x")
    assert await classificar_fluxos_plausiveis("m", []) == {"ids": ["x"], "viaIA": False}
    monkeypatch.setenv("MOCK_SUMARIZACAO_RESUMO", "")
    assert await sumarizar_relato("texto") == {"resumo": "", "viaIA": False}
    monkeypatch.delenv("MOCK_SUMARIZACAO_RESUMO")
    assert await sumarizar_relato("texto") == {"resumo": "texto", "viaIA": False}
    assert await gerar_pergunta_desambiguacao("r", []) == {"pergunta": desambiguar.TEXTO_FALLBACK, "viaIA": False}
    assert await extrair_campos_livre("t") == {"viaIA": False}
    assert await reescrever_pergunta("rg", "Qual?") == {"texto": "Qual?", "viaIA": False}
    assert bedrock.requisicoes == []


@pytest.mark.parametrize("valor", [None, "1", "TRUE"])
async def test_12_flags_desligadas_nao_chamam(bedrock: BedrockFalso, monkeypatch: pytest.MonkeyPatch, valor: str | None) -> None:
    bedrock.roteirizar(ferramenta({}))
    for flag in ("REESCREVER_IA", "EXTRACAO_LIVRE_IA"):
        if valor is None:
            monkeypatch.delenv(flag)
        else:
            monkeypatch.setenv(flag, valor)
    assert await reescrever_pergunta("rg", "Qual?") == {"texto": "Qual?", "viaIA": False}
    assert await extrair_campos_livre("t") == {"viaIA": False}
    assert bedrock.requisicoes == []


async def test_13_flag_lida_a_cada_chamada(bedrock: BedrockFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    bedrock.roteirizar(ferramenta({"pergunta": "Reescrita?"}))
    monkeypatch.setenv("REESCREVER_IA", "false")
    assert (await reescrever_pergunta("rg", "Qual?"))["viaIA"] is False
    monkeypatch.setenv("REESCREVER_IA", "true")
    assert await reescrever_pergunta("rg", "Qual?") == {"texto": "Reescrita?", "viaIA": True, **TOKENS}


# ---- 14: nada do prompt nem da resposta no log ----------------------------------------


async def test_14_log_sem_prompt_nem_resposta(bedrock: BedrockFalso, capsys: pytest.CaptureFixture[str]) -> None:
    segredo_usuario = "relato-sigiloso-RG-998877"
    segredo_sistema = "sistema-sigiloso"
    segredo_resposta = "resposta-sigilosa"
    capsys.readouterr()
    for roteiro in (ferramenta({"escolhaId": segredo_resposta}), SO_TEXTO, THROTTLE, ERRO_500, VALIDACAO_400):
        bedrock.roteirizar(roteiro)
        await classificar_entre_opcoes(segredo_usuario, segredo_sistema, ["a"])
    bedrock.roteirizar(ERRO_500)
    await reescrever_pergunta("rg", segredo_usuario)
    saida = capsys.readouterr()
    for segredo in (segredo_usuario, segredo_sistema, segredo_resposta):
        assert segredo not in saida.out
        assert segredo not in saida.err
    linhas = [json.loads(linha) for linha in saida.out.splitlines() if linha.strip()]
    assert linhas
    for linha in linhas:
        assert set(linha) <= {"level", "time", "pid", "hostname", "msg", "err", "chatId", "fluxoId", "campo"}
    assert linhas[-1]["campo"] == "rg"


def test_modulos_criam_o_modelo_com_a_config_e_a_cota_do_sdk_js() -> None:
    from maria.ia import classificar
    from maria.shared.bedrock import _CotaComoSdkJs

    for modulo in (classificar, desambiguar, extrair, reescrever, sumarizar):
        cliente = modulo.modelo.client
        assert cliente.meta.config.retries == {"mode": "standard", "total_max_attempts": 3}
        # O botocore não expõe a cota: o handler registrado em needs-retry é o
        # método de um RetryHandler, que guarda o RetryQuotaChecker.
        quotas = [
            getattr(getattr(h, "__self__", None), "_retry_quota", None)
            for h in cliente.meta.events._emitter._handlers.prefix_search("needs-retry.bedrock-runtime")
        ]
        assert any(isinstance(q, _CotaComoSdkJs) for q in quotas), modulo.__name__
