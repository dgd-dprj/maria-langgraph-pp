"""Casos que saíram da conferência contra as fixtures de contrato (#321).

As fixtures (`tests/fixtures/contrato/`) são respostas gravadas da versão TypeScript e nunca são
editadas (decisão C7, `MIGRACAO.md`, "As respostas gravadas são evidência, não teste de regressão").
Quando uma mudança legítima muda o valor de uma resposta gravada (o primeiro caso à vista é um
fluxo novo mudando `GET /fluxos`), o caso sai da conferência, e o comportamento novo ganha um teste
escrito. Campo novo e opcional não é caso aposentado: é `campos_posteriores.py` (#294).

O caso aposentado continua sendo enviado, na mesma ordem, porque os seguintes podem depender do
estado que ele deixa; só a comparação dele sai. Se ele voltar a bater com a gravação, a conferência
falha, para a entrada não ficar esquecida aqui.

Para aposentar um caso: uma entrada em `CASOS_APOSENTADOS[<conferência>]`, com o nome exato do caso,
a issue, o motivo e o teste escrito que cobre o comportamento novo (`test_casos_aposentados.py`
confere o registro).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

RAIZ_FIXTURES = Path("tests/fixtures/contrato")


@dataclass(frozen=True)
class CasoAposentado:
    issue: int
    motivo: str
    teste: str  # caminho a partir da raiz do repositório
    # Aposenta só o corpo: o status continua conferido contra a gravação (#210, #211). Uma mudança que levasse o caso a
    # outro status (um 422, um 500) continua sendo pega pela conferência.
    mantem_status: bool = False


# A falha de status que as conferências registram à parte, para valer mesmo num caso aposentado com `mantem_status`.
PREFIXO_STATUS = "[status] "


# Conferência -> (arquivo de teste dela, nomes dos casos que ela percorre).
def _nomes_contrato() -> list[str]:
    return [i["nome"] for i in json.loads((RAIZ_FIXTURES / "indice.json").read_text(encoding="utf-8"))]


def _nomes_cenarios(pasta: str) -> list[str]:
    return [c["nome"] for c in json.loads((RAIZ_FIXTURES / pasta / "cenarios.json").read_text(encoding="utf-8"))]


CONFERENCIAS: dict[str, str] = {
    "contrato": "tests/api/test_contrato.py",
    "pr1": "tests/api/test_conferencia_pr1.py",
    "pr2": "tests/api/test_conferencia_pr2.py",
}


def nomes_dos_casos(conferencia: str) -> list[str]:
    if conferencia == "contrato":
        return _nomes_contrato()
    return _nomes_cenarios({"pr1": "conferencia-api-pr1", "pr2": "conferencia-api-pr2"}[conferencia])


# As três conferências rodam com o ambiente da produção (#324): as gravações são o contrato com a
# Tykhe, e é na produção que ele vale. Um teste (`test_fluxo_em_teste.py`) exige que este valor seja
# o mesmo que `infra/terraform/ecs.tf` declara. O que só muda no release, onde os fluxos em teste
# ligam, é coberto por testes escritos, e não pelas gravações.
AMBIENTE_DAS_CONFERENCIAS = "producao"

# #551 (2026-11-25): a confirmação do RG voltou a mostrar o nome completo da pessoa presa; os 4 casos que a #393
# aposentou (pessoa-presa-resposta-rg-200, pessoa-presa-get-metadados-parciais-200, pp_rg, pp_get_confirma_nome)
# voltam a bater com as gravações e saíram daqui.

# Histórico dos casos de `GET /fluxos`: a #329 aposentou 6 (contrato `fluxos-200`; pr1 `fluxos`,
# `fluxos_query`, `auth_bearer_espacos_fluxos`, `auth_bearer_duplo_espaco_fluxos`; pr2
# `rota_get_fluxos_codificado`) quando o fluxo do plano de saúde entrou na lista. Com ele em teste,
# desligado na produção (#324), os 6 voltaram a bater com as gravações e saíram daqui (registro no
# `MIGRACAO.md`). As gravações não foram editadas.
# #475 (decisão da Nicole, 2026-11-12): a pergunta do RG mostra os formatos aceitos.
_PERGUNTA_DO_RG = CasoAposentado(issue=475, motivo="a pergunta do RG mostra os formatos aceitos", teste="tests/fluxos/test_pessoa_presa.py")
_IRMAO_E_IRMA = CasoAposentado(issue=212, motivo="o parentesco Irmão(a) virou Irmão e Irmã", teste="tests/shared/test_parentesco.py")
# #497 (decisão da Nicole, 2026-11-16): o CPF digitado na conversa passa pela conta dos dígitos verificadores antes do
# Verde. O CPF da gravação ("11111111111") não fecha a conta: a conversa pede o CPF de novo e não conclui, e as consultas
# seguintes à mesma conversa mudam junto.
_CPF_PELA_CONTA = CasoAposentado(
    issue=497, motivo="o CPF da gravação não fecha a conta dos dígitos verificadores", teste="tests/subgrafos/test_subgrafos.py"
)

# #296: `dadosConhecidos.cpf` numérico vira texto de 11 dígitos e outro tipo é 400 com motivo; na gravação, o 200 sumia com o campo.
_CPF_NUMERICO = CasoAposentado(
    issue=296, motivo="cpf de dadosConhecidos que não é texto: número vira texto, outro tipo é 400", teste="tests/api/test_cpf_conhecido.py"
)
_CASOS_CPF_NUMERICO = (
    "dados_cpf_zero",
    "dados_cpf_sete",
    "dados_cpf_true",
    "dados_cpf_false",
    "dados_cpf_objeto",
    "dados_cpf_lista",
    "dados_cpf_lista1",
    "dados_cpf_lista2",
    "dados_cpf_float_pequeno",
    "dados_cpf_inteiro_grande",
    "dados_cpf_float",
    "dados_cpf_objeto_cheio",
)

# #240 (decisão da Nicole, 2026-11-17): campo interno dos fluxos em `dadosConhecidos` é descartado. A gravação provocava
# o erro não tratado com `dadosConhecidos.tokensGastos: null`; agora o campo sai, e a criação segue com 200. O formato do
# 500, que mudou com a #210, é conferido em `tests/api/test_erros_api.py`.
_CAMPO_INTERNO = CasoAposentado(
    issue=240,
    motivo="tokensGastos de fora é campo interno e é descartado; a criação não quebra mais",
    teste="tests/api/test_dados_conhecidos_internos.py",
)

# #210 e #211 (decisão da Nicole, 2026-11-18, um PR só): os erros da API mudaram de corpo, com o mesmo status.
# - O 400 de validação e de leitura do corpo, nas rotas que declaram o 400, trazia `{}`; agora traz `{"erro": <motivo>}`.
#   Todo 400 gravado com `{}` é um desses (os 400 de negócio já vinham com `erro`), e por isso eles saem por regra.
# - O 500 trazia o texto da exceção em `message`; agora traz um texto fixo e o `reqId`. Os 500 gravados saem pelo nome:
#   todos continuavam respondendo 500 quando foram aposentados, só o corpo mudou. Ficam de fora os 500 de HEAD, que não
#   têm corpo e continuam iguais à gravação, e os dois 500 de `tokensGastos` da PR1, que a #240 já trata à parte (200).
#   Nos dois, só o corpo sai da conferência: o status continua conferido (`mantem_status`).
_ERRO_400_COM_MOTIVO = CasoAposentado(
    issue=211,
    motivo="o 400 de validação e de leitura do corpo traz o motivo em português, em vez de {}",
    teste="tests/api/test_erros_api.py",
    mantem_status=True,
)
_ERRO_500_SEM_EXCECAO = CasoAposentado(
    issue=210,
    motivo="o 500 traz um texto fixo e o reqId, em vez do texto da exceção",
    teste="tests/api/test_erros_api.py",
    mantem_status=True,
)
_CASOS_500: dict[str, tuple[str, ...]] = {
    "contrato": (
        "erro-nao-tratado-webhook-challenge-repetido-500",
        "erro-nao-tratado-webhook-mensagem-null-500",
        "erro-nao-tratado-webhook-texto-numero-500",
    ),
    "pr1": (),
    "pr2": ("wh_get_challenge_repetido", "wh_post_item_null", "wh_post_numero_texto_numero"),
}


def _respostas_gravadas(conferencia: str) -> list[tuple[str, int, str]]:
    """Nome, status e corpo de cada resposta gravada da conferência."""
    if conferencia == "contrato":
        saida = []
        for nome in _nomes_contrato():
            resposta = json.loads((RAIZ_FIXTURES / "http" / f"{nome}.json").read_text(encoding="utf-8"))["resposta"]
            saida.append((nome, resposta["status"], resposta["corpoBruto"]))
        return saida
    pasta = {"pr1": "conferencia-api-pr1", "pr2": "conferencia-api-pr2"}[conferencia]
    gravadas = json.loads((RAIZ_FIXTURES / pasta / "develop.json").read_text(encoding="utf-8"))
    return [(g["nome"], g["status"], g["corpo"]) for g in gravadas]


def casos_dos_erros_da_api(conferencia: str) -> dict[str, CasoAposentado]:
    """#210 e #211: os casos gravados com 400 `{}` (por regra) e os 500 (pelo nome)."""
    casos = {nome: _ERRO_400_COM_MOTIVO for nome, status, corpo in _respostas_gravadas(conferencia) if status == 400 and corpo == "{}"}
    casos.update(dict.fromkeys(_CASOS_500[conferencia], _ERRO_500_SEM_EXCECAO))
    return casos


