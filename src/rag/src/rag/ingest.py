"""Comando manual de ingestão: `python -m rag.ingest` com acompanhamento de progresso."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from typing import TextIO

from .embeddings import criar_modelo_embeddings
from .progresso import CallbackProgresso, ProgressoIngest
from .retriever import RecuperadorVerde
from .settings import carregar_configuracoes
from .vector_store import ArmazenamentoVetorial


def _hora_atual() -> str:
    return datetime.now(UTC).astimezone().strftime("%H:%M:%S")


def criar_formatador_terminal(stream: TextIO = sys.stdout, silencioso: bool = False) -> CallbackProgresso:
    """Cria um callback de progresso formatado para exibição amigável no terminal."""
    etapa_anterior = ""

    def callback(progresso: ProgressoIngest) -> None:
        nonlocal etapa_anterior
        if silencioso:
            return

        hora = _hora_atual()
        etapa = progresso.etapa

        if etapa == "descoberta" and etapa != etapa_anterior:
            stream.write(f"\n[{hora}] [1/4] Descoberta: {progresso.mensagem}\n")
            stream.flush()
        elif etapa == "carregamento":
            if progresso.arquivo_atual and progresso.atual > 0:
                total_str = f"/{progresso.total}" if progresso.total else ""
                stream.write(f"[{hora}]   -> [{progresso.atual:2d}{total_str}] {progresso.mensagem}\n")
                stream.flush()
        elif etapa == "fragmentacao" and etapa != etapa_anterior:
            stream.write(f"[{hora}]   -> {progresso.mensagem}\n")
            stream.flush()
        elif etapa == "comparacao" and etapa != etapa_anterior:
            stream.write(f"\n[{hora}] [2/4] Verificação de integridade no pgvector...\n")
            if progresso.detalhes:
                total = progresso.detalhes.get("total_documentos", progresso.total)
                ja = progresso.detalhes.get("ja_indexados", 0)
                pendentes = progresso.detalhes.get("pendentes", 0)
                stream.write(f"[{hora}]       Total de fragmentos : {total}\n")
                stream.write(f"[{hora}]       Já indexados        : {ja}\n")
                stream.write(f"[{hora}]       Pendentes de cálculo: {pendentes}\n")
            stream.flush()
        elif etapa == "embeddings":
            if etapa != etapa_anterior:
                stream.write(f"\n[{hora}] [3/4] Gerando embeddings no Amazon Bedrock...\n")
            porcentagem = (progresso.atual / progresso.total * 100) if progresso.total > 0 else 0.0
            lote_info = ""
            if "lote" in progresso.detalhes and "total_lotes" in progresso.detalhes:
                lote_info = f"[Lote {progresso.detalhes['lote']}/{progresso.detalhes['total_lotes']}] "
            stream.write(f"[{hora}]       {lote_info}{progresso.atual}/{progresso.total} ({porcentagem:5.1f}%) concluídos\n")
            stream.flush()
        elif etapa == "persistindo" and etapa != etapa_anterior:
            stream.write(f"\n[{hora}] [4/4] {progresso.mensagem}\n")
            stream.flush()

        etapa_anterior = etapa

    return callback


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa a ingestão e indexação vetorial dos documentos da API Verde.")
    parser.add_argument("--pasta", type=str, default=None, help="Caminho para a pasta de documentos a indexar.")
    parser.add_argument("--lote", type=int, default=25, help="Tamanho do lote para geração de embeddings (padrão: 25).")
    parser.add_argument("--silencioso", action="store_true", help="Oprime saída detalhada de progresso.")
    args = parser.parse_args()

    inicio = time.time()
    print("=" * 70)
    print("Iniciando ingestão RAG da API Verde")
    print("=" * 70)

    callback_progresso = criar_formatador_terminal(silencioso=args.silencioso)
    armazenamento = ArmazenamentoVetorial(carregar_configuracoes().database_url)
    armazenamento.abrir()
    try:
        recuperador = RecuperadorVerde(armazenamento, criar_modelo_embeddings())
        resumo = recuperador.indexar(
            pasta=args.pasta,
            callback_progresso=callback_progresso,
            tamanho_lote=args.lote,
        )
        duracao = round(time.time() - inicio, 2)
        total_no_banco = armazenamento.contar()

        print("\n" + "=" * 70)
        print(f"Indexação concluída com sucesso em {duracao}s!")
        print("-" * 70)
        print(f"  - Documentos no índice     : {resumo.get('documentos', 0)}")
        print(f"  - Novos embeddings gerados : {resumo.get('embeddings_gerados', 0)}")
        print(f"  - Trechos reaproveitados   : {resumo.get('já_indexados', 0)}")
        print(f"  - Total atual no pgvector  : {total_no_banco}")
        print("=" * 70)
    except Exception as erro:
        print(f"\n[ERRO] Falha durante a ingestão: {erro}", file=sys.stderr)
        sys.exit(1)
    finally:
        armazenamento.fechar()


if __name__ == "__main__":
    main()
