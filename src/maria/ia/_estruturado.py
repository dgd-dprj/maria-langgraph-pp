"""Saída estruturada como em develop: `withStructuredOutput(schema, {includeRaw: true}).withRetry(...)`.

Reproduz o `ChatBedrockConverse` do @langchain/aws 1.4.4, e NÃO o
`with_structured_output` do langchain-aws Python:

- **Sem validação.** O parser de develop (`chat_models.js:781-786`) devolve os
  `args` da ferramenta como vieram; o zod só descreve a saída no prompt. Com
  classe Pydantic, o Python validaria, e um id inventado viraria fallback.
  A ausência de validação é defeito de develop reproduzido de propósito:
  https://github.com/dgd-dprj/maria-langgraph-pp/issues/212
- **Requisição idêntica.** O `toolConfig` vai pronto (a ordem das chaves do
  `toolSpec` é a de develop), e o `inferenceConfig` vazio que o langchain-aws
  Python acrescenta é removido: develop não envia nenhum.
- **Falha de parse não dispara retry.** Vira `parsed: None` dentro da cadeia,
  como o `withFallbacks` do `assembleStructuredOutputPipeline`; só erro do
  modelo (HTTP) é retentado.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from botocore.exceptions import ClientError
from langchain_aws import ChatBedrockConverse
from langchain_aws.utils import create_aws_client
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from maria.shared import _js
from maria.shared._js import AUSENTE
from maria.shared.bedrock import CONFIG_BOTOCORE, cota_como_sdk_js
from maria.shared.logger import serializar_erro

# Absorve instabilidade passageira do Bedrock (throttle, timeout de rede) antes
# de cair no fallback (issue #46). Em develop cada módulo declara o seu; o valor
# é o mesmo nos seis.
TENTATIVAS_RETRY_IA = 3

NOME_FERRAMENTA = "extract"
DESCRICAO_FERRAMENTA = "A function available to call."
ESQUEMA_JSON = "https://json-schema.org/draft/2020-12/schema"


class _ConverseComoDevelop(ChatBedrockConverse):
    def _converse_params(self, **kwargs: Any) -> dict[str, Any]:
        params = super()._converse_params(**kwargs)
        # Sem temperatura nem maxTokens, o langchain-aws Python ainda manda
        # "inferenceConfig": {}. develop não manda a chave.
        if params.get("inferenceConfig") == {}:
            del params["inferenceConfig"]
        return params


class _ClienteTardio:
    """Cliente boto3 criado no primeiro uso, e não na construção do modelo.

    O langchain-aws Python cria o cliente (e resolve o perfil AWS) no validador
    do `ChatBedrockConverse`, na importação do módulo: com `AWS_PROFILE` de um
    perfil que não existe, a API nem sobe. O SDK JS de develop só resolve a
    credencial na chamada: a API sobe, e cada chamada ao modelo falha e cai no
    fallback (executado em develop @ 1157a6d: relato vira `outros`, com
    `CredentialsProviderError` no log). Achado no teste do guia de rodar
    localmente (#246). O cliente é o mesmo que o langchain-aws criaria, com os
    mesmos argumentos; se a criação falha, a próxima chamada tenta de novo."""

    def __init__(self, servico: str) -> None:
        self._servico = servico
        self._modelo: ChatBedrockConverse | None = None
        self._cliente: Any = None
        self._trava = threading.Lock()

    def _criar(self) -> Any:
        modelo = self._modelo
        assert modelo is not None
        with cota_como_sdk_js():
            return create_aws_client(
                service_name=self._servico,
                region_name=modelo.region_name,
                credentials_profile_name=modelo.credentials_profile_name,
                aws_access_key_id=modelo.aws_access_key_id,
                aws_secret_access_key=modelo.aws_secret_access_key,
                aws_session_token=modelo.aws_session_token,
                endpoint_url=modelo.endpoint_url,
                config=modelo._get_effective_config(),
                api_key=modelo.bedrock_api_key,
            )

    def __getattr__(self, nome: str) -> Any:
        if nome.startswith("_"):
            raise AttributeError(nome)
        with self._trava:
            if self._cliente is None:
                self._cliente = self._criar()
        return getattr(self._cliente, nome)


def criar_modelo() -> ChatBedrockConverse:
    """Um por módulo, na importação, como cada `new ChatBedrockConverse` de develop."""
    cliente, controle = _ClienteTardio("bedrock-runtime"), _ClienteTardio("bedrock")
    modelo = _ConverseComoDevelop(
        model=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=CONFIG_BOTOCORE,
        client=cliente,
        bedrock_client=controle,
    )
    cliente._modelo = controle._modelo = modelo
    return modelo


def esquema_objeto(propriedades: dict[str, Any], obrigatorias: list[str] | None) -> dict[str, Any]:
    """JSON Schema que o zod-to-json-schema de develop gera para um `z.object`."""
    esquema: dict[str, Any] = {"$schema": ESQUEMA_JSON, "type": "object", "properties": propriedades}
    if obrigatorias is not None:
        esquema["required"] = obrigatorias
    esquema["additionalProperties"] = False
    return esquema


def _parsear(raw: Any) -> Any:
    # O RunnableLambda de chat_models.js:782-785.
    chamadas = getattr(raw, "tool_calls", None)
    if not chamadas:
        raise ValueError("No tool calls found in the response.")
    for chamada in chamadas:
        if chamada["name"] == NOME_FERRAMENTA:
            return chamada["args"]
    raise ValueError(f"No tool call found with name {NOME_FERRAMENTA}.")


MENSAGEM_HUMANO_VAZIO = "Invalid message content: empty string. 'human' must contain non-empty content."


def _recusar_humano_vazio(mensagens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """O @langchain/aws 1.4.4 recusa mensagem humana vazia ANTES de enviar
    (`convertHumanMessageToConverseMessage`, `utils/message_inputs.ts:662`), dentro
    do modelo e, portanto, dentro do retry: nenhuma requisição sai, e a função cai
    no próprio fallback. O langchain-aws Python envia a mensagem vazia ao Bedrock.
    Achado na conferência diferencial do orquestrador (relato `""`)."""
    for papel, conteudo in mensagens:
        if papel == "user" and conteudo == "":
            raise ValueError(MENSAGEM_HUMANO_VAZIO)
    return mensagens


def _com_parsed(raw: Any) -> dict[str, Any]:
    try:
        parsed = _parsear(raw)
    except Exception:
        parsed = None
    return {"raw": raw, "parsed": parsed}


async def invocar_estruturado(modelo: ChatBedrockConverse, esquema: dict[str, Any], sistema: str, usuario: str) -> dict[str, Any]:
    """Devolve `{raw, parsed}`; `parsed` é `None` quando a resposta não tem a ferramenta."""
    tool_config = {
        "tools": [{"toolSpec": {"name": NOME_FERRAMENTA, "inputSchema": {"json": esquema}, "description": DESCRICAO_FERRAMENTA}}],
        "toolChoice": {"tool": {"name": NOME_FERRAMENTA}},
    }
    cadeia = (RunnableLambda(_recusar_humano_vazio) | modelo.bind(tool_config=tool_config) | RunnableLambda(_com_parsed)).with_retry(
        stop_after_attempt=TENTATIVAS_RETRY_IA
    )
    return await cadeia.ainvoke([("system", sistema), ("user", usuario)])


def definir_tokens(saida: dict[str, Any], raw: Any) -> None:
    """`tokensEntrada: uso?.input_tokens` etc.: chave ausente quando não há contagem.

    `usage_metadata` é um dict (TypedDict) no Python: ler com getattr daria
    ausente MESMO com a contagem presente (ponto 5 da #208).
    """
    uso = raw.usage_metadata if isinstance(raw, AIMessage) else AUSENTE
    for chave, campo in (("tokensEntrada", "input_tokens"), ("tokensSaida", "output_tokens"), ("tokensTotal", "total_tokens")):
        valor = _js.opt(uso, campo)
        if valor is AUSENTE or valor is None:
            saida.pop(chave, None)
        else:
            saida[chave] = valor


def erro_para_log(erro: BaseException) -> dict[str, str]:
    """O `err` do pino em develop, para um erro do Bedrock.

    No SDK JS, `err.type` é o nome da exceção (`ThrottlingException`) e
    `err.message` é a mensagem do Bedrock. No botocore tudo é `ClientError`, com
    o código e a mensagem dentro de `response["Error"]` (decisão pendente 1 da
    spec do ia, valor provisório). A mensagem é a do Bedrock, como em develop:
    rota 2 da #220.
    """
    serializado = serializar_erro(erro)
    if isinstance(erro, ClientError):
        detalhe = erro.response.get("Error", {})
        serializado["type"] = str(detalhe.get("Code", serializado["type"]))
        serializado["message"] = str(detalhe.get("Message", serializado["message"]))
    return serializado
