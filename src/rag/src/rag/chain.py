"""Cadeia de geração: busca contexto relevante e pede uma explicação fundamentada."""

from __future__ import annotations

from typing import Any

from langchain_aws import ChatBedrockConverse

from .prompt import PROMPT_EXPLICACAO
from .retriever import RecuperadorVerde, criar_documento_de_mensagem
from .settings import carregar_configuracoes


class ExplicadorVerde:
    def __init__(self, recuperador: RecuperadorVerde) -> None:
        configuracoes = carregar_configuracoes()
        self.recuperador = recuperador
        self.limiar_similaridade = configuracoes.limiar_similaridade
        self.modelo = ChatBedrockConverse(
            model=configuracoes.modelo_chat,
            region_name=configuracoes.aws_region,
            temperature=0,
            max_tokens=500,
        )

    def explicar(self, mensagem: str, endpoint: str = "", metodo: str = "", status_http: int | None = None) -> dict[str, Any]:
        consulta = criar_documento_de_mensagem(mensagem, endpoint, metodo, status_http)
        fontes = self.recuperador.buscar(consulta, limite=3)
        fontes_relevantes = [fonte for fonte in fontes if float(fonte["similaridade"]) >= self.limiar_similaridade]
        if not fontes_relevantes:
            return {
                "explicacao": (
                    "Não encontrei informação suficiente na documentação da API para explicar esta mensagem. "
                    "A equipe que acompanha seu atendimento poderá verificar o que aconteceu."
                ),
                "fontes": [],
                "similaridade": None,
            }

        contexto = "\n\n---\n\n".join(str(fonte["conteudo"]) for fonte in fontes_relevantes)
        prompt = PROMPT_EXPLICACAO.format(mensagem=consulta, contexto=contexto)
        resposta = self.modelo.invoke(prompt)
        explicacao = resposta.content
        if isinstance(explicacao, list):
            explicacao = " ".join(str(bloco.get("text", "")) for bloco in explicacao if isinstance(bloco, dict))
        return {
            "explicacao": str(explicacao).strip(),
            "fontes": [
                {
                    "id": fonte["id"],
                    "fonte": fonte["fonte"],
                    "endpoint": fonte["endpoint"],
                    "metodo": fonte["metodo"],
                    "assunto": fonte["assunto"],
                    "similaridade": round(float(fonte["similaridade"]), 4),
                }
                for fonte in fontes_relevantes
            ],
            "similaridade": round(float(fontes_relevantes[0]["similaridade"]), 4),
        }
