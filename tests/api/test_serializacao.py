"""Serializador contra a tabela executada no Fastify de develop @ 1157a6d
(`tests/fixtures/contrato/serializacao-fastify.json`, gerada por
`serializacao-fastify.mts`, com os mesmos schemas das rotas)."""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from maria.api.serializacao import ErroSerializacao, serializar
from maria.shared._js import AUSENTE

REF: dict[str, str] = json.loads(Path("tests/fixtures/contrato/serializacao-fastify.json").read_text(encoding="utf-8"))

LINKS = {
    "type": "object",
    "properties": {
        "self": {"type": "object", "properties": {"href": {"type": "string"}}},
        "responder": {"type": "object", "properties": {"href": {"type": "string"}, "method": {"type": "string", "enum": ["POST"]}}},
    },
}
TOKENS = {"type": "object", "properties": {"input": {"type": "number"}, "output": {"type": "number"}, "total": {"type": "number"}}}
ATENDIMENTO = {
    "type": "object",
    "properties": {
        "resposta": {"type": "string"},
        "tipoResposta": {"type": "string", "enum": ["texto", "sim_nao", "opcoes"]},
        "opcoes": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string"},
        "flowId": {"type": "string", "format": "uuid"},
        "metadados": {"type": "object", "additionalProperties": True},
        "dadosColetados": {"type": "object", "properties": {"cpf": {"type": "string"}}},
        "tokensGastos": TOKENS,
        "_links": LINKS,
    },
}
ERRO = {"type": "object", "properties": {"erro": {"type": "string"}}, "additionalProperties": True}
ERRO_SEM = {"type": "object", "properties": {"erro": {"type": "string"}}}
FLUXOS = {
    "type": "array",
    "items": {"type": "object", "properties": {"id": {"type": "string", "format": "uuid"}, "nome": {"type": "string"}}},
}
SCHEMAS: dict[str, dict[str, Any]] = {"a": ATENDIMENTO, "e": ERRO, "es": ERRO_SEM, "f": FLUXOS}

# Os valores da tabela, em Python. "data" (Date do JS) não existe no estado dos grafos.
VALORES: dict[str, Any] = {
    "string": "x",
    "vazia": "",
    "numero_int": 7,
    "numero_float": 1.5,
    "exp_pequeno": 1e-7,
    "exp_grande": 1e21,
    "zero_neg": -0.0,
    "nan": math.nan,
    "infinito": math.inf,
    "true": True,
    "false": False,
    "null": None,
    "undefined": AUSENTE,
    "objeto": {"a": 1},
    "lista": ["a", None, 2],
    "lista_vazia": [],
    "aninhado_undef": {"a": AUSENTE, "b": [AUSENTE]},
}


def _corpo(caso: str, v: Any) -> tuple[str, Any]:
    if caso == "resposta":
        return "a", {"resposta": v}
    if caso == "tokens.input":
        return "a", {"tokensGastos": {"input": v, "output": 1, "total": 2}}
    if caso == "opcoes[0]":
        return "a", {"opcoes": [v]}
    if caso == "opcoes":
        return "a", {"opcoes": v}
    if caso == "metadados.k":
        return "a", {"metadados": {"k": v}}
    if caso == "metadados":
        return "a", {"metadados": v}
    if caso == "dadosColetados":
        return "a", {"dadosColetados": v}
    if caso == "dadosColetados.cpf":
        return "a", {"dadosColetados": {"cpf": v}}
    if caso == "_links.self":
        return "a", {"_links": {"self": v}}
    if caso == "_links.self.href":
        return "a", {"_links": {"self": {"href": v}}}
    if caso == "erro.erro":
        return "e", {"erro": v}
    if caso == "erro.extra":
        return "e", {"erro": "e", "extra": v}
    if caso == "fluxos[0].id":
        return "f", [{"id": v, "nome": "n"}]
    if caso == "raiz atendimento":
        return "a", v
    raise AssertionError(caso)


CASOS = [(chave, *chave.split(" = ")) for chave in REF if " = " in chave and not chave.endswith("= data")]


@pytest.mark.parametrize(("chave", "caso", "valor"), CASOS, ids=[c[0] for c in CASOS])
def test_serializacao_igual_a_do_fastify(chave: str, caso: str, valor: str) -> None:
    status, _, esperado = REF[chave].partition(" ")
    schema, corpo = _corpo(caso, VALORES[valor])
    if status == "500":
        with pytest.raises(ErroSerializacao) as erro:
            serializar(SCHEMAS[schema], corpo)
        assert str(erro.value) == json.loads(esperado)["message"]
    else:
        assert serializar(SCHEMAS[schema], corpo) == esperado


def test_ordem_do_schema_e_campo_nao_declarado() -> None:
    corpo = {"_links": {"self": {"href": "/a"}}, "extra": 1, "status": "s", "resposta": "r"}
    assert serializar(ATENDIMENTO, corpo) == REF["ordem e extra"]


def test_erro_sem_additional_properties_descarta_extra() -> None:
    assert serializar(ERRO_SEM, {"erro": "e", "status": "concluido"}) == REF["erro sem additionalProperties com extra"]


def test_erro_com_additional_properties_omite_undefined_e_mantem_null() -> None:
    corpo = {"erro": "e", "status": "concluido", "z": AUSENTE, "n": None}
    assert serializar(ERRO, corpo) == REF["erro com additionalProperties: undefined e null"]


def test_sem_schema_e_json_stringify() -> None:
    assert serializar(None, {"status": "ok"}) == '{"status":"ok"}'
