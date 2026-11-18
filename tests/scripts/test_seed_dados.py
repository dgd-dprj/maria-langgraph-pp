"""O arquivo de dados do seed (`scripts/dados/fluxos_planejados.json`), que é a fonte desde a #253.

Até 2026-11-18, `tests/scripts/test_seed_extracao.py` conferia este arquivo, byte a byte, contra o literal do seed de
develop em TypeScript (`1157a6d`). Com a decisão da #253 (o arquivo vale, e toda mudança de dado entra por PR aqui),
essa conferência perdeu o sentido e foi aposentada: ela impedia exatamente a mudança que a regra pede. Ficam as
conferências do próprio arquivo.
"""

import json
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[2]
DADOS = RAIZ / "scripts" / "dados" / "fluxos_planejados.json"
CAMPOS = {"id", "nome", "descricao", "idCategoriaAssuntoVerde", "palavrasChave", "mensagemFixa"}


@pytest.fixture(scope="module")
def dados() -> list[dict[str, Any]]:
    lidos: list[dict[str, Any]] = json.loads(DADOS.read_bytes().decode("utf-8"))
    return lidos


def test_ids_unicos(dados: list[dict[str, Any]]) -> None:
    assert len({d["id"] for d in dados}) == len(dados)


def test_tipos_dos_campos(dados: list[dict[str, Any]]) -> None:
    for d in dados:
        assert set(d) <= CAMPOS
        assert {"id", "nome", "descricao", "idCategoriaAssuntoVerde", "palavrasChave"} <= set(d)
        assert isinstance(d["idCategoriaAssuntoVerde"], int) and not isinstance(d["idCategoriaAssuntoVerde"], bool)
        assert isinstance(d["palavrasChave"], list) and all(isinstance(p, str) for p in d["palavrasChave"])
        # Sem mensagem, a chave fica ausente (e não `null`): é o que o seed compara com a coluna vazia.
        assert d.get("mensagemFixa", "ausente") is not None


def test_aspa_solta_de_develop_preservada(dados: list[dict[str, Any]]) -> None:
    # Defeito de develop reproduzido (spec 08, achado B4): a aspa vem do literal original. Corrigir é um PR de dado.
    (registro,) = [d for d in dados if d["nome"] == "direitos e diversidade"]
    assert '"sofri preconceito' in registro["palavrasChave"]
