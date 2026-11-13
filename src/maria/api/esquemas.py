"""Schemas das rotas, copiados de develop @ 1157a6d na MESMA ordem de propriedades.

A ordem é contrato: o Fastify serializa a resposta na ordem do schema
(`serializacao.py`). Descrições ficam só onde o /docs as mostra.
"""

from __future__ import annotations

from typing import Any

from maria.fluxos.tipos_tykhe import TIPOS_TYKHE

Schema = dict[str, Any]

DESTINOS = ["atendimento_humano", "agendamento", "email_enviado", "sessao_expirada"]

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

# #435 (multi-fluxo, fase 1a, só no release): os outros assuntos do relato, para a Tykhe seguir com eles.
# Só aparece quando há outro assunto. `flowId` quando o assunto é de um fluxo da Maria; `tipoCaso`
# quando é da Tykhe.
ASSUNTOS_PENDENTES: Schema = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "nome": {"type": "string"},
            # O sinal de risco do relato, marcado pela classificação.
            "urgente": {"type": "boolean"},
            # #450 (2026-11-10): o parâmetro de urgência (tabela por assunto, com o sinal de risco por cima).
            "urgencia": {"type": "string", "enum": ["urgente", "menos_urgente"]},
            "flowId": {"type": "string"},
            "tipoCaso": {"type": "string"},
            # #442: o que a Maria já sabe para este assunto; a Tykhe repassa em `dadosConhecidos` ao abrir o fluxo.
            "dadosConhecidos": {"type": "object", "additionalProperties": True},
        },
    },
}

# #450 (2026-11-11, só no release): os assuntos em aberto da pessoa, desta conversa e guardados de outras, os urgentes
# primeiro. Decisão da Nicole (2026-11-13): o assunto é identificado pelo `flowId` (fluxo da Maria) ou pelo `tipoCaso`
# (assunto da Tykhe), que aparecem uma vez só na lista; a Tykhe manda esse valor em `POST /atendimentos/proximo-assunto`
# como `assunto`. O `chatIdAssunto` saiu da resposta.
ASSUNTOS_EM_ABERTO: Schema = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "nome": {"type": "string"},
            "urgente": {"type": "boolean"},
            "urgencia": {"type": "string", "enum": ["urgente", "menos_urgente"]},
            "codigo": {"type": "string", "description": "Código curto do assunto, para a pessoa citar à equipe"},
            "fase": {"type": "string", "enum": ["nao_iniciado", "em_andamento"]},
            "venceEm": {"type": "string"},
            "flowId": {"type": "string", "description": "Assunto da Maria: o id do assunto, para mandar como `assunto`"},
            "tipoCaso": {"type": "string", "description": "Assunto da Tykhe: o id do assunto, para mandar como `assunto`"},
        },
    },
}

# #450 (2026-11-11, só no release): no fim da conversa, o resumo do que foi atendido, sem nada do relato.
RESUMO_DA_CONVERSA: Schema = {
    "type": "array",
    "items": {"type": "object", "properties": {"nome": {"type": "string"}, "desfecho": {"type": "string"}, "codigo": {"type": "string"}}},
}

