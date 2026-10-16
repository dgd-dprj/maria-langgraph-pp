"""Validação do corpo como o ajv do Fastify 5.12.1 (`coerceTypes: "array"`, `allErrors: false`).

Cobre o subconjunto de JSON Schema que as rotas usam: objeto com propriedades,
`string` com `format: "uuid"` e objeto livre (`additionalProperties: true`).
Comportamento executado no app de develop @ 1157a6d (casos de borda do
pipeline, registrados no PR):

- o corpo precisa ser objeto: `null`, lista, texto e corpo ausente dão
  "body must be object";
- `string` converte número (`12345` vira `"12345"`, `1e-7` vira `"1e-7"`),
  booleano (`"true"`), `null` (`""`) e lista de um item (`["b3"]` vira `"b3"`);
  objeto e lista de outro tamanho são erro;
- `format: "uuid"` é conferido depois da conversão, sem diferenciar caixa e
  aceitando o prefixo `urn:uuid:`;
- objeto: `null` e lista são erro;
- a primeira falha, na ordem das propriedades do schema, encerra a validação.

O corpo convertido é o que o handler recebe.
"""

from __future__ import annotations

import re
from typing import Any

from maria.shared._js import AUSENTE, numero_para_texto

Schema = dict[str, Any]

# Formato "uuid" do ajv-formats.
_UUID = re.compile(r"^(?:urn:uuid:)?[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$", re.IGNORECASE)

_NAO_CONVERTE = object()


class ErroValidacao(Exception):
    """FST_ERR_VALIDATION: 400, com a mensagem e a entrada `validation` do ajv."""

    def __init__(self, caminho: str, schema_path: str, palavra: str, parametros: dict[str, str], mensagem: str) -> None:
        self.validacao = {
            "instancePath": caminho,
            "schemaPath": schema_path,
            "keyword": palavra,
            "params": parametros,
            "message": mensagem,
        }
        super().__init__(f"body{caminho} {mensagem}")


def _para_texto(valor: Any) -> Any:
    if isinstance(valor, str):
        return valor
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, int | float):
        return numero_para_texto(valor)
    if valor is None:
        return ""
    if isinstance(valor, list) and len(valor) == 1 and not isinstance(valor[0], list | dict):
        return _para_texto(valor[0])
    return _NAO_CONVERTE


def validar_corpo(schema: Schema, corpo: Any) -> dict[str, Any]:
    if not isinstance(corpo, dict) or corpo is AUSENTE:
        raise ErroValidacao("", "#/type", "type", {"type": "object"}, "must be object")
    for nome, sub in schema.get("properties", {}).items():
        if nome not in corpo:
            continue
        caminho = f"/{nome}"
        base = f"#/properties/{nome}"
        tipo = sub.get("type")
        if tipo == "string":
            convertido = _para_texto(corpo[nome])
            if convertido is _NAO_CONVERTE:
                raise ErroValidacao(caminho, f"{base}/type", "type", {"type": "string"}, "must be string")
            corpo[nome] = convertido
            if sub.get("format") == "uuid" and not _UUID.match(convertido):
                raise ErroValidacao(caminho, f"{base}/format", "format", {"format": "uuid"}, 'must match format "uuid"')
        elif tipo == "object" and not isinstance(corpo[nome], dict):
            raise ErroValidacao(caminho, f"{base}/type", "type", {"type": "object"}, "must be object")
    return corpo
