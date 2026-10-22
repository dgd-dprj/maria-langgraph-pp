"""O que o /docs mostra além dos schemas de rota: obrigatório, descrição e exemplo (issue #283).

Os schemas de `esquemas.py` também validam o corpo e serializam a resposta, na ordem de develop.
Por isso a documentação entra aqui, por cima de uma cópia: `required` e `anyOf` não passam a
rejeitar nada, e a ordem de serialização não muda.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

Schema = dict[str, Any]

_PARAMETRO_CAMINHO = re.compile(r":(\w+)")

ERRO_401: Schema = {
    "type": "object",
    "properties": {"error": {"type": "string", "description": '"missing authorization header" ou "invalid authorization header"'}},
}

DESCRICAO_CHAT_ID = (
    "Identificador da conversa, atribuído pela Tykhe: o mesmo em todas as rodadas. Até 100 caracteres, "
    "sem `/`, `?`, `#` nem espaço (vai no caminho da consulta e nos `_links`)."
)

# Descrição por nome de campo, aplicada onde o campo existe nas respostas.
DESCRICOES_RESPOSTA: dict[str, Schema] = {
    "tipoCaso": {
        "description": ("Só vem com `status: redirecionado` (caso que a Tykhe atende). `outros` também cobre relato não identificado.")
    },
    "destino": {
        "description": (
            "Só em atendimento encerrado, e só quando o fluxo tem destino definido: para onde a pessoa vai. "
            "`status` diz que terminou, `destino` diz para onde. `atendimento_humano` (acompanha `handoff_humano`; "
            "o porquê continua em `metadados.motivoHandoff`), `agendamento` (fluxo de violência doméstica concluído) "
            "ou `sessao_expirada` (acompanha `expirado`). Pessoa presa concluída não traz o campo."
        ),
    },
    "flowId": {
        "description": "Id do fluxo da Maria identificado. Não vem na desambiguação nem no `redirecionado`.",
    },
    "dadosColetados": {
        "type": "object",
        "description": (
            "Dados já coletados pelo fluxo. Hoje só `cpf`, e só quando existe. "
            "Só aparece na resposta do fluxo da Maria identificado; nunca no `redirecionado` nem na desambiguação."
        ),
        "properties": {"cpf": {"type": "string"}},
    },
}

DESCRICOES_PARAMETROS: dict[str, str] = {"chatId": DESCRICAO_CHAT_ID}

DESCRICOES_ROTA: dict[tuple[str, str], str] = {
    ("POST", "/atendimentos/orquestrador"): (
        "1ª chamada: `{ chatId, mensagem }`. Continuação da desambiguação (resposta sem `flowId` e com "
        "`_links.responder` apontando para esta rota): `{ chatId, resposta }`. Mandar `mensagem` de novo reinicia a "
        "classificação do zero. `resposta` vazia é 400. `status: redirecionado` traz `tipoCaso` e encerra a conversa aqui."
    ),
    ("GET", "/atendimentos/:chatId"): "Só lê o estado; não avança o fluxo. `chatId` com mais de 100 caracteres responde 414.",
}


@dataclass(frozen=True)
class CamposCorpo:
    obrigatorios: tuple[str, ...] = ()
    # Pelo menos um destes precisa vir (OpenAPI `anyOf` de `required`).
    um_de: tuple[str, ...] = ()
    descricoes: dict[str, str] = field(default_factory=dict)
    exemplo: dict[str, Any] = field(default_factory=dict)


_DADOS_CONHECIDOS = (
    "Opcional. O que a Tykhe já sabe, para a Maria não perguntar de novo. Hoje só `cpf`. "
    "Vale na criação do atendimento; no orquestrador, é repassado ao fluxo identificado."
)

CORPOS: dict[tuple[str, str], CamposCorpo] = {
    ("POST", "/atendimentos/orquestrador"): CamposCorpo(
        obrigatorios=("chatId",),
        um_de=("mensagem", "resposta"),
        descricoes={
            "chatId": f"Obrigatório (só dispensado com `APP_ENV=test`). {DESCRICAO_CHAT_ID}",
            "mensagem": "Relato livre da pessoa. Use na 1ª chamada da conversa.",
            "resposta": ("Resposta à pergunta de desambiguação. Use nas chamadas seguintes, na mesma rota. Não pode ser vazia (400)."),
            "dadosConhecidos": _DADOS_CONHECIDOS,
        },
        exemplo={
            "chatId": "conversa-0001",
            "mensagem": "Preciso de ajuda com uma situação em casa.",
            "dadosConhecidos": {"cpf": "00000000000"},
        },
    ),
    ("POST", "/atendimentos"): CamposCorpo(
        obrigatorios=("flowId",),
        descricoes={
            "chatId": f"Obrigatório (só dispensado com `APP_ENV=test`). {DESCRICAO_CHAT_ID}",
            "flowId": "Obrigatório. Id do fluxo; os ids disponíveis estão em `GET /fluxos`.",
            "dadosConhecidos": _DADOS_CONHECIDOS,
        },
        exemplo={"chatId": "conversa-0001", "flowId": "00000000-0000-4000-8000-000000000000"},
    ),
    ("POST", "/atendimentos/respostas"): CamposCorpo(
        obrigatorios=("chatId", "resposta"),
        descricoes={
            "chatId": f"Obrigatório. {DESCRICAO_CHAT_ID} O servidor resolve o fluxo sozinho a partir dele.",
            "resposta": 'Obrigatória. `"true"`/`"false"` para `sim_nao`; texto livre para as demais.',
        },
        exemplo={"chatId": "conversa-0001", "resposta": "true"},
    ),
}


def caminho_openapi(caminho: str) -> str:
    """`/atendimentos/:chatId` → `/atendimentos/{chatId}`."""
    return _PARAMETRO_CAMINHO.sub(r"{\1}", caminho)


def parametros_caminho(caminho: str) -> list[Schema]:
    return [
        {
            "name": nome,
            "in": "path",
            "required": True,
            "description": DESCRICOES_PARAMETROS.get(nome, ""),
            "schema": {"type": "string", "maxLength": 100},
        }
        for nome in _PARAMETRO_CAMINHO.findall(caminho)
    ]


def documentar_corpo(metodo: str, caminho: str, schema: Schema) -> Schema:
    campos = CORPOS.get((metodo, caminho))
    documentado = copy.deepcopy(schema)
    if campos is None:
        return documentado
    propriedades = documentado.get("properties", {})
    for nome, descricao in campos.descricoes.items():
        if nome in propriedades:
            propriedades[nome]["description"] = descricao
    if campos.obrigatorios:
        documentado["required"] = list(campos.obrigatorios)
    if campos.um_de:
        documentado["anyOf"] = [{"required": [nome]} for nome in campos.um_de]
    if campos.exemplo:
        documentado["example"] = campos.exemplo
    return documentado


def documentar_resposta(schema: Schema) -> Schema:
    documentado = copy.deepcopy(schema)
    propriedades = documentado.get("properties", {})
    for nome, extra in DESCRICOES_RESPOSTA.items():
        if nome in propriedades:
            # Com `type`, a definição substitui a do schema (é o caso de dadosColetados, que difere entre as rotas).
            propriedades[nome] = copy.deepcopy(extra) if "type" in extra else {**propriedades[nome], **extra}
    return documentado
