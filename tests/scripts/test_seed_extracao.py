"""Verificação da transcrição dos 74 fluxos planejados (spec 08, seção 2.3).

O arquivo de dados foi extraído pelo Node (`tests/fixtures/scripts/extrair_seed.mjs`). Aqui a
mesma fonte, o `.ts` de develop guardado byte a byte como fixture, é lida por um leitor próprio
em Python. Os dois caminhos precisam concordar registro a registro. Palavra-chave perdida não
quebra nenhum outro teste: é este que pega.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.scripts.leitor_literal_ts import LiteralInvalido, ler_dados_seed

RAIZ = Path(__file__).resolve().parents[2]
FIXTURE = RAIZ / "tests" / "fixtures" / "scripts" / "seedFluxosPlanejados-1157a6d.ts"
DADOS = RAIZ / "scripts" / "dados" / "fluxos_planejados.json"

# `git rev-parse 1157a6d:scripts/seedFluxosPlanejados.ts` em develop. Se o seed mudar em
# develop (por exemplo, pela #249), a fixture, este id e o arquivo de dados mudam juntos.
BLOB_DEVELOP = "265f1df4f64c5a34abf9e01ce421efa4822dc2e2"
TOTAL_REGISTROS = 74
TOTAL_PALAVRAS_CHAVE = 1744  # executado no literal de 1157a6d com o Node (spec 08, seção 2.1)


def _id_blob_git(conteudo: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(conteudo) + conteudo).hexdigest()


@pytest.fixture(scope="module")
def literal() -> list[dict[str, Any]]:
    return ler_dados_seed(FIXTURE.read_bytes().decode("utf-8"))


@pytest.fixture(scope="module")
def extraido() -> list[dict[str, Any]]:
    dados: list[dict[str, Any]] = json.loads(DADOS.read_bytes().decode("utf-8"))
    return dados


def test_fixture_e_o_blob_de_develop() -> None:
    assert _id_blob_git(FIXTURE.read_bytes()) == BLOB_DEVELOP


def test_74_ids_unicos_nos_dois_lados(literal: list[dict[str, Any]], extraido: list[dict[str, Any]]) -> None:
    for dados in (literal, extraido):
        assert len(dados) == TOTAL_REGISTROS
        assert len({d["id"] for d in dados}) == TOTAL_REGISTROS


def test_conjunto_de_ids_identico(literal: list[dict[str, Any]], extraido: list[dict[str, Any]]) -> None:
    assert {d["id"] for d in literal} == {d["id"] for d in extraido}


def test_total_de_palavras_chave_identico(literal: list[dict[str, Any]], extraido: list[dict[str, Any]]) -> None:
    assert sum(len(d["palavrasChave"]) for d in literal) == TOTAL_PALAVRAS_CHAVE
    assert sum(len(d["palavrasChave"]) for d in extraido) == TOTAL_PALAVRAS_CHAVE


def test_cada_registro_igual_campo_a_campo_e_na_mesma_ordem(literal: list[dict[str, Any]], extraido: list[dict[str, Any]]) -> None:
    # Compara a lista de pares (chave, valor): pega valor diferente, chave a mais ou a menos
    # (inclusive `mensagemFixa: null` no lugar da chave ausente), ordem das palavras-chave e
    # ordem dos registros. Comparação de str é por code point: acento em NFD não passa.
    assert [list(d.items()) for d in extraido] == [list(d.items()) for d in literal]


def test_mensagens_fixas_so_em_trabalhista_e_loas(extraido: list[dict[str, Any]]) -> None:
    com_mensagem = {d["idCategoriaAssuntoVerde"]: d["nome"] for d in extraido if "mensagemFixa" in d}
    assert com_mensagem == {10085: "reclamação trabalhista", 10092: "loas"}


def test_tipos_dos_campos(extraido: list[dict[str, Any]]) -> None:
    for d in extraido:
        assert set(d) <= {"id", "nome", "descricao", "idCategoriaAssuntoVerde", "palavrasChave", "mensagemFixa"}
        assert isinstance(d["idCategoriaAssuntoVerde"], int)
        assert all(isinstance(p, str) for p in d["palavrasChave"])


@pytest.mark.parametrize(
    "literal_ruim",
    [
        'const DADOS_SEED: FluxoPlanejado[] = [{ id: "a\\nb" }];',
        'const DADOS_SEED: FluxoPlanejado[] = [{ id: "a\\u00e9" }];',
        'const DADOS_SEED: FluxoPlanejado[] = [{ id: "a\\\\b" }];',
        "const DADOS_SEED: FluxoPlanejado[] = [{ id: 'a' }];",
        "const DADOS_SEED: FluxoPlanejado[] = [{ id: `a` }];",
        'const DADOS_SEED: FluxoPlanejado[] = [{ id: "a" }, // comentário\n];',
        "const DADOS_SEED: FluxoPlanejado[] = [{ n: 1.5 }];",
        "const DADOS_SEED: FluxoPlanejado[] = [{ n: undefined }];",
        'const DADOS_SEED: FluxoPlanejado[] = [{ id: "a", id: "b" }];',
        'const DADOS_SEED: FluxoPlanejado[] = [{ id: "a" }]',
        'const DADOS_SEED: FluxoPlanejado[] = [...outros, { id: "a" }];',
    ],
)
def test_leitor_recusa_construcao_que_nao_cobre(literal_ruim: str) -> None:
    with pytest.raises(LiteralInvalido):
        ler_dados_seed(literal_ruim)


def test_leitor_le_o_escape_de_aspas() -> None:
    assert ler_dados_seed('const DADOS_SEED: FluxoPlanejado[] = [{ p: ["\\"sofri"] }];') == [{"p": ['"sofri']}]


def test_aspa_solta_de_develop_preservada(extraido: list[dict[str, Any]]) -> None:
    # Defeito de develop reproduzido (spec 08, achado B4): a aspa vem do literal, não da extração.
    (registro,) = [d for d in extraido if d["nome"] == "direitos e diversidade"]
    assert '"sofri preconceito' in registro["palavrasChave"]


def test_leitor_aceita_virgula_final() -> None:
    fonte = 'const DADOS_SEED: FluxoPlanejado[] = [\n  { id: "a", n: 1, l: ["x", "y",], },\n];'
    assert ler_dados_seed(fonte) == [{"id": "a", "n": 1, "l": ["x", "y"]}]
