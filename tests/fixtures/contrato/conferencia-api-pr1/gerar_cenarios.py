# mypy: ignore-errors
# ruff: noqa
# Script de captura (não é teste nem código da aplicação), guardado para regravar a conferência.
"""Cenários da conferência diferencial do PR 1 do api (rotas /health, /fluxos,
POST /atendimentos, POST /atendimentos/orquestrador), por HTTP.

Cada cenário é uma requisição crua: método, caminho, cabeçalhos, corpo como texto
(para mandar bytes exatos: inteiro grande, BOM, JSON inválido) e ambiente
(APP_ENV/NODE_ENV e mocks). Os dois lados rodam a lista na mesma ordem, numa
única aplicação, e o estado que um cenário deixa vale para os seguintes.
"""

import json
import sys

PP = "3df874f2-675a-4c43-9ec7-480f7c702f50"
VD = "cabb2495-4e12-4f4a-9956-3d20649059bc"
AUTH = {"authorization": "Bearer chave-conferencia"}
JSON_H = {**AUTH, "content-type": "application/json"}
AUS = object()
VALORES = {
    "null": None,
    "texto": "x",
    "zero": 0,
    "sete": 7,
    "true": True,
    "false": False,
    "objeto": {},
    "lista": [],
    "vazio": "",
    "ausente": AUS,
    "lista1": ["y"],
    "lista2": ["a", "b"],
    "float_pequeno": "RAW:1e-7",
    "inteiro_grande": "RAW:12345678901234567890",
    "float": 1.5,
    "objeto_cheio": {"a": 1},
}

cenarios: list[dict] = []
n = 0


def corpo_texto(campos: dict) -> str:
    partes = []
    for k, v in campos.items():
        if v is AUS:
            continue
        if isinstance(v, str) and v.startswith("RAW:"):
            partes.append(f"{json.dumps(k)}:{v[4:]}")
        else:
            partes.append(f"{json.dumps(k)}:{json.dumps(v, ensure_ascii=False)}")
    return "{" + ",".join(partes) + "}"


def cen(nome, metodo, caminho, headers=None, corpo=None, env=None, bloco="principal"):
    cenarios.append(
        {"nome": nome, "bloco": bloco, "metodo": metodo, "caminho": caminho, "headers": headers or {}, "corpo": corpo, "env": env or {}}
    )


def chat():
    global n
    n += 1
    return f"conf-api-{n}"


# ---- caminhos principais ------------------------------------------------------------
cen("health", "GET", "/health")
cen("health_head", "HEAD", "/health")
cen("fluxos", "GET", "/fluxos", AUTH)
cen("fluxos_head", "HEAD", "/fluxos", AUTH)
cen("fluxos_query", "GET", "/fluxos?a=1", AUTH)
cen("rota_inexistente", "GET", "/nao-existe", AUTH)
cen("rota_inexistente_query", "GET", "/nao-existe?x=1&y=2", AUTH)
cen("barra_final", "GET", "/fluxos/", AUTH)
cen("dupla_barra", "GET", "//health")
cen("metodo_errado", "GET", "/atendimentos", AUTH)
cen("options", "OPTIONS", "/health")
cen("post_health", "POST", "/health")
for nome, h in [
    ("sem", {}),
    ("sem_bearer", {"authorization": "chave-conferencia"}),
    ("bearer_minusculo", {"authorization": "bearer chave-conferencia"}),
    ("bearer_vazio", {"authorization": "Bearer "}),
    ("bearer_espacos", {"authorization": "Bearer   chave-conferencia  "}),
    ("chave_errada", {"authorization": "Bearer errada"}),
    ("bearer_duplo_espaco", {"authorization": "Bearer  chave-conferencia"}),
]:
    cen(f"auth_{nome}_fluxos", "GET", "/fluxos", h)
    cen(
        f"auth_{nome}_atendimentos",
        "POST",
        "/atendimentos",
        {**h, "content-type": "application/json"},
        corpo_texto({"chatId": chat(), "flowId": VD}),
    )
