"""GET /versoes-dos-fluxos e GET /versoes-dos-fluxos/:id: leitura das versões dos fluxos para o Visor (#547, #542).

Só leitura. Autenticação própria (`VERSOES_API_KEY`, Bearer), diferente da `API_KEY` da Tykhe: uma não abre as rotas da outra.
Sem `VERSOES_API_KEY` as rotas não existem (404), como o webhook do WhatsApp sem o token (#339). Ficam fora do /docs público
(sem tags): quem precisa do contrato lê `docs/versionamento-dos-fluxos.md`.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

from maria.api.pipeline import Contexto, Resposta, Rota
from maria.versionamento import leitura

CHAVE = "versoes"
LIMITE_PADRAO = 20
LIMITE_MAXIMO = 100
_TEXTO_DO_FILTRO = re.compile(r"[A-Za-z0-9_.-]{1,80}")
_ID = re.compile(r"[0-9]{1,18}")
MENSAGEM_503 = "Não foi possível ler as versões dos fluxos agora. Tente de novo em instantes."


def chave_configurada() -> str | None:
    return os.environ.get("VERSOES_API_KEY") or None


def ligado() -> bool:
    return chave_configurada() is not None


def _erro(status: int, mensagem: str) -> Resposta:
    return Resposta(status, {"erro": mensagem})


def _filtro(ctx: Contexto, nome: str) -> tuple[str | None, Resposta | None]:
    valor = ctx.consulta.get(nome)
    if valor is None or valor == "":
        return None, None
    if not isinstance(valor, str) or not _TEXTO_DO_FILTRO.fullmatch(valor):
        return None, _erro(400, f"{nome} inválido (use letras, números, ponto, hífen ou sublinhado, até 80 caracteres)")
    return valor, None


async def _listar(ctx: Contexto) -> Resposta:
    fluxo, falha = _filtro(ctx, "fluxo")
    if falha:
        return falha
    ambiente, falha = _filtro(ctx, "ambiente")
    if falha:
        return falha
    bruto = ctx.consulta.get("limite")
    limite = LIMITE_PADRAO
    if bruto not in (None, ""):
        if not isinstance(bruto, str) or not _ID.fullmatch(bruto) or not 1 <= int(bruto) <= LIMITE_MAXIMO:
            return _erro(400, f"limite inválido (esperado um número inteiro de 1 a {LIMITE_MAXIMO})")
        limite = int(bruto)
    url = os.environ.get("DATABASE_URL")
    if not url:
        return _erro(503, MENSAGEM_503)
    try:
        dados = await leitura.listar(url, fluxo, ambiente, limite)
    except Exception as erro:
        ctx.log.error("[versionamento] falha ao ler as versões dos fluxos", err=erro)
        return _erro(503, MENSAGEM_503)
    return Resposta(200, {"lidoEm": datetime.now(UTC).isoformat(), **dados})


async def _detalhe(ctx: Contexto) -> Resposta:
    bruto = ctx.parametros.get("id", "")
    if not _ID.fullmatch(bruto):
        return _erro(400, "id inválido (esperado um número inteiro)")
    url = os.environ.get("DATABASE_URL")
    if not url:
        return _erro(503, MENSAGEM_503)
    try:
        versao = await leitura.buscar(url, int(bruto))
    except Exception as erro:
        ctx.log.error("[versionamento] falha ao ler a versão do fluxo", err=erro)
        return _erro(503, MENSAGEM_503)
    if versao is None:
        return _erro(404, "versão não encontrada")
    return Resposta(200, {"lidoEm": datetime.now(UTC).isoformat(), **versao})


ROTAS: tuple[Rota, ...] = (
    Rota("GET", "/versoes-dos-fluxos", _listar, chave=CHAVE),
    Rota("GET", "/versoes-dos-fluxos/:id", _detalhe, chave=CHAVE),
)

__all__ = ["CHAVE", "ROTAS", "chave_configurada", "ligado"]
