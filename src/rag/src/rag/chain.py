"""Cadeia de geração: coexiste o modo de explicação da API Verde com o modo de dúvidas da pessoa (2 agentes)."""

from __future__ import annotations

import time
from typing import Any, Literal

from langchain_aws import ChatBedrockConverse

from .prompt import (
    PROMPT_CONFERENCIA,
    PROMPT_DUVIDAS,
    PROMPT_ESCOLHA_MODO,
    PROMPT_EXPLICACAO,
    RECUSA_PADRAO_DUVIDAS,
    RECUSA_PADRAO_VERDE,
)
from .retriever import RecuperadorVerde, criar_documento_de_mensagem
from .settings import carregar_configuracoes

ModoRag = Literal["verde", "duvidas"]
ModoEntrada = Literal["auto", "verde", "duvidas"]

_SINAIS_RECUSA_DUVIDA = (
    "não sei responder isso",
    "vou passar a sua conversa para o nosso atendimento humano",
    "não encontrei informação suficiente",
    "não foi possível confirmar",
)


def _extrair_texto_e_tokens(resposta: Any) -> tuple[str, int, int]:
    conteudo = getattr(resposta, "content", resposta)
    if isinstance(conteudo, list):
        conteudo = " ".join(str(bloco.get("text", "")) for bloco in conteudo if isinstance(bloco, dict))
    texto = str(conteudo).strip()
    uso = getattr(resposta, "usage_metadata", None) or {}
    tokens_entrada = int(uso.get("input_tokens", 0) or 0)
    tokens_saida = int(uso.get("output_tokens", 0) or 0)
    return texto, tokens_entrada, tokens_saida


def _formatar_fontes(fontes_relevantes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": fonte["id"],
            "fonte": fonte["fonte"],
            "endpoint": fonte["endpoint"],
            "metodo": fonte["metodo"],
            "assunto": fonte["assunto"],
            "similaridade": round(float(fonte["similaridade"]), 4),
        }
        for fonte in fontes_relevantes
    ]


def _montar_contexto_duvidas(fontes_relevantes: list[dict[str, Any]]) -> str:
    return "\n\n---\n\n".join(f"Fonte: {fonte['fonte']} (ID: {fonte['id']})\n{fonte['conteudo']}" for fonte in fontes_relevantes)


def _eh_recusa_duvida(texto: str) -> bool:
    normalizado = " ".join(texto.casefold().split())
    if normalizado == RECUSA_PADRAO_DUVIDAS.casefold():
        return True
    return normalizado.startswith("não sei responder isso")


def _interpretar_veredito_conferencia(texto_conferencia: str) -> bool:
    linhas = [linha.strip() for linha in texto_conferencia.splitlines() if linha.strip()]
    for linha in linhas:
        superior = linha.upper()
        if superior.startswith("VEREDITO:"):
            valor = superior.removeprefix("VEREDITO:").strip()
            if "RECUSAR" in valor or "REPROVAR" in valor or "NAO" in valor or "NÃO" in valor:
                return False
            if "APROVAR" in valor or "SIM" in valor:
                return True
    superior_total = texto_conferencia.upper()
    if "VEREDITO: APROVAR" in superior_total and "VEREDITO: RECUSAR" not in superior_total:
        return True
    return False