cen("sem_auth_e_json_invalido", "POST", "/atendimentos", {"content-type": "application/json"}, "{x")
cen("criar_vd", "POST", "/atendimentos", JSON_H, corpo_texto({"chatId": "conf-vd", "flowId": VD}))
cen("criar_vd_repetido", "POST", "/atendimentos", JSON_H, corpo_texto({"chatId": "conf-vd", "flowId": VD}))
cen("criar_pp_mesmo_chat", "POST", "/atendimentos", JSON_H, corpo_texto({"chatId": "conf-vd", "flowId": PP}))
cen("criar_pp", "POST", "/atendimentos", JSON_H, corpo_texto({"chatId": "conf-pp", "flowId": PP}))
cen(
    "criar_flowid_inexistente",
    "POST",
    "/atendimentos",
    JSON_H,
    corpo_texto({"chatId": chat(), "flowId": "00000000-0000-4000-8000-000000000000"}),
)
cen("criar_flowid_maiusculo", "POST", "/atendimentos", JSON_H, corpo_texto({"chatId": chat(), "flowId": VD.upper()}))
cen("criar_flowid_urn", "POST", "/atendimentos", JSON_H, corpo_texto({"chatId": chat(), "flowId": "urn:uuid:" + VD}))
cen("criar_sem_chatid_development", "POST", "/atendimentos", JSON_H, corpo_texto({"flowId": VD}), {"APP_ENV": "development"})
cen(
    "criar_chatid_vazio_development", "POST", "/atendimentos", JSON_H, corpo_texto({"chatId": "", "flowId": VD}), {"APP_ENV": "development"}
)
cen("orq_sem_chatid_development", "POST", "/atendimentos/orquestrador", JSON_H, corpo_texto({"mensagem": "oi"}), {"APP_ENV": "development"})
cen(
    "criar_vd_cpf",
    "POST",
    "/atendimentos",
    JSON_H,
    corpo_texto({"chatId": chat(), "flowId": VD, "dadosConhecidos": {"cpf": "12345678901", "viaOrquestrador": True}}),
)
cen(
    "criar_tokens_null_500",
    "POST",
    "/atendimentos",
    JSON_H,
    corpo_texto({"chatId": chat(), "flowId": VD, "dadosConhecidos": {"tokensGastos": None}}),
)
# orquestrador
M_PP = {"MOCK_CLASSIFICACAO_FLOWID": PP}
M_AMB = {"MOCK_CLASSIFICACAO_FLOWIDS": f"{PP},{VD}"}
cen(
    "orq_identificado",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto({"chatId": "conf-orq-1", "mensagem": "meu filho está preso"}),
    M_PP,
)
cen(
    "orq_identificado_repetido",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto({"chatId": "conf-orq-1", "mensagem": "de novo"}),
    M_PP,
)
cen("orq_nao_identificado", "POST", "/atendimentos/orquestrador", JSON_H, corpo_texto({"chatId": chat(), "mensagem": "texto"}))
cen(
    "orq_tykhe_saude",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto({"chatId": chat(), "mensagem": "remédio"}),
    {"MOCK_CLASSIFICACAO_FLOWID": "tykhe:saude"},
)
cen(
    "orq_tykhe_sair",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto({"chatId": chat(), "mensagem": "tchau"}),
    {"MOCK_CLASSIFICACAO_FLOWID": "tykhe:sair"},
)
cen("orq_amb_1", "POST", "/atendimentos/orquestrador", JSON_H, corpo_texto({"chatId": "conf-amb", "mensagem": "ambíguo"}), M_AMB)
cen("orq_amb_2", "POST", "/atendimentos/orquestrador", JSON_H, corpo_texto({"chatId": "conf-amb", "resposta": "r1"}), M_AMB)
cen("orq_amb_resolve", "POST", "/atendimentos/orquestrador", JSON_H, corpo_texto({"chatId": "conf-amb", "resposta": "presa"}), M_PP)
cen(
    "orq_amb_depois_de_resolvido",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto({"chatId": "conf-amb", "resposta": "mais"}),
    M_PP,
)
cen("orq_resposta_sem_conversa", "POST", "/atendimentos/orquestrador", JSON_H, corpo_texto({"chatId": chat(), "resposta": "oi"}), M_PP)
cen(
    "orq_mensagem_e_resposta",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto({"chatId": chat(), "mensagem": "a", "resposta": "b"}),
    M_PP,
)
cen(
    "orq_mesmo_chat_de_outro_fluxo",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto({"chatId": "conf-vd", "mensagem": "presa"}),
    M_PP,
)
cen(
    "orq_dados_conhecidos_cpf",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto(
        {"chatId": chat(), "mensagem": "vd", "dadosConhecidos": {"cpf": "1", "tokensGastos": {"input": 9, "output": 9, "total": 9}}}
    ),
    {"MOCK_CLASSIFICACAO_FLOWID": VD},
)

