"""Os scripts ficam em `scripts/`, fora do pacote `maria` (spec 08, D-2). Os testes os
importam pelo nome do arquivo, como o `uv run python scripts/<nome>.py` os roda."""

import sys
from pathlib import Path

from tests.shared.conftest import banco_de_negocio, stores_limpas

__all__ = ["banco_de_negocio", "stores_limpas"]

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
