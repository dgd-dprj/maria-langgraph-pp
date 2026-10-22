"""Schemas das rotas, copiados de develop @ 1157a6d na MESMA ordem de propriedades.

A ordem é contrato: o Fastify serializa a resposta na ordem do schema
(`serializacao.py`). Descrições ficam só onde o /docs as mostra.
"""

from __future__ import annotations

from typing import Any

from maria.fluxos.tipos_tykhe import TIPOS_TYKHE

Schema = dict[str, Any]

DESCRICAO_CHAT_ID = (
    "Identificador da conversa, atribuído pela Tykhe. Até 100 caracteres, sem `/`, `?`, `#` nem espaço. "
    "Obrigatório (400 sem ele), salvo com APP_ENV=test."
)
DESCRICAO_DADOS_CONHECIDOS = "Opcional. Dados que a Tykhe já sabe, para a Maria não perguntar de novo. Exemplo: `cpf` (texto)."
DESCRICAO_DADOS_COLETADOS = (
    "Opcional. O que o fluxo já coletou. Só aparece nas respostas de um fluxo da Maria identificado, "
    "e pode vir vazio; não vem nos redirecionamentos nem nas perguntas de desambiguação."
)
DESCRICAO_DADOS_CONHECIDOS_ORQUESTRADOR = (
    DESCRICAO_DADOS_CONHECIDOS + " Só é usado se o relato levar a um fluxo da Maria: nesse caso vai para o atendimento criado. "
    "Nos redirecionamentos (`status` = `redirecionado`) e nas perguntas de desambiguação não tem efeito."
)

# rotas/atendimentos.ts:125-134
LINKS: Schema = {
    "type": "object",
    "properties": {
        "self": {"type": "object", "properties": {"href": {"type": "string"}}},
        "responder": {"type": "object", "properties": {"href": {"type": "string"}, "method": {"type": "string", "enum": ["POST"]}}},
    },
}

TOKENS_GASTOS: Schema = {
    "type": "object",
    "properties": {"input": {"type": "number"}, "output": {"type": "number"}, "total": {"type": "number"}},
}

# rotas/atendimentos.ts:140. additionalProperties: o 409 de "atendimento já
# concluído" leva o atendimento inteiro junto do `erro`.
ERRO_ATENDIMENTOS: Schema = {"type": "object", "properties": {"erro": {"type": "string"}}, "additionalProperties": True}

# rotas/atendimentos.ts:146-181
RESPOSTA_ATENDIMENTO: Schema = {
    "type": "object",
    "properties": {
        "resposta": {"type": "string"},
        "tipoResposta": {"type": "string", "enum": ["texto", "sim_nao", "opcoes"]},
        "opcoes": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": ["em_andamento", "concluido", "handoff_humano", "expirado"]},
        "flowId": {"type": "string", "format": "uuid"},
        "metadados": {"type": "object", "additionalProperties": True},
        "dadosColetados": {
            "type": "object",
            "properties": {"cpf": {"type": "string"}},
            "description": DESCRICAO_DADOS_COLETADOS,
        },
        "tokensGastos": TOKENS_GASTOS,
        "_links": LINKS,
    },
}

# rotas/atendimentos.ts:384-396
#
# `required` e `description` só alimentam o /docs: a validação (`validacao.py`) e a serialização
# (`serializacao.py`) leem apenas `type`, `format`, `properties` e `additionalProperties`. Quem
# recusa a requisição é o handler (400), com a mensagem própria de cada rota.
CORPO_CRIAR_ATENDIMENTO: Schema = {
    "type": "object",
    "required": ["chatId", "flowId"],
    "properties": {
        "chatId": {"type": "string", "description": DESCRICAO_CHAT_ID},
        "flowId": {"type": "string", "format": "uuid", "description": "Fluxo do atendimento (ver GET /fluxos)"},
        "dadosConhecidos": {"type": "object", "additionalProperties": True, "description": DESCRICAO_DADOS_CONHECIDOS},
    },
}

# rotas/atendimentos.ts:469-475
CORPO_RESPOSTAS: Schema = {
    "type": "object",
    "required": ["chatId", "resposta"],
    "properties": {
        "chatId": {"type": "string", "description": "O mesmo chatId do atendimento; o servidor resolve o flowId sozinho a partir dele"},
        "resposta": {"type": "string", "description": '"true"/"false" pra sim_nao, texto livre pras demais'},
    },
}

# rotas/fluxos.ts:4-7
FLUXOS: Schema = {
    "type": "array",
    "items": {"type": "object", "properties": {"id": {"type": "string", "format": "uuid"}, "nome": {"type": "string"}}},
}

# rotas/orquestrador.ts:9 (sem additionalProperties, ao contrário do de atendimentos)
ERRO_ORQUESTRADOR: Schema = {"type": "object", "properties": {"erro": {"type": "string"}}}

# rotas/orquestrador.ts:11-54
RESPOSTA_ORQUESTRADOR: Schema = {
    "type": "object",
    "properties": {
        "resposta": {"type": "string"},
        "tipoResposta": {"type": "string", "enum": ["texto", "sim_nao", "opcoes"]},
        "opcoes": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": ["em_andamento", "concluido", "handoff_humano", "redirecionado"]},
        "tipoCaso": {
            "type": "string",
            "enum": [t.tipo_caso for t in TIPOS_TYKHE],
            "description": "Só com `status` = `redirecionado`: o tipo de caso que a Tykhe atende. Sempre presente nesse status.",
        },
        "motivoHandoff": {"type": "string", "enum": ["nao_identificado"]},
        "metadados": {"type": "object", "additionalProperties": True},
        "dadosColetados": {"type": "object", "additionalProperties": True, "description": DESCRICAO_DADOS_COLETADOS},
        "tokensGastos": TOKENS_GASTOS,
        "flowId": {"type": "string"},
        "_links": {"type": "object", "additionalProperties": True},
    },
}

# rotas/orquestrador.ts:110-125
CORPO_ORQUESTRADOR: Schema = {
    "type": "object",
    "required": ["chatId"],
    "anyOf": [{"required": ["mensagem"]}, {"required": ["resposta"]}],
    "properties": {
        "chatId": {"type": "string", "description": DESCRICAO_CHAT_ID + " O mesmo chatId em todas as rodadas da conversa."},
        "mensagem": {
            "type": "string",
            "description": "Relato livre da pessoa. Obrigatório na 1ª chamada; use `resposta` para continuar a desambiguação.",
        },
        "resposta": {
            "type": "string",
            "description": (
                "Resposta à pergunta de desambiguação. Obrigatório nas chamadas seguintes à 1ª, no lugar de `mensagem`. "
                "Texto livre e não vazio (vazio dá 400)."
            ),
        },
        "dadosConhecidos": {"type": "object", "additionalProperties": True, "description": DESCRICAO_DADOS_CONHECIDOS_ORQUESTRADOR},
    },
}