# ---- varredura: corpo vindo de fora --------------------------------------------------
V = "varredura"
for campo in ("chatId", "flowId", "dadosConhecidos"):
    for nome, v in VALORES.items():
        base = {"chatId": chat(), "flowId": VD, "dadosConhecidos": {}}
        base[campo] = v
        cen(f"atend_{campo}_{nome}", "POST", "/atendimentos", JSON_H, corpo_texto(base), bloco=V)
for campo in ("chatId", "mensagem", "resposta", "dadosConhecidos"):
    for nome, v in VALORES.items():
        base = {"chatId": chat(), "mensagem": "relato"}
        if campo == "resposta":
            base.pop("mensagem")
        base[campo] = v
        cen(f"orq_{campo}_{nome}", "POST", "/atendimentos/orquestrador", JSON_H, corpo_texto(base), M_PP, bloco=V)
for canal in (
    "cpf",
    "tokensGastos",
    "statusFinal",
    "mensagemFinal",
    "viaOrquestrador",
    "ehVitima",
    "encaminhamentoId",
    "perguntaAtualTexto",
):
    for nome, v in VALORES.items():
        if v is AUS:
            continue
        valor = v if not (isinstance(v, str) and v.startswith("RAW:")) else float(v[4:])
        cen(
            f"dados_{canal}_{nome}",
            "POST",
            "/atendimentos",
            JSON_H,
            corpo_texto({"chatId": chat(), "flowId": VD, "dadosConhecidos": {canal: valor}}),
            bloco=V,
        )
for nome, v in [
    ("input_texto", {"input": "x", "output": 1, "total": 1}),
    ("parcial", {"input": 1}),
    ("input_null", {"input": None, "output": 1, "total": 1}),
]:
    cen(
        f"dados_tokens_{nome}",
        "POST",
        "/atendimentos",
        JSON_H,
        corpo_texto({"chatId": chat(), "flowId": VD, "dadosConhecidos": {"tokensGastos": v}}),
        bloco=V,
    )
# corpo e content-type
for nome, h, corpo in [
    ("sem_corpo_sem_ct", AUTH, None),
    ("json_null", JSON_H, "null"),
    ("json_lista", JSON_H, "[]"),
    ("json_texto", JSON_H, '"x"'),
    ("json_numero", JSON_H, "7"),
    ("json_vazio", JSON_H, ""),
    ("json_espacos", JSON_H, "   "),
    ("json_invalido", JSON_H, "{x"),
    ("json_bom", JSON_H, "﻿" + corpo_texto({"chatId": "conf-bom", "flowId": VD})),
    ("json_proto", JSON_H, '{"__proto__":{"a":1},"chatId":"p","flowId":"' + VD + '"}'),
    ("json_constructor", JSON_H, '{"constructor":{"prototype":{}},"chatId":"q","flowId":"' + VD + '"}'),
    ("json_chaves_duplicadas", JSON_H, '{"chatId":"d1","chatId":"d2","flowId":"' + VD + '"}'),
    ("json_nan", JSON_H, '{"chatId":NaN}'),
    ("ct_charset", {**AUTH, "content-type": "application/json; charset=utf-8"}, corpo_texto({"chatId": chat(), "flowId": VD})),
    ("ct_maiusculo", {**AUTH, "content-type": "APPLICATION/JSON"}, corpo_texto({"chatId": chat(), "flowId": VD})),
    ("ct_texto", {**AUTH, "content-type": "text/plain"}, "oi"),
    ("ct_texto_vazio", {**AUTH, "content-type": "text/plain"}, ""),
    ("ct_xml", {**AUTH, "content-type": "application/xml"}, "<a/>"),
    ("ct_invalido", {**AUTH, "content-type": "json"}, "{}"),
    ("ct_vazio", {**AUTH, "content-type": ""}, "{}"),
    ("ct_form", {**AUTH, "content-type": "application/x-www-form-urlencoded"}, "a=1"),
    ("sem_ct_com_corpo", AUTH, corpo_texto({"chatId": chat(), "flowId": VD})),
    ("ct_json_patch", {**AUTH, "content-type": "application/merge-patch+json"}, "{}"),
]:
    cen(f"corpo_{nome}", "POST", "/atendimentos", h, corpo, bloco=V)

json.dump(cenarios, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(cenarios), {b: sum(c["bloco"] == b for c in cenarios) for b in ("principal", "varredura")})
