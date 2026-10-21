# mypy: ignore-errors
# ruff: noqa
# Script de captura (não é teste nem código da aplicação), guardado para regravar a conferência.
"""Cenários da conferência diferencial do PR 2 do api (GET /atendimentos/:chatId,
POST /atendimentos/respostas com o TTL, /webhook/whatsapp e o roteador), por HTTP.

Mesmo formato do PR 1 (`conferencia-api-pr1/gerar_cenarios.py`): requisição crua
(método, caminho, cabeçalhos, corpo como texto, ambiente). Os dois lados rodam a
lista na mesma ordem, numa única aplicação; o estado de um cenário vale para os
seguintes. Uso: python gerar_cenarios_pr2.py cenarios.json
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
    "inteiro_grande": "RAW:12345678901234567890",
    "float": 1.5,
    "objeto_cheio": {"a": 1},
    "espacos": "   ",
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
    return f"conf-pr2-{n}"


def criar(nome, chat_id, flow=VD, dados=None, env=None, bloco="principal"):
    campos = {"chatId": chat_id, "flowId": flow}
    if dados is not None:
        campos["dadosConhecidos"] = dados
    cen(nome, "POST", "/atendimentos", JSON_H, corpo_texto(campos), env, bloco)


def responder(nome, chat_id, resposta, env=None, bloco="principal"):
    cen(nome, "POST", "/atendimentos/respostas", JSON_H, corpo_texto({"chatId": chat_id, "resposta": resposta}), env, bloco)


def get(nome, chat_id, headers=AUTH, bloco="principal"):
    cen(nome, "GET", f"/atendimentos/{chat_id}", headers, None, None, bloco)


# ---- caminhos principais ------------------------------------------------------------
get("get_nunca_criado", "conf-pr2-nunca")
criar("vd_criar", "conf-pr2-vd")
get("vd_get_pergunta_1", "conf-pr2-vd")
responder("vd_eh_vitima", "conf-pr2-vd", "true")
get("vd_get_pergunta_2", "conf-pr2-vd")
responder("vd_sem_processo", "conf-pr2-vd", "false")
responder("vd_tem_ro", "conf-pr2-vd", "true")
responder("vd_cpf", "conf-pr2-vd", "11111111111")
get("vd_get_concluido", "conf-pr2-vd")
responder("vd_409_concluido", "conf-pr2-vd", "qualquer coisa")
criar("vd_cpf_conhecido", "conf-pr2-vd-cpf", dados={"cpf": "11111111111"})
responder("vd_cpf_conhecido_nao_vitima", "conf-pr2-vd-cpf", "false")
responder("vd_cpf_conhecido_409", "conf-pr2-vd-cpf", "x")
criar("pp_criar", "conf-pr2-pp", PP)
responder("pp_sem_processo", "conf-pr2-pp", "Não")
responder("pp_rg_invalido", "conf-pr2-pp", "abc")
responder("pp_rg", "conf-pr2-pp", "11111111111")
get("pp_get_confirma_nome", "conf-pr2-pp")
responder("pp_confirma", "conf-pr2-pp", "Sim")
responder("pp_parentesco", "conf-pr2-pp", "irmão", {"MOCK_CLASSIFICACAO_PARENTESCO": "Irmão(a)"})
get("pp_get_concluido", "conf-pr2-pp")
criar("vd_encaminhamento_falha", "conf-pr2-vd-falha", dados={"cpf": "11111111111"})
responder("vd_falha_1", "conf-pr2-vd-falha", "true")
responder("vd_falha_2", "conf-pr2-vd-falha", "false")
responder("vd_falha_3", "conf-pr2-vd-falha", "true", {"MOCK_ENCAMINHAMENTO_FALHA": "true"})
responder("respostas_chat_inexistente", "conf-pr2-nunca", "x")
# Orquestrador sem fluxo: a thread `orquestrador:x` não está na tabela de atendimentos.
cen(
    "orq_redirecionado",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto({"chatId": "conf-pr2-orq", "mensagem": "remédio"}),
    {"MOCK_CLASSIFICACAO_FLOWID": "tykhe:saude"},
)
get("orq_redirecionado_get", "conf-pr2-orq")
responder("orq_redirecionado_respostas", "conf-pr2-orq", "x")
cen(
    "orq_identifica",
    "POST",
    "/atendimentos/orquestrador",
    JSON_H,
    corpo_texto({"chatId": "conf-pr2-orq-pp", "mensagem": "preso"}),
    {"MOCK_CLASSIFICACAO_FLOWID": PP},
)
get("orq_identifica_get", "conf-pr2-orq-pp")
responder("orq_identifica_responde", "conf-pr2-orq-pp", "false")
criar("vd_via_orq_em_dados", "conf-pr2-viaorq", dados={"cpf": "11111111111", "viaOrquestrador": True})
responder("vd_via_orq_1", "conf-pr2-viaorq", "true")
responder("vd_via_orq_2", "conf-pr2-viaorq", "false")
responder("vd_via_orq_3", "conf-pr2-viaorq", "true")

# ---- TTL (#166, #227, #234) ------------------------------------------------------------
TTL0 = {"TTL_INATIVIDADE_HORAS": "0"}
for i, conf in enumerate(["sim", "Sim", " s ", "quero continuar", "Continuar", "pode continuar", "SIM", "yes", "true"]):
    c = f"conf-pr2-ttl-c{i}"
    criar(f"ttl_c{i}_criar", c, bloco="ttl")
    responder(f"ttl_c{i}_confirmacao", c, "false", TTL0, "ttl")
    responder(f"ttl_c{i}_continuar", c, conf, None, "ttl")
    get(f"ttl_c{i}_get", c, bloco="ttl")
for i, conf in enumerate(["não", "nao", "N", "Recomeçar", "comecar de novo", "não quero", "false"]):
    c = f"conf-pr2-ttl-r{i}"
    criar(f"ttl_r{i}_criar", c, bloco="ttl")
    responder(f"ttl_r{i}_confirmacao", c, "true", TTL0, "ttl")
    responder(f"ttl_r{i}_recomecar", c, conf, None, "ttl")
    responder(f"ttl_r{i}_409_expirado", c, "true", None, "ttl")
    get(f"ttl_r{i}_get_depois_de_expirado", c, bloco="ttl")
c = "conf-pr2-ttl-repete"
criar("ttl_repete_criar", c, bloco="ttl")
responder("ttl_repete_confirmacao", c, "false", TTL0, "ttl")
responder("ttl_repete_nao_reconhecida", c, "meu marido me ameaçou", None, "ttl")
responder("ttl_repete_de_novo", c, "talvez", TTL0, "ttl")
responder("ttl_repete_sim", c, "sim", None, "ttl")
for nome, valor in [
    ("abc", "abc"),
    ("vazio", ""),
    ("hex", "0x10"),
    ("espacos", " 5 "),
    ("negativo", "-1"),
    ("infinito", "Infinity"),
    ("zero_ponto", "0.0"),
    ("exp", "1e-9"),
]:
    c = f"conf-pr2-ttl-env-{nome}"
    criar(f"ttl_env_{nome}_criar", c, bloco="ttl")
    responder(f"ttl_env_{nome}_resposta", c, "true", {"TTL_INATIVIDADE_HORAS": valor}, "ttl")

# ---- roteador (find-my-way) -------------------------------------------------------------
criar("rota_criar_espaco", "a b", bloco="roteador")
criar("rota_criar_barra", "a/b", bloco="roteador")
criar("rota_criar_cedilha", "ç", bloco="roteador")
criar("rota_criar_percent", "a%b", bloco="roteador")
criar("rota_criar_mais", "a+b", bloco="roteador")
criar("rota_criar_100", "x" * 100, bloco="roteador")
criar("rota_criar_barra_espaco", "a/b c", bloco="roteador")
criar("rota_criar_barra_percent", "a/b%c", bloco="roteador")
for nome, caminho in [
    ("vazio", "/atendimentos/"),
    ("barra_final", "/atendimentos/conf-pr2-vd/"),
    ("espaco_codificado", "/atendimentos/a%20b"),
    ("barra_codificada", "/atendimentos/a%2Fb"),
    ("barra_codificada_minuscula", "/atendimentos/a%2fb"),
    ("barra_crua", "/atendimentos/a/b"),
    ("cedilha", "/atendimentos/%C3%A7"),
    ("percent", "/atendimentos/a%25b"),
    ("mais_cru", "/atendimentos/a+b"),
    ("mais_codificado", "/atendimentos/a%2Bb"),
    ("utf8_incompleto", "/atendimentos/%E0%A4%A"),
    ("escape_invalido", "/atendimentos/%zz"),
    ("escape_invalido_query", "/atendimentos/conf-pr2-vd?x=%zz"),
    ("query", "/atendimentos/conf-pr2-vd?y=1"),
    ("respostas_get", "/atendimentos/respostas"),
    ("orquestrador_get", "/atendimentos/orquestrador"),
    ("caixa", "/ATENDIMENTOS/conf-pr2-vd"),
    ("barra_dupla_meio", "/atendimentos//conf-pr2-vd"),
    ("ponto_e_virgula", "/atendimentos/conf-pr2-vd;x"),
    ("hash_codificado", "/atendimentos/a%23b"),
    ("param_100", "/atendimentos/" + "x" * 100),
    ("param_101", "/atendimentos/" + "x" * 101),
    ("param_101_codificado", "/atendimentos/" + "%78" * 101),
    ("param_emoji_51", "/atendimentos/" + "%F0%9F%98%80" * 51),
    ("param_emoji_50", "/atendimentos/" + "%F0%9F%98%80" * 50),
    ("fluxos_escape_invalido", "/fluxos%zz"),
    ("inexistente_escape_invalido", "/nao-existe%zz"),
    ("fluxos_codificado", "/flu%78os"),
    ("health_codificado", "/healt%68"),
    ("barra_e_espaco_codificados", "/atendimentos/a%2Fb%20c"),
    ("barra_e_percent_codificados", "/atendimentos/a%2Fb%25c"),
    ("espaco_e_barra_codificados", "/atendimentos/a%20b%2Fc"),
]:
    cen(f"rota_get_{nome}", "GET", caminho, AUTH, bloco="roteador")
    cen(f"rota_head_{nome}", "HEAD", caminho, AUTH, bloco="roteador")
cen("rota_post_param", "POST", "/atendimentos/x", JSON_H, "{}", bloco="roteador")
cen("rota_put_escape_invalido", "PUT", "/atendimentos/%zz", AUTH, bloco="roteador")
cen("rota_get_sem_auth", "GET", "/atendimentos/conf-pr2-vd", {}, bloco="roteador")
cen("rota_get_sem_auth_inexistente", "GET", "/atendimentos/nunca", {}, bloco="roteador")
cen("rota_get_auth_errada", "GET", "/atendimentos/conf-pr2-vd", {"authorization": "Bearer errada"}, bloco="roteador")
cen("rota_get_escape_invalido_sem_auth", "GET", "/atendimentos/%zz", {}, bloco="roteador")
cen("rota_get_param_101_sem_auth", "GET", "/atendimentos/" + "x" * 101, {}, bloco="roteador")

# ---- POST /atendimentos/respostas: varredura da entrada -------------------------------
criar("varre_base", "conf-pr2-varre", bloco="varredura")
for campo in ("chatId", "resposta"):
    for nome, valor in VALORES.items():
        campos = {"chatId": "conf-pr2-varre", "resposta": "x"}
        campos[campo] = valor
        cen(f"varre_{campo}_{nome}", "POST", "/atendimentos/respostas", JSON_H, corpo_texto(campos), bloco="varredura")
for nome, h, corpo in [
    ("texto_plano", {**AUTH, "content-type": "text/plain"}, '{"chatId":"conf-pr2-varre","resposta":"x"}'),
    ("sem_content_type", AUTH, '{"chatId":"conf-pr2-varre","resposta":"x"}'),
    ("json_invalido", JSON_H, "{x"),
    ("corpo_vazio", JSON_H, ""),
    ("array", JSON_H, "[]"),
    ("string_json", JSON_H, '"x"'),
    ("null_json", JSON_H, "null"),
    ("sem_corpo", AUTH, None),
    ("campo_extra", JSON_H, '{"chatId":"conf-pr2-varre","resposta":"x","flowId":"' + PP + '"}'),
    ("proto", JSON_H, '{"__proto__":{"a":1},"chatId":"conf-pr2-varre","resposta":"x"}'),
    ("bom", JSON_H, '﻿{"chatId":"conf-pr2-varre","resposta":"x"}'),
    ("sem_auth_json_invalido", {"content-type": "application/json"}, "{x"),
]:
    cen(f"varre_corpo_{nome}", "POST", "/atendimentos/respostas", h, corpo, bloco="varredura")

# ---- webhook do WhatsApp --------------------------------------------------------------
TOKEN = {"WHATSAPP_VERIFY_TOKEN": "tok"}
for nome, query, env in [
    ("sem_token_env", "hub.mode=subscribe&hub.verify_token=tok&hub.challenge=abc", {}),
    ("token_vazio_env", "hub.mode=subscribe&hub.verify_token=&hub.challenge=abc", {"WHATSAPP_VERIFY_TOKEN": ""}),
    ("ok", "hub.mode=subscribe&hub.verify_token=tok&hub.challenge=abc", TOKEN),
    ("modo_errado", "hub.mode=unsubscribe&hub.verify_token=tok&hub.challenge=abc", TOKEN),
    ("token_errado", "hub.mode=subscribe&hub.verify_token=x&hub.challenge=abc", TOKEN),
    ("sem_challenge", "hub.mode=subscribe&hub.verify_token=tok", TOKEN),
    ("challenge_vazio", "hub.mode=subscribe&hub.verify_token=tok&hub.challenge=", TOKEN),
    ("challenge_repetido", "hub.mode=subscribe&hub.verify_token=tok&hub.challenge=a&hub.challenge=b", TOKEN),
    ("challenge_codificado", "hub.mode=subscribe&hub.verify_token=tok&hub.challenge=%C3%A7", TOKEN),
    ("challenge_mais", "hub.mode=subscribe&hub.verify_token=tok&hub.challenge=a+b", TOKEN),
    ("challenge_igual", "hub.mode=subscribe&hub.verify_token=tok&hub.challenge=a=b", TOKEN),
    ("challenge_escape_invalido", "hub.mode=subscribe&hub.verify_token=tok&hub.challenge=%zz", TOKEN),
    ("token_codificado", "hub.mode=subscribe&hub.verify_token=t%6Fk&hub.challenge=abc", TOKEN),
    ("token_repetido", "hub.mode=subscribe&hub.verify_token=tok&hub.verify_token=tok&hub.challenge=abc", TOKEN),
    ("sem_query", "", TOKEN),
    ("so_chave", "hub.mode&hub.verify_token=tok", TOKEN),
]:
    caminho = "/webhook/whatsapp" + ("?" + query if query else "")
    cen(f"wh_get_{nome}", "GET", caminho, {}, None, env, "webhook")
    cen(f"wh_head_{nome}", "HEAD", caminho, {}, None, env, "webhook")


def mensagem(de, texto):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "x",
                "changes": [
                    {"value": {"messages": [{"from": de, "id": "w", "type": "text", "text": {"body": texto}}]}, "field": "messages"}
                ],
            }
        ],
    }


def wh(nome, corpo, env=None, headers=None):
    texto = corpo if isinstance(corpo, str) else json.dumps(corpo, ensure_ascii=False)
    cen(f"wh_post_{nome}", "POST", "/webhook/whatsapp", headers or {"content-type": "application/json"}, texto, env, "webhook")


STATUS = {"object": "w", "entry": [{"changes": [{"value": {"statuses": [{"id": "w", "status": "delivered"}]}}]}]}
STATUS_FALHA = {
    "object": "w",
    "entry": [
        {
            "changes": [
                {"value": {"statuses": [{"id": "w", "status": "failed", "errors": [{"code": 131026, "title": "Mensagem não entregue"}]}]}}
            ]
        }
    ],
}
wh("status", STATUS)
wh("status_falha", STATUS_FALHA)
wh("vazio_objeto", {})
wh("audio", {"entry": [{"changes": [{"value": {"messages": [{"from": "551", "type": "audio"}]}}]}]})
wh("json_invalido", "{x")
wh("texto_plano", '{"a":1}', headers={"content-type": "text/plain"})
wh("sem_corpo", "", headers={})
wh("item_null", {"entry": [{"changes": [{"value": {"messages": [None]}}]}]})
wh("sair_sem_conversa", mensagem("5521000000001", "#sair"))
PP_ENV = {"MOCK_CLASSIFICACAO_FLOWID": PP}
wh("pp_1", mensagem("5521000000002", "meu irmão está preso"), PP_ENV)
wh("pp_2_tem_processo", mensagem("5521000000002", "Não"), PP_ENV)
wh("pp_3_rg", mensagem("5521000000002", "11111111111"), PP_ENV)
wh("pp_4_confirma", mensagem("5521000000002", "Sim"), PP_ENV)
wh("pp_5_parentesco_conclui", mensagem("5521000000002", "irmão"), PP_ENV)
wh("pp_6_nova_conversa", mensagem("5521000000002", "oi de novo"), PP_ENV)
wh("pp_7_sair_maiusculo", mensagem("5521000000002", "  #SAIR  "), PP_ENV)
wh("pp_8_depois_do_sair", mensagem("5521000000002", "oi"), PP_ENV)
wh("pp_9_sair_com_x1c", mensagem("5521000000002", "#sair\x1c"), PP_ENV)
wh("pp_10_sair_com_bom", mensagem("5521000000002", "﻿#sair"), PP_ENV)
wh("saude", mensagem("5521000000003", "remédio"), {"MOCK_CLASSIFICACAO_FLOWID": "tykhe:saude"})
wh("saude_de_novo", mensagem("5521000000003", "remédio"), {"MOCK_CLASSIFICACAO_FLOWID": "tykhe:saude"})
wh("tykhe_sair", mensagem("5521000000004", "quero sair"), {"MOCK_CLASSIFICACAO_FLOWID": "tykhe:sair"})
wh("outros", mensagem("5521000000005", "blá"), {"MOCK_CLASSIFICACAO_FLOWID": ""})
AMB = {"MOCK_CLASSIFICACAO_FLOWIDS": f"{PP},{VD}"}
wh("ambiguo_1", mensagem("5521000000006", "meu ex foi preso e me ameaça"), AMB)
wh("ambiguo_2", mensagem("5521000000006", "sou vítima"), {"MOCK_CLASSIFICACAO_FLOWID": VD})
wh("ambiguo_3", mensagem("5521000000006", "Sim"), {"MOCK_CLASSIFICACAO_FLOWID": VD})
VD_ENV = {"MOCK_CLASSIFICACAO_FLOWID": VD}
wh("vd_1", mensagem("5521000000007", "apanho do meu marido"), VD_ENV)
wh("vd_2_ttl", mensagem("5521000000007", "Sim"), {**VD_ENV, "TTL_INATIVIDADE_HORAS": "0"})
wh("vd_3_confirma_ttl", mensagem("5521000000007", "sim"), VD_ENV)
wh("vd_4_nao_vitima_texto", mensagem("5521000000007", "talvez"), VD_ENV)
wh(
    "numero_texto_numero",
    {"entry": [{"changes": [{"value": {"messages": [{"from": "5521000000008", "type": "text", "text": {"body": 7}}]}}]}]},
    PP_ENV,
)

json.dump(cenarios, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(cenarios), "cenários")
