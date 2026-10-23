"""Tradução dos 12 testes de `test-integracao/` de develop (classificar, desambiguar,
extrair, parentesco, reescrever, sumarizar).

Chamam o Bedrock DE VERDADE: custam dinheiro e precisam de credencial AWS
válida. Ficam fora da suíte padrão e do CI pelo marcador `integracao`; rodar à
mão com `uv run pytest -m integracao tests/integracao/ia`.
"""

import pytest

from maria.ia.classificar import classificar_entre_opcoes, classificar_multiplo_entre_opcoes
from maria.ia.desambiguar import gerar_pergunta_desambiguacao
from maria.ia.extrair import extrair_campos_livre
from maria.ia.reescrever import preparar_pergunta, reescrever_pergunta
from maria.ia.sumarizar import sumarizar_relato

pytestmark = pytest.mark.integracao


@pytest.fixture(autouse=True)
def _fora_do_modo_teste(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("REESCREVER_IA", "true")
    monkeypatch.setenv("EXTRACAO_LIVRE_IA", "true")


def _tokens_positivos(resultado: dict[str, object]) -> None:
    for chave in ("tokensTotal", "tokensEntrada", "tokensSaida"):  # #34 e #69
        valor = resultado.get(chave)
        assert isinstance(valor, int) and valor > 0, chave


# ---- classificar.test.ts --------------------------------------------------------

SISTEMA_ANIMAIS = """Você escolhe entre candidatos de teste. Responda com o id que melhor combina, ou "nenhum".
Candidatos:
- id "gato": relacionado a gatos, felinos, miar
- id "cachorro": relacionado a cachorros, cães, latir"""


async def test_classificar_entre_opcoes_escolhe_o_certo_e_devolve_tokens() -> None:
    resultado = await classificar_entre_opcoes("meu gato não para de miar a noite toda", SISTEMA_ANIMAIS, ["gato", "cachorro"])
    assert resultado["viaIA"] is True, "esperava a IA responder com sucesso (credencial AWS configurada)"
    assert resultado.get("escolhaId") == "gato"
    _tokens_positivos(dict(resultado))
    assert resultado["tokensEntrada"] + resultado["tokensSaida"] == resultado["tokensTotal"]


async def test_classificar_multiplo_devolve_tokens() -> None:
    resultado = await classificar_multiplo_entre_opcoes("tenho um bichano em casa", SISTEMA_ANIMAIS, ["gato", "cachorro"])
    assert resultado["viaIA"] is True
    assert "gato" in resultado.get("ids", [])
    _tokens_positivos(dict(resultado))


# ---- desambiguar.test.ts --------------------------------------------------------


async def test_desambiguar_gera_pergunta_real_e_devolve_tokens() -> None:
    resultado = await gerar_pergunta_desambiguacao(
        "tenho um amigo que está preso, queria visitar ele",
        [
            {"id": "1", "nome": "regulamentar visita", "descricao": "Direito de visitas: crianças, adolescentes, idosos e pessoas presas"},
            {"id": "2", "nome": "pessoa-presa", "descricao": "Informação ou encaminhamento sobre uma pessoa que está presa"},
        ],
    )
    assert resultado["viaIA"] is True
    pergunta = resultado.get("pergunta")
    assert isinstance(pergunta, str) and len(pergunta) > 0
    _tokens_positivos(dict(resultado))


# ---- extrair.test.ts --------------------------------------------------------------


async def test_extrair_rg_e_parentesco_de_relato_real() -> None:
    resultado = await extrair_campos_livre(
        "Meu marido José da Silva tá preso, o RG dele é 12345678, temos processo aberto sim, é o numero"
        " 0000088-95.2026.8.19.0010, e eu sou esposa dele"
    )
    assert resultado["viaIA"] is True
    assert resultado.get("temProcesso") is True
    assert resultado.get("rg") == "12345678"
    assert "esposa" in str(resultado.get("parentesco") or "").lower()
    assert "0000088-95.2026.8.19.0010" in str(resultado.get("numeroProcesso") or "")
    _tokens_positivos(dict(resultado))


async def test_extrair_nao_forca_campo_nao_mencionado() -> None:
    resultado = await extrair_campos_livre("Sou irmã da pessoa presa")
    assert resultado["viaIA"] is True
    assert "irm" in str(resultado.get("parentesco") or "").lower()
    assert "rg" not in resultado, "RG não foi mencionado, não deveria vir preenchido"
    assert "numeroProcesso" not in resultado, "número do processo não foi mencionado"


# ---- parentesco.test.ts (lista e sistema reais de classificarParentesco) -----------

PARENTESCOS_PERMITIDOS = [
    "Mãe",
    "Pai",
    "Irmão(a)",
    "Esposo(a)",
    "Ex-esposo(a)",
    "Companheiro(a)",
    "Filho(a)",
    "Amigo(a)",
    "Primo(a)",
    "Tio(a)",
    "Sobrinho(a)",
    "Avô/Avó",
    "Cunhado(a)",
    "Sogro(a)",
    "Outro",
]

SISTEMA_PARENTESCO = f"""Você classifica o parentesco de quem busca informação sobre uma pessoa presa, na Defensoria Pública do RJ, a partir de um relato livre.
Parentescos possíveis: {", ".join(PARENTESCOS_PERMITIDOS)}.
Regras: escolha o que melhor descreve a relação, mesmo que o relato seja indireto (ex: "fui casada com ele mas já nos divorciamos" → "Ex-esposo(a)"). Se não bater com confiança em nenhum, responda "nenhum"."""  # noqa: E501


@pytest.mark.parametrize(
    ("relato", "esperado"),
    [
        ("Fui casada por dez anos mas já nos divorciamos", "Ex-esposo(a)"),  # issue #17, exemplo 1
        ("Conheço ele desde criança e sempre fomos vizinhos", "Amigo(a)"),  # issue #17, exemplo 2
        ("amigo", "Amigo(a)"),  # resposta já é valor direto da lista
    ],
)
async def test_parentesco_issue_17(relato: str, esperado: str) -> None:
    resultado = await classificar_entre_opcoes(relato, SISTEMA_PARENTESCO, PARENTESCOS_PERMITIDOS)
    assert resultado["viaIA"] is True
    assert resultado.get("escolhaId") == esperado


async def test_parentesco_sem_match_claro_termina_em_outro() -> None:
    resultado = await classificar_entre_opcoes("gosto de pizza aos domingos", SISTEMA_PARENTESCO, PARENTESCOS_PERMITIDOS)
    assert resultado["viaIA"] is True
    # "Outro" é candidato da lista; classificarParentesco trata "Outro" e
    # "nenhum" (None) igual.
    assert (resultado.get("escolhaId") or "Outro") == "Outro"


# ---- reescrever.test.ts -------------------------------------------------------------


async def test_reescrever_chama_o_bedrock_de_verdade() -> None:
    resultado = await reescrever_pergunta("parentesco", "Qual seu parentesco com a pessoa presa?")
    assert resultado["viaIA"] is True
    texto = resultado.get("texto")
    assert isinstance(texto, str) and len(texto) > 0
    _tokens_positivos(dict(resultado))


async def test_preparar_pergunta_repassa_tokens_gastos() -> None:
    preparado = await preparar_pergunta("parentesco", "Qual seu parentesco com a pessoa presa?")
    assert preparado["perguntaAtualViaIA"] is True
    gastos = preparado["tokensGastos"]
    assert gastos["total"] > 0 and gastos["input"] > 0 and gastos["output"] > 0
    assert gastos["input"] + gastos["output"] == gastos["total"]


# ---- sumarizar.test.ts --------------------------------------------------------------

# Issue #70: relato longo e redundante de propósito, para qualquer resumo
# razoável ser menor.
RELATO = """Meu marido foi preso semana passada, ainda não sei direito o número do processo, não anotei na hora porque estava muito nervosa e não consegui prestar atenção em tudo que os policiais falaram naquele momento.
A gente mora junto tem 8 anos, não somos casados no papel, nunca fizemos questão de casar oficialmente porque nunca vimos necessidade, mas moramos juntos como se fôssemos casados mesmo, dividindo tudo, contas, aluguel, essas coisas do dia a dia.
Ele tá numa unidade em Bangu, falaram que era condenado mas eu não entendi direito a situação, ficou tudo muito confuso na hora, com muita gente falando ao mesmo tempo e eu tentando entender o que estava acontecendo.
Queria saber como acompanhar isso e se posso visitar ele, porque nunca passei por uma situação assim antes e não sei nem por onde começar, se preciso de algum documento, se preciso agendar visita com antecedência.
Também queria saber se existe algum auxílio pra quem fica sem o marido trabalhando em casa, porque ele que ajudava com as contas e agora não sei como vou me virar sozinha com as despesas da casa.
Alguém falou que existe um benefício pra família de pessoa presa mas não sei se é verdade nem como funciona, se precisa de advogado ou se dá pra resolver direto com a defensoria mesmo."""  # noqa: E501


async def test_sumarizar_devolve_resumo_menor_e_tokens() -> None:
    resultado = await sumarizar_relato(RELATO)
    assert resultado["viaIA"] is True
    resumo = resultado.get("resumo")
    assert isinstance(resumo, str) and 0 < len(resumo) < len(RELATO)
    _tokens_positivos(dict(resultado))
