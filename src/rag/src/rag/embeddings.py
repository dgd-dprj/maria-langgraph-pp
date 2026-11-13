"""Geração de embeddings via Amazon Bedrock, seguindo o guia-maria."""

from __future__ import annotations

from langchain_aws import BedrockEmbeddings

from .settings import carregar_configuracoes


def criar_modelo_embeddings() -> BedrockEmbeddings:
    configuracoes = carregar_configuracoes()
    return BedrockEmbeddings(model_id=configuracoes.modelo_embedding, region_name=configuracoes.aws_region)
