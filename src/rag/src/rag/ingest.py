"""Comando manual de ingestão: `python -m rag.ingest`."""

from __future__ import annotations

from .embeddings import criar_modelo_embeddings
from .retriever import RecuperadorVerde
from .settings import carregar_configuracoes
from .vector_store import ArmazenamentoVetorial


def main() -> None:
    armazenamento = ArmazenamentoVetorial(carregar_configuracoes().database_url)
    armazenamento.abrir()
    try:
        resumo = RecuperadorVerde(armazenamento, criar_modelo_embeddings()).indexar()
        print("Indexação concluída")
        for nome, quantidade in resumo.items():
            print(f"{nome}: {quantidade}")
        print(f"total no pgvector: {armazenamento.contar()}")
    finally:
        armazenamento.fechar()


if __name__ == "__main__":
    main()
