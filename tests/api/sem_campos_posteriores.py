"""Campos que a API passou a devolver depois da gravação das fixtures de contrato.

As fixtures (`tests/fixtures/contrato/`) são respostas gravadas da versão TypeScript e ficam congeladas
(MIGRACAO.md, "As respostas gravadas são evidência, não teste de regressão"). Quando a API ganha um campo
novo e opcional, a conferência contra elas tira só esse campo da resposta obtida, e o resto continua
conferido byte a byte. O campo novo é coberto por teste escrito (um por campo, citado abaixo).
"""

from __future__ import annotations

import json

# campo -> issue que o introduziu e teste escrito que o cobre
CAMPOS_POSTERIORES: dict[str, str] = {
    "destino": "#288, tests/api/test_destino.py",
}


def sem_campos_posteriores(corpo: str) -> str:
    """O corpo JSON sem os campos de `CAMPOS_POSTERIORES` (no primeiro nível), na mesma ordem e formato."""
    try:
        dados = json.loads(corpo)
    except ValueError:
        return corpo
    if not isinstance(dados, dict) or not any(campo in dados for campo in CAMPOS_POSTERIORES):
        return corpo
    for campo in CAMPOS_POSTERIORES:
        dados.pop(campo, None)
    return json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
