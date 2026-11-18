"""Configurações locais do serviço RAG."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PASTA_PROJETO = Path(__file__).resolve().parents[2]
load_dotenv(PASTA_PROJETO / ".env.rag")

# Um valor vazio no arquivo de exemplo não deve substituir o perfil padrão AWS.
if not os.getenv("AWS_PROFILE", "").strip():
    os.environ.pop("AWS_PROFILE", None)


@dataclass(frozen=True, slots=True)
class Configuracoes:
    database_url: str
    aws_region: str
    modelo_chat: str
    modelo_embedding: str
    limiar_similaridade: float


def carregar_configuracoes() -> Configuracoes:
    return Configuracoes(
        database_url=os.getenv("DATABASE_URL", "postgresql://rag_user:rag_local_password@127.0.0.1:55433/rag_db"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        modelo_chat=os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0"),
        modelo_embedding=os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"),
        limiar_similaridade=float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.25")),
    )
