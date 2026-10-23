"""Execução do orquestrador em testes, como o `graph.test.ts` de develop.

Checkpointer em memória (fixture do fluxos). Em `APP_ENV=test`, o retrieval usa
o embedding falso em memória e a classificação, a desambiguação e a
sumarização ficam nos mocks do ia (`MOCK_CLASSIFICACAO_FLOWIDS`,
`MOCK_SUMARIZACAO_RESUMO`).

Para a saída do modelo sem validação (#212), `Modelo` troca as três funções de
IA no módulo do grafo por roteiros e guarda o texto que cada uma recebeu.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from maria.orquestrador import graph
from maria.shared.embeddings_fluxos import buscar_candidatos
from tests.fluxos.conftest import checkpointer  # noqa: F401

# Fixture do Bedrock falso do ia, para o teste de ponta a ponta da saída do modelo.
from tests.ia.conftest import bedrock  # noqa: F401


@dataclass
class Modelo:
    classificacoes: list[dict[str, Any]] = field(default_factory=list)
    perguntas: list[dict[str, Any]] = field(default_factory=list)
    resumos: list[dict[str, Any]] = field(default_factory=list)
    textos_classificados: list[Any] = field(default_factory=list)
    textos_desambiguados: list[Any] = field(default_factory=list)
    textos_sumarizados: list[Any] = field(default_factory=list)
    retrievals: int = 0

    @staticmethod
    def _proximo(fila: list[dict[str, Any]]) -> dict[str, Any]:
        """Responde na ordem; o último se repete depois que a fila acaba."""
        return dict(fila.pop(0) if len(fila) > 1 else fila[0])


@pytest.fixture
def modelo(monkeypatch: pytest.MonkeyPatch) -> Iterator[Modelo]:
    m = Modelo(perguntas=[{"pergunta": "Pergunta da IA?", "viaIA": True}], resumos=[{"resumo": "resumo", "viaIA": True}])

    async def classificar(texto: Any, pool: Any) -> dict[str, Any]:
        m.textos_classificados.append(texto)
        return Modelo._proximo(m.classificacoes)

    async def desambiguar(texto: Any, candidatos: Any) -> dict[str, Any]:
        m.textos_desambiguados.append(texto)
        return Modelo._proximo(m.perguntas)

    async def sumarizar(texto: Any) -> dict[str, Any]:
        m.textos_sumarizados.append(texto)
        return Modelo._proximo(m.resumos)

    async def buscar(mensagem: str, k: int, catalogo: Any) -> Any:
        m.retrievals += 1
        return await buscar_candidatos(mensagem, k, catalogo)

    monkeypatch.setattr(graph, "classificar_fluxos_plausiveis", classificar)
    monkeypatch.setattr(graph, "gerar_pergunta_desambiguacao", desambiguar)
    monkeypatch.setattr(graph, "sumarizar_relato", sumarizar)
    monkeypatch.setattr(graph, "buscar_candidatos", buscar)
    yield m