CASOS_APOSENTADOS: dict[str, dict[str, CasoAposentado]] = {
    "contrato": {
        **casos_dos_erros_da_api("contrato"),
        "erro-nao-tratado-500": _CAMPO_INTERNO,
        "pessoa-presa-resposta-texto-sem-opcoes-200": _PERGUNTA_DO_RG,
    },
    "pr1": {
        **casos_dos_erros_da_api("pr1"),
        **{nome: _CPF_NUMERICO for nome in _CASOS_CPF_NUMERICO},
        # #240: develop devolvia em `metadados` o `encaminhamentoId` pré-preenchido; agora ele é descartado na entrada.
        # O `null` fica fora: a gravação já não o mostrava, e a resposta continua igual.
        **{
            nome: _CAMPO_INTERNO
            for nome in nomes_dos_casos("pr1")
            if nome.startswith("dados_encaminhamentoId_") and nome != "dados_encaminhamentoId_null"
        },
    },
    "pr2": {
        **casos_dos_erros_da_api("pr2"),
        # #394 (decisão da Nicole, 2026-11-12): a recusa do RG pelo formato diz a tentativa e dá um exemplo.
        "pp_rg_invalido": CasoAposentado(
            issue=394, motivo="a mensagem de recusa do RG pelo formato mudou", teste="tests/fluxos/test_pessoa_presa.py"
        ),
        "pp_sem_processo": _PERGUNTA_DO_RG,
        "orq_identifica_responde": _PERGUNTA_DO_RG,
        # #212 (decisão da Nicole, 2026-11-13): "Irmão(a)" virou "Irmão" e "Irmã"; a resposta "irmão" grava "Irmão".
        "pp_parentesco": _IRMAO_E_IRMA,
        "pp_get_concluido": _IRMAO_E_IRMA,
        # #393, item 3 (decisão da Nicole, 2026-11-17): o município do órgão saiu da mensagem final da violência doméstica.
        "vd_via_orq_3": CasoAposentado(
            issue=393,
            motivo="o município do órgão saiu da mensagem final da violência doméstica",
            teste="tests/fluxos/test_mensagem_sem_municipio.py",
        ),
        "vd_cpf": _CPF_PELA_CONTA,
        "vd_get_concluido": _CPF_PELA_CONTA,
        "vd_409_concluido": _CPF_PELA_CONTA,
        "rota_get_query": _CPF_PELA_CONTA,
        "rota_get_escape_invalido_query": _CPF_PELA_CONTA,
    },
}


