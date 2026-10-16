"""Schemas das rotas, copiados de develop @ 1157a6d na MESMA ordem de propriedades.

A ordem é contrato: o Fastify serializa a resposta na ordem do schema
(`serializacao.py`). Descrições ficam só onde o /docs as mostra.
"""

from __future__ import annotations

from typing import Any

from maria.fluxos.tipos_tykhe import TIPOS_TYKHE

Schema = dict[str, Any]

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
        "dadosColetados": {"type": "object", "properties": {"cpf": {"type": "string"}}},
        "tokensGastos": TOKENS_GASTOS,
        "_links": LINKS,
    },
}

# rotas/atendimentos.ts:384-396
CORPO_CRIAR_ATENDIMENTO: Schema = {
    "type": "object",
    "properties": {
        "chatId": {"type": "string"},
        "flowId": {"type": "string", "format": "uuid"},
        "dadosConhecidos": {"type": "object", "additionalProperties": True},
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
        "tipoCaso": {"type": "string", "enum": [t.tipo_caso for t in TIPOS_TYKHE]},
        "motivoHandoff": {"type": "string", "enum": ["nao_identificado"]},
        "metadados": {"type": "object", "additionalProperties": True},
        "dadosColetados": {"type": "object", "additionalProperties": True},
        "tokensGastos": TOKENS_GASTOS,
        "flowId": {"type": "string"},
        "_links": {"type": "object", "additionalProperties": True},
    },
}

# rotas/orquestrador.ts:110-125
CORPO_ORQUESTRADOR: Schema = {
    "type": "object",
    "properties": {
        "chatId": {"type": "string"},
        "mensagem": {"type": "string"},
        "resposta": {"type": "string"},
        "dadosConhecidos": {"type": "object", "additionalProperties": True},
    },
}