# rotas/atendimentos.ts:146-181
RESPOSTA_ATENDIMENTO: Schema = {
    "type": "object",
    "properties": {
        "resposta": {"type": "string"},
        "tipoResposta": {"type": "string", "enum": ["texto", "sim_nao", "opcoes", "link_imagem"]},
        "tipoImagem": {"type": "string"},
        "opcoes": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": ["em_andamento", "concluido", "handoff_humano", "expirado"]},
        "destino": {"type": "string", "enum": DESTINOS},
        "flowId": {"type": "string", "format": "uuid"},
        "metadados": {"type": "object", "additionalProperties": True},
        "dadosColetados": {
            "type": "object",
            "properties": {
                "cpf": {"type": "string"},
                # #448: plano de saúde para outra pessoa. Dado pessoal: só na resposta, nunca em log nem em `metadados`.
                "solicitante": {"type": "object", "properties": {"nome": {"type": "string"}, "cpf": {"type": "string"}}},
                "outraPessoa": {
                    "type": "object",
                    "properties": {
                        **{
                            campo: {"type": "string"}
                            for campo in (
                                "cpf",
                                "nome",
                                "dataNascimento",
                                "endereco",
                                "telefone",
                                "whatsapp",
                                "email",
                                "estadoCivil",
                                "profissao",
                                "rg",
                                "parentesco",
                            )
                        },
                        "origem": {"type": "string", "enum": ["verde", "informado"]},
                    },
                },
                # #398: links de baixar as imagens, só em `concluido` (plano de saúde). Segredo: nunca em log.
                "imagens": {
                    "type": "object",
                    "properties": {"carteirinhaFrente": {"type": "string"}, "carteirinhaVerso": {"type": "string"}},
                },
            },
        },
        "tokensGastos": TOKENS_GASTOS,
        "assuntosPendentes": ASSUNTOS_PENDENTES,
        # #450 (2026-11-11, só no release): no fim da conversa, o resumo, os assuntos em aberto e os botões (um por
        # assunto em aberto, "Falar de um assunto novo" e "Encerrar a conversa").
        "resumoDaConversa": RESUMO_DA_CONVERSA,
        "assuntosEmAberto": ASSUNTOS_EM_ABERTO,
        "opcoesDoFim": {"type": "array", "items": {"type": "string"}},
        "_links": LINKS,
    },
}

# #450 (multi-fluxo, fase 1b, só no release): POST /atendimentos/proximo-assunto. O corpo é o de um
# atendimento (assunto da Maria) ou o do redirecionado (assunto da Tykhe), mais o `chatId` gerado pela Maria.
CORPO_PROXIMO_ASSUNTO: Schema = {
    "type": "object",
    "properties": {
        "chatId": {"type": "string", "description": "O chatId da conversa"},
        "assunto": {"type": "string", "description": "Opcional: o flowId (ou o tipoCaso) de um item de assuntosEmAberto"},
        "resposta": {"type": "string", "description": "Opcional: a resposta da pessoa à lista dos assuntos em aberto"},
    },
}
# #450 (2026-11-11, só no release): POST /atendimentos/assuntos-em-aberto.
CORPO_ASSUNTOS_EM_ABERTO: Schema = {"type": "object", "properties": {"chatId": {"type": "string", "description": "O chatId da conversa"}}}
RESPOSTA_ASSUNTOS_EM_ABERTO: Schema = {
    "type": "object",
    "properties": {
        "resposta": {"type": "string"},
        "tipoResposta": {"type": "string", "enum": ["texto", "opcoes"]},
        "opcoes": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": ["em_andamento"]},
        "assuntosEmAberto": ASSUNTOS_EM_ABERTO,
        "_links": LINKS,
    },
}
RESPOSTA_PROXIMO_ASSUNTO: Schema = {
    "type": "object",
    "properties": {
        **RESPOSTA_ATENDIMENTO["properties"],
        "status": {"type": "string", "enum": ["em_andamento", "concluido", "handoff_humano", "expirado", "redirecionado"]},
        "tipoCaso": {"type": "string"},
        "chatId": {"type": "string", "description": "O chatId deste assunto, gerado pela Maria: use-o nas próximas chamadas"},
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

# rotas/atendimentos.ts:469-475
CORPO_RESPOSTAS: Schema = {
    "type": "object",
    "properties": {
        "chatId": {"type": "string"},
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
        "destino": {"type": "string", "enum": DESTINOS},
        "tipoCaso": {"type": "string", "enum": [t.tipo_caso for t in TIPOS_TYKHE]},
        "motivoHandoff": {"type": "string", "enum": ["nao_identificado"]},
        "metadados": {"type": "object", "additionalProperties": True},
        "dadosColetados": {"type": "object", "additionalProperties": True},
        "tokensGastos": TOKENS_GASTOS,
        "flowId": {"type": "string"},
        "assuntosPendentes": ASSUNTOS_PENDENTES,
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
        # #450 (só no release): o id da pessoa na Tykhe, a chave dos assuntos guardados. Opcional.
        "idUsuario": {"type": "string"},
    },
}