def falhas_que_valem(nome: str, falhas_do_caso: list[str], aposentados: Mapping[str, CasoAposentado]) -> list[str]:
    """As falhas de um caso que contam na conferência.

    Caso fora da lista: as próprias falhas. Caso aposentado: nenhuma, a não ser que ele tenha
    voltado a bater com a gravação, o que vira falha de entrada esquecida. Caso aposentado só no
    corpo (`mantem_status`): as falhas de status (`PREFIXO_STATUS`) continuam valendo."""
    caso = aposentados.get(nome)
    if caso is None:
        return falhas_do_caso
    if not falhas_do_caso:
        return [f"{nome}: aposentado (#{caso.issue}), mas voltou a bater com a gravação; tire a entrada de casos_aposentados.py"]
    if caso.mantem_status:
        return [f for f in falhas_do_caso if f.startswith(PREFIXO_STATUS)]
    return []


def falhas_da_conferencia(por_caso: Mapping[str, list[str]], aposentados: Mapping[str, CasoAposentado]) -> list[str]:
    """Junta as falhas de cada caso da conferência, aplicando a lista de aposentados."""
    return [f for nome, falhas in por_caso.items() for f in falhas_que_valem(nome, falhas, aposentados)]


def problemas_do_registro(registro: Mapping[str, Mapping[str, CasoAposentado]]) -> list[str]:
    """O que está errado no registro: conferência ou caso inexistente, teste que não existe ou não
    cita o caso nem a issue, motivo ou issue vazios."""
    problemas: list[str] = []
    for conferencia, casos in registro.items():
        if conferencia not in CONFERENCIAS:
            problemas.append(f"conferência inexistente: {conferencia}")
            continue
        existentes = set(nomes_dos_casos(conferencia))
        for nome, caso in casos.items():
            onde = f"{conferencia}/{nome}"
            if nome not in existentes:
                problemas.append(f"{onde}: o caso não existe nessa conferência")
            if caso.issue <= 0 or not caso.motivo.strip():
                problemas.append(f"{onde}: issue e motivo são obrigatórios")
            arquivo = Path(caso.teste)
            if not arquivo.name.startswith("test_") or not arquivo.is_file():
                problemas.append(f"{onde}: o teste {caso.teste} não existe")
            elif nome not in (texto := arquivo.read_text(encoding="utf-8")) and f"#{caso.issue}" not in texto:
                problemas.append(f"{onde}: o teste {caso.teste} não cita o caso nem a #{caso.issue}")
    return problemas
