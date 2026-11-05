"""Cenários H1 a H6 da #386 com a IA de verdade e o catálogo do release.

Chama o Bedrock DE VERDADE (custa dinheiro e precisa de credencial AWS válida): fica fora da
suíte padrão e do CI pelo marcador `integracao`. Rodar à mão, com o custo aprovado antes:

    uv run pytest -m integracao tests/integracao/ia/test_classificacao_plano_saude.py -s

Reproduz a 1ª rodada do orquestrador: o catálogo do release (`MARIA_AMBIENTE=release`), o corte
de candidatos (`buscar_candidatos`, que com até 15 opções devolve o catálogo inteiro sem gastar
embedding) e a classificação, com o modelo da produção (`infra/terraform/ecs.tf`).

Os relatos são inventados, com versões informais e erros de escrita de propósito. Reajuste e
cancelamento ainda dependem do NUDECON (#386), por isso não entram aqui como esperados.
"""

from __future__ import annotations

import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA, catalogo_para_classificacao
from maria.ia import classificar
from maria.ia._estruturado import criar_modelo
from maria.ia.classificar_fluxos import classificar_fluxos_plausiveis
from maria.orquestrador.graph import CANDIDATOS_MAXIMOS
from maria.shared.embeddings_fluxos import buscar_candidatos

pytestmark = pytest.mark.integracao

MODELO_DE_PRODUCAO = "us.anthropic.claude-haiku-4-5-20251001-v1:0"  # infra/terraform/ecs.tf
PLANO = ID_PROBLEMAS_PLANO_SAUDE
SAUDE = "tykhe:saude"

# (cenário, relato, ids que precisam estar, ids que não podem estar, "só" = exatamente os de cima)
CASOS: list[tuple[str, str, set[str], set[str], bool]] = [
    # H1 e H2: negativa do plano vai para o fluxo, sem a saúde pública junto.
    ("H1", "meu plano de saúde negou minha cirurgia", {PLANO}, {SAUDE}, True),
    ("H1-informal", "o plano nao quis libera minha cirurgia do joelho", {PLANO}, {SAUDE}, True),
    ("H1-marca", "a amil negou o tratamento de quimio da minha mae", {PLANO}, {SAUDE}, True),
    ("H2", "o convênio não quer reembolsar o exame", {PLANO}, {SAUDE}, True),
    ("H2-informal", "a unimed nao qer devolver o dinheiro da consulta q eu paguei", {PLANO}, {SAUDE}, True),
    ("H2-exame", "meu convenio recusou a ressonancia q o medico pediu", {PLANO}, {SAUDE}, True),
    # H3: saúde pública continua com a Tykhe, sem o plano junto.
    ("H3", "preciso de um remédio que o posto não tem", {SAUDE}, {PLANO}, True),
    ("H3-posto", "o posto não marca minha cirurgia", {SAUDE}, {PLANO}, True),
    ("H3-vaga", "to esperando vaga no sus pra internar minha mae faz 2 semana", {SAUDE}, {PLANO}, True),
    ("H3-farmacia", "a farmacia popular nao tem o remedio da pressao", {SAUDE}, {PLANO}, True),
    # H4: ambíguo, os dois entram e o orquestrador pergunta antes de escolher.
    ("H4", "preciso de uma cirurgia", {PLANO, SAUDE}, set(), False),
    ("H4-informal", "minha mae precisa operar o joelho urgente", {PLANO, SAUDE}, set(), False),
    # Consumidor em geral: não é plano de saúde.
    ("consumidor", "comprei uma geladeira com defeito e a loja nao quer trocar", set(), {PLANO, SAUDE}, False),
    # H6: com o plano no catálogo, os outros fluxos continuam escolhidos sozinhos.
    ("H6-pessoa-presa", "meu filho foi preso semana passada e quero saber do processo dele", {ID_PESSOA_PRESA}, {PLANO}, True),
    ("H6-violencia", "meu marido me bateu de novo e eu tenho medo dele", {ID_VIOLENCIA_DOMESTICA}, {PLANO}, True),
]


@pytest.fixture(autouse=True)
def _release_com_o_modelo_da_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    monkeypatch.delenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", raising=False)
    monkeypatch.setenv("BEDROCK_MODEL_ID", MODELO_DE_PRODUCAO)
    # O modelo é criado na importação do módulo: troca pelo da produção, qualquer que seja o .env.
    monkeypatch.setattr(classificar, "modelo", criar_modelo())


@pytest.mark.parametrize(("cenario", "relato", "precisa", "nao_pode", "so"), CASOS, ids=[c[0] for c in CASOS])
async def test_classificacao_plano_de_saude(cenario: str, relato: str, precisa: set[str], nao_pode: set[str], so: bool) -> None:
    catalogo = await catalogo_para_classificacao()
    assert PLANO in [o["id"] for o in catalogo], "o catálogo do release precisa ter o plano de saúde"
    pool = await buscar_candidatos(relato, CANDIDATOS_MAXIMOS, catalogo)
    resultado = await classificar_fluxos_plausiveis(relato, pool)
    ids = set(resultado.get("ids") or [])
    print(f"\n[{cenario}] {sorted(ids)} tokens={resultado.get('tokensTotal')}")
    assert resultado.get("viaIA") is True, "a resposta tem de vir da IA, não do modo de teste"
    assert precisa <= ids, f"faltou {sorted(precisa - ids)}"
    assert not (nao_pode & ids), f"não podia ter {sorted(nao_pode & ids)}"
    if so:
        assert ids == precisa, f"esperado só {sorted(precisa)}"