class ExplicadorVerde:
    """Serviço RAG com dois modos coexistentes:
    - `verde`: explica mensagens técnicas de requisições da API Verde.
    - `duvidas`: responde dúvidas da pessoa com um segundo agente conferidor e recusa padronizada.
    """

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

    def escolher_modo(
        self,
        mensagem: str,
        endpoint: str = "",
        metodo: str = "",
        status_http: int | None = None,
    ) -> dict[str, Any]:
        """Permite que o modelo escolha qual modo assumir (`verde` ou `duvidas`) de acordo com a situação."""
        inicio = time.perf_counter()
        tem_contexto_http = bool(endpoint.strip() or metodo.strip() or status_http is not None)
        prompt = PROMPT_ESCOLHA_MODO.format(
            mensagem=mensagem.strip(),
            endpoint=endpoint.strip() or "(não informado)",
            metodo=metodo.strip().upper() or "(não informado)",
            status_http=status_http if status_http is not None else "(não informado)",
        )
        try:
            resposta = self.modelo.invoke(prompt)
            texto, tokens_entrada, tokens_saida = _extrair_texto_e_tokens(resposta)
            decisao = texto.upper()
            if "DUVIDA" in decisao or "DÚVIDA" in decisao:
                modo: ModoRag = "duvidas"
            elif "VERDE" in decisao:
                modo = "verde"
            else:
                modo = "verde" if tem_contexto_http else "duvidas"
        except Exception:
            tokens_entrada = 0
            tokens_saida = 0
            texto = ""
            modo = "verde" if tem_contexto_http else "duvidas"

        return {
            "modo": modo,
            "resposta_roteador": texto,
            "tokens_entrada": tokens_entrada,
            "tokens_saida": tokens_saida,
            "tempo_s": round(time.perf_counter() - inicio, 4),
        }

    def explicar_verde(
        self,
        mensagem: str,
        endpoint: str = "",
        metodo: str = "",
        status_http: int | None = None,
    ) -> dict[str, Any]:
        """Modo original do RAG: explica mensagens técnicas das requisições da API Verde."""
        inicio = time.perf_counter()
        consulta = criar_documento_de_mensagem(mensagem, endpoint, metodo, status_http)
        fontes = self.recuperador.buscar(consulta, limite=3)
        fontes_relevantes = [fonte for fonte in fontes if float(fonte["similaridade"]) >= self.limiar_similaridade]
        if not fontes_relevantes:
            tempo_s = round(time.perf_counter() - inicio, 4)
            return {
                "modo": "verde",
                "explicacao": RECUSA_PADRAO_VERDE,
                "resposta": RECUSA_PADRAO_VERDE,
                "acao": "recusou",
                "respondeu": False,
                "recusou": True,
                "tempo_s": tempo_s,
                "tokens_entrada": 0,
                "tokens_saida": 0,
                "fontes": [],
                "trechos_usados": [],
                "similaridade": None,
            }

        contexto = "\n\n---\n\n".join(str(fonte["conteudo"]) for fonte in fontes_relevantes)
        prompt = PROMPT_EXPLICACAO.format(mensagem=consulta, contexto=contexto)
        resposta = self.modelo.invoke(prompt)
        explicacao, tokens_entrada, tokens_saida = _extrair_texto_e_tokens(resposta)
        fontes_formatadas = _formatar_fontes(fontes_relevantes)
        similaridade_topo = round(float(fontes_relevantes[0]["similaridade"]), 4)
        tempo_s = round(time.perf_counter() - inicio, 4)
        recusou = any(sinal in explicacao.casefold() for sinal in _SINAIS_RECUSA_DUVIDA)
        return {
            "modo": "verde",
            "explicacao": explicacao,
            "resposta": explicacao,
            "acao": "recusou" if recusou else "respondeu",
            "respondeu": not recusou,
            "recusou": recusou,
            "tempo_s": tempo_s,
            "tokens_entrada": tokens_entrada,
            "tokens_saida": tokens_saida,
            "fontes": fontes_formatadas,
            "trechos_usados": fontes_formatadas,
            "similaridade": similaridade_topo,
        }

    def conferir_resposta(
        self,
        pergunta: str,
        resposta_proposta: str,
        fontes_relevantes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Segundo agente: recebe a resposta e os trechos, confere se cada afirmação está nos trechos."""
        inicio = time.perf_counter()
        contexto = _montar_contexto_duvidas(fontes_relevantes)
        prompt = PROMPT_CONFERENCIA.format(
            pergunta=pergunta.strip(),
            contexto=contexto,
            resposta=resposta_proposta.strip(),
        )
        resposta = self.modelo.invoke(prompt)
        texto_conferencia, tokens_entrada, tokens_saida = _extrair_texto_e_tokens(resposta)
        aprovada = _interpretar_veredito_conferencia(texto_conferencia)
        return {
            "aprovada": aprovada,
            "veredito": "APROVAR" if aprovada else "RECUSAR",
            "avaliacao": texto_conferencia,
            "tokens_entrada": tokens_entrada,
            "tokens_saida": tokens_saida,
            "tempo_s": round(time.perf_counter() - inicio, 4),
        }

    def responder_duvida(self, pergunta: str) -> dict[str, Any]:
        """Modo 'dúvidas da pessoa': Agente 1 responde com prompt próprio e Agente 2 confere nos trechos."""
        inicio = time.perf_counter()
        consulta = pergunta.strip()
        fontes = self.recuperador.buscar(consulta, limite=3)
        fontes_relevantes = [fonte for fonte in fontes if float(fonte["similaridade"]) >= self.limiar_similaridade]
        fontes_formatadas = _formatar_fontes(fontes_relevantes)

        if not fontes_relevantes:
            tempo_s = round(time.perf_counter() - inicio, 4)
            return {
                "modo": "duvidas",
                "resposta": RECUSA_PADRAO_DUVIDAS,
                "explicacao": RECUSA_PADRAO_DUVIDAS,
                "acao": "recusou",
                "respondeu": False,
                "recusou": True,
                "motivo_recusa": "sem_trechos_acima_do_limiar",
                "tempo_s": tempo_s,
                "tokens_entrada": 0,
                "tokens_saida": 0,
                "trechos_usados": [],
                "fontes": [],
                "similaridade": None,
                "chamadas": {
                    "agente_respondedor": None,
                    "agente_conferidor": None,
                },
            }

        contexto = _montar_contexto_duvidas(fontes_relevantes)
        prompt_agente_1 = PROMPT_DUVIDAS.format(
            pergunta=consulta,
            contexto=contexto,
            recusa_padrao=RECUSA_PADRAO_DUVIDAS,
        )
        inicio_a1 = time.perf_counter()
        bruto_a1 = self.modelo.invoke(prompt_agente_1)
        resposta_a1, in_a1, out_a1 = _extrair_texto_e_tokens(bruto_a1)
        tempo_a1 = round(time.perf_counter() - inicio_a1, 4)

        dados_a1 = {
            "resposta": resposta_a1,
            "tokens_entrada": in_a1,
            "tokens_saida": out_a1,
            "tempo_s": tempo_a1,
        }

        similaridade_topo = round(float(fontes_relevantes[0]["similaridade"]), 4)

        # Se o primeiro agente já recusou, garante a frase padrão exata.
        if _eh_recusa_duvida(resposta_a1):
            tempo_total = round(time.perf_counter() - inicio, 4)
            return {
                "modo": "duvidas",
                "resposta": RECUSA_PADRAO_DUVIDAS,
                "explicacao": RECUSA_PADRAO_DUVIDAS,
                "acao": "recusou",
                "respondeu": False,
                "recusou": True,
                "motivo_recusa": "agente_respondedor",
                "tempo_s": tempo_total,
                "tokens_entrada": in_a1,
                "tokens_saida": out_a1,
                "trechos_usados": fontes_formatadas,
                "fontes": fontes_formatadas,
                "similaridade": similaridade_topo,
                "chamadas": {
                    "agente_respondedor": dados_a1,
                    "agente_conferidor": None,
                },
            }

        # Segundo agente confere se cada afirmação da resposta está nos trechos.
        dados_a2 = self.conferir_resposta(
            pergunta=consulta,
            resposta_proposta=resposta_a1,
            fontes_relevantes=fontes_relevantes,
        )
        tokens_entrada_total = in_a1 + int(dados_a2["tokens_entrada"])
        tokens_saida_total = out_a1 + int(dados_a2["tokens_saida"])

        if dados_a2["aprovada"]:
            resposta_final = resposta_a1
            acao = "respondeu"
            respondeu = True
            recusou = False
            motivo_recusa = None
        else:
            resposta_final = RECUSA_PADRAO_DUVIDAS
            acao = "recusou"
            respondeu = False
            recusou = True
            motivo_recusa = "agente_conferidor"

        tempo_total = round(time.perf_counter() - inicio, 4)
        return {
            "modo": "duvidas",
            "resposta": resposta_final,
            "explicacao": resposta_final,
            "acao": acao,
            "respondeu": respondeu,
            "recusou": recusou,
            "motivo_recusa": motivo_recusa,
            "tempo_s": tempo_total,
            "tokens_entrada": tokens_entrada_total,
            "tokens_saida": tokens_saida_total,
            "trechos_usados": fontes_formatadas,
            "fontes": fontes_formatadas,
            "similaridade": similaridade_topo,
            "chamadas": {
                "agente_respondedor": dados_a1,
                "agente_conferidor": dados_a2,
            },
        }

    def explicar(
        self,
        mensagem: str,
        endpoint: str = "",
        metodo: str = "",
        status_http: int | None = None,
        modo: ModoEntrada | None = None,
    ) -> dict[str, Any]:
        """Ponto de entrada unificado que mantém o modo Verde e o modo de dúvidas coexistindo.

        - Quando `modo` é `"verde"` ou `"duvidas"`, executa diretamente o modo solicitado.
        - Quando `modo` é `None` ou `"auto"`, o modelo escolhe qual modo assumir de acordo com a situação.
        """
        inicio = time.perf_counter()
        roteamento: dict[str, Any] | None = None
        if modo in ("verde", "duvidas"):
            modo_efetivo: ModoRag = modo
        else:
            roteamento = self.escolher_modo(mensagem, endpoint, metodo, status_http)
            modo_efetivo = roteamento["modo"]

        if modo_efetivo == "verde":
            resultado = self.explicar_verde(mensagem, endpoint, metodo, status_http)
        else:
            resultado = self.responder_duvida(mensagem)

        if roteamento is not None:
            resultado["roteamento_modo"] = roteamento
            resultado["tokens_entrada_roteador"] = roteamento["tokens_entrada"]
            resultado["tokens_saida_roteador"] = roteamento["tokens_saida"]
            resultado["tempo_total_com_roteamento_s"] = round(time.perf_counter() - inicio, 4)

        return resultado
