"""Classificação por necessidades do multi-fluxo (#435) com a IA de verdade e o catálogo do release.

Chama o Bedrock DE VERDADE (custa dinheiro e precisa de credencial AWS válida): fica fora da suíte
padrão e do CI pelo marcador `integracao`. Rodar à mão, com o custo aprovado antes:

    uv run pytest -m integracao tests/integracao/ia/test_classificacao_necessidades.py -s

Medido em 2026-11-06 com `count_tokens`: 33 chamadas, de 3.323 a 3.346 tokens de entrada cada.

Duas partes:
- os 22 cenários da #386 (`test_classificacao_plano_saude.py`), agora pelo caminho do release:
  o destino de um relato de um assunto só não pode mudar com a classificação nova. Isso inclui a
  escolha direta da #419 ("preciso de uma cirurgia" vai para o plano);
- relatos com dois assuntos, informais e com erros de digitação, como a Nicole escreveu no teste
  do protótipo em 06/11 (`migracao-specs/multi-fluxo/relatos-por-partes-e-digitacao.md`).
"""

from __future__ import annotations

import pytest

from maria.fluxos import ID_PESSOA_PRESA, ID_PROBLEMAS_PLANO_SAUDE, ID_VIOLENCIA_DOMESTICA, catalogo_para_classificacao
from maria.ia import classificar_necessidades as cn
from maria.ia._estruturado import criar_modelo
from maria.orquestrador.fila import montar_fila
from maria.orquestrador.graph import CANDIDATOS_MAXIMOS, resolver_escolha_direta
from maria.shared.embeddings_fluxos import buscar_candidatos
from tests.integracao.ia.test_classificacao_plano_saude import CASOS, MODELO_DO_TESTE

pytestmark = pytest.mark.integracao

PP, VD, PLANO, SAUDE = ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, ID_PROBLEMAS_PLANO_SAUDE, "tykhe:saude"
NOVO = "tykhe:novo-processo"

# (cenário, relato, assuntos da fila). Fila de 1 assunto = segue direto, como hoje.
MULTI: list[tuple[str, str, set[str]]] = [
    ("M1-pp-plano", "meu irmao ta preso e o plano da minha mae n quer libera a cirurgia dela", {PP, PLANO}),
    ("M2-vd-pp-agora", "meu marido me bate qnd bebe e meu filho rodou ontem a noite", {VD, PP}),
    ("M4-pp-posto", "mu imao ta preso la em bangu e o posto n marca o exame da minha vo faz 3 mes", {PP, SAUDE}),
    # Só cita que o marido está preso, sem pedir nada sobre ele: pela regra de 28/10, a prisão é contexto (como no M11).
    ("M5-pp-tratamento", "ow meu marido ta na cana e o convenio cortou o tratamento do meu filho", {SAUDE}),
    ("M6-vd-pensao", "preciso de ajuda pq meu ex me ameaçou e tb ele n paga a pensao das crianças", {VD, NOVO}),
    ("M7-uti-pp-agora", "minha mae ta internada e o hospital do sus n tem vaga na uti e meu filho foi preso agr de manha", {SAUDE, PP}),
    ("M8-pp-plano", "meu irmao ta preso faz 2 anos e o plano da minha mae negou a cirurgia", {PP, PLANO}),
    # Prótese sem falar de cirurgia é fronteira do escopo da #386 (a prótese pode ser da cirurgia): nas rodadas
    # de 06/11, a IA mandou uma vez para a saúde da Tykhe e uma vez para o plano. Os dois valem.
    ("M9-pp-protese", "meu filho ta preso em bangu e a amil n quer pagar a protese do meu pai", {PP, SAUDE, PLANO}),
    ("M10-um-so", "meu filho foi pres semana passada", {PP}),
    # Decisão de 28/10: a prisão só como contexto de outro pedido não é pedido sobre pessoa presa.
    ("M11-prisao-contexto", "meu marido ta preso e eu quero me divorciar dele", {NOVO}),
]


@pytest.fixture(autouse=True)
def _release_com_o_modelo_da_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("MARIA_AMBIENTE", "release")
    monkeypatch.delenv("ORQUESTRADOR_INCLUIR_PLANEJADOS", raising=False)
    monkeypatch.setenv("BEDROCK_MODEL_ID", MODELO_DO_TESTE)
    monkeypatch.setattr(cn, "modelo", criar_modelo())


async def _classificar(relato: str) -> cn.ResultadoNecessidades:
    catalogo = await catalogo_para_classificacao()
    pool = await buscar_candidatos(relato, CANDIDATOS_MAXIMOS, catalogo)
    resultado = await cn.classificar_necessidades(relato, pool)
    print(f"\n[tokens] entrada={resultado.get('tokensEntrada')} saida={resultado.get('tokensSaida')}")
    assert resultado["viaIA"] is True, "a resposta tem de vir da IA, não do modo de teste"
    return resultado


async def _destino(resultado: cn.ResultadoNecessidades) -> str:
    """O que o orquestrador faria na 1ª rodada (`_classificar_por_necessidades` e `depois_de_classificar`)."""
    fila = montar_fila(resultado["necessidades"])
    if len(fila) >= 2:
        return "fila"
    por_id = {c["id"]: c for c in await catalogo_para_classificacao()}
    ids = resultado["idsEmAmbiguidade"] if len(resultado["idsEmAmbiguidade"]) >= 2 else [i["id"] for i in fila]
    candidatos = resolver_escolha_direta([por_id[i] for i in ids if i in por_id])
    if len(candidatos) == 1:
        return candidatos[0]["id"]
    return "desambiguacao" if candidatos else "nenhum"


@pytest.mark.parametrize(("cenario", "relato", "precisa", "nao_pode", "so"), CASOS, ids=[c[0] for c in CASOS])
async def test_386_o_destino_de_um_assunto_so_nao_muda(cenario: str, relato: str, precisa: set[str], nao_pode: set[str], so: bool) -> None:
    resultado = await _classificar(relato)
    destino = await _destino(resultado)
    ids = [n["id"] for n in resultado["necessidades"]]
    print(f"\n[{cenario}] destino={destino} necessidades={ids} duvida={resultado['idsEmAmbiguidade']}")
    if cenario.startswith("H4"):
        # #419: a dúvida entre o plano e a saúde da Tykhe vai direto para o plano.
        assert destino in (PLANO, "desambiguacao"), f"H4 foi para {destino}"
    elif cenario.startswith("plano-fora-internacao"):
        # Risco aceito na #419: internação negada pelo plano pode ir para o fluxo do plano.
        assert destino in (SAUDE, PLANO), f"internação foi para {destino}"
    elif so:
        assert destino == next(iter(precisa)), f"esperado {precisa}, foi para {destino}"
    else:
        assert destino not in nao_pode, f"não podia ir para {destino}"


@pytest.mark.parametrize(("cenario", "relato", "esperado"), MULTI, ids=[c[0] for c in MULTI])
async def test_multi_fluxo_acha_os_assuntos(cenario: str, relato: str, esperado: set[str]) -> None:
    resultado = await _classificar(relato)
    fila = montar_fila(resultado["necessidades"])
    print(f"\n[{cenario}] fila={[(i['id'], i['evidencia'], i['urgente']) for i in fila]} duvida={resultado['idsEmAmbiguidade']}")
    achados = {i["id"] for i in fila}
    if cenario.startswith("M9"):
        # Fronteira: a pessoa presa e um dos dois assuntos de saúde.
        assert PP in achados and len(achados) == 2 and achados <= esperado
    else:
        assert achados == esperado
    for item in fila:
        assert item["evidencia"], "cada assunto precisa do trecho do relato"
