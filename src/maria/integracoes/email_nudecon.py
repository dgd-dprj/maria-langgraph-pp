"""Cliente da função Lambda `maria-email-nudecon` (envia ao NUDECON o e-mail com os dados e as imagens, #345 e #405).

Contrato da função: `docs/contrato.md` do repositório `dgd-dprj/maria-email-nudecon`.

Regras que importam aqui:
- O envio é idempotente por `protocolo`: repetir a chamada com o mesmo protocolo não manda outro e-mail.
  Por isso 5xx, 409 (envio igual em andamento) e falha de rede são repetidos com o MESMO protocolo.
- O fluxo é de urgência: qualquer falha volta como `ok=False`, e o fluxo leva a pessoa ao atendimento humano.
- Os links das imagens têm token na URL: são segredo. O log leva só protocolo, tentativa, status e tipo do erro,
  nunca os dados, as URLs nem a chave.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from maria.integracoes.cliente_http import obter_cliente_http
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger

# A Tykhe espera a resposta da Maria por até 30 s (#344): o orçamento da chamada inteira cabe aí.
PRAZO_TOTAL_S = 25.0
PRAZO_TENTATIVA_S = 15.0
TENTATIVAS = 3
TAMANHO_MAXIMO_VALOR = 2000  # limite de cada valor em `dados` no contrato da função


@dataclass(frozen=True)
class ResultadoEmail:
    ok: bool
    repetido: bool = False
    # Só para log e testes: `nao_configurado`, `http_<status>`, `prazo` ou `rede`. Nunca texto da resposta.
    motivo: str | None = None


def _configuracao() -> tuple[str, str] | None:
    # Lidos a cada chamada (e não na importação): o segredo pode chegar depois do boot e os testes trocam o ambiente.
    url = os.environ.get("EMAIL_NUDECON_URL", "").strip()
    chave = os.environ.get("EMAIL_NUDECON_CHAVE", "").strip()
    return (url, chave) if url and chave else None


def _agora_ms() -> int:
    return time.time_ns() // 1_000_000


def _repetir(status: int) -> bool:
    return status >= 500 or status == 409


def _corpo(protocolo: str, dados: Mapping[str, str], imagens: Mapping[str, str] | None) -> dict[str, Any]:
    corpo: dict[str, Any] = {
        "protocolo": protocolo,
        "dados": {rotulo: valor[:TAMANHO_MAXIMO_VALOR] for rotulo, valor in dados.items()},
    }
    if imagens:
        corpo["imagens"] = dict(imagens)
    return corpo


async def enviar_email_nudecon(protocolo: str, dados: Mapping[str, str], imagens: Mapping[str, str] | None = None) -> ResultadoEmail:
    configuracao = _configuracao()
    if configuracao is None:
        logger.error(
            "[email-nudecon] URL ou chave da função ausente: o e-mail não foi enviado",
            **contexto_atual(),
            evento="email_nudecon",
            resultado="nao_configurado",
            protocolo=protocolo,
        )
        return ResultadoEmail(ok=False, motivo="nao_configurado")
    url, chave = configuracao
    corpo = _corpo(protocolo, dados, imagens)
    cabecalhos = {"Authorization": f"Bearer {chave}", "Content-Type": "application/json"}
    motivo = "rede"
    try:
        async with asyncio.timeout(PRAZO_TOTAL_S):
            for tentativa in range(1, TENTATIVAS + 1):
                inicio = _agora_ms()
                erro_tipo: str | None = None
                try:
                    async with asyncio.timeout(PRAZO_TENTATIVA_S):
                        res = await obter_cliente_http().post(url, json=corpo, headers=cabecalhos)
                except TimeoutError:
                    motivo = "prazo"
                    erro_tipo = "TimeoutError"
                except httpx.HTTPError as erro:
                    motivo = "rede"
                    erro_tipo = type(erro).__name__
                else:
                    duracao = _agora_ms() - inicio
                    if res.is_success:
                        repetido = _repetido(res)
                        logger.info(
                            "[email-nudecon] e-mail enviado à função",
                            **contexto_atual(),
                            evento="email_nudecon",
                            resultado="ok",
                            protocolo=protocolo,
                            tentativa=tentativa,
                            repetido=repetido,
                            duracaoMs=duracao,
                        )
                        return ResultadoEmail(ok=True, repetido=repetido)
                    motivo = f"http_{res.status_code}"
                    logger.error(
                        "[email-nudecon] a função recusou ou falhou",
                        **contexto_atual(),
                        evento="email_nudecon",
                        resultado="nao_ok",
                        protocolo=protocolo,
                        tentativa=tentativa,
                        status=res.status_code,
                        duracaoMs=duracao,
                    )
                    if not _repetir(res.status_code):
                        return ResultadoEmail(ok=False, motivo=motivo)
                if erro_tipo is not None:
                    logger.error(
                        "[email-nudecon] falha na chamada à função",
                        **contexto_atual(),
                        evento="email_nudecon",
                        resultado="erro",
                        protocolo=protocolo,
                        tentativa=tentativa,
                        tipoErro=erro_tipo,
                    )
    except TimeoutError:
        motivo = "prazo"
    return ResultadoEmail(ok=False, motivo=motivo)


def _repetido(res: httpx.Response) -> bool:
    try:
        corpo = res.json()
    except ValueError:
        return False
    return isinstance(corpo, dict) and corpo.get("repetido") is True
