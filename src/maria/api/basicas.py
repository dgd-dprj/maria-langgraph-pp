"""GET /health e GET /fluxos (develop: `app.ts:78`, `rotas/fluxos.ts`)."""

from __future__ import annotations

from maria.api import esquemas
from maria.api.pipeline import Contexto, Resposta, Rota
from maria.fluxos import fluxos_ligados


async def _health(_ctx: Contexto) -> Resposta:
    # Health check do ALB: sem efeito colateral, fora da autenticação.
    return Resposta(200, {"status": "ok"})


async def _fluxos(_ctx: Contexto) -> Resposta:
    # Só os fluxos implementados: os tipos da Tykhe e os planejados não aparecem
    # aqui, nem um fluxo em teste fora do release (#324).
    return Resposta(200, [{"id": id_, "nome": cfg.nome} for id_, cfg in fluxos_ligados().items()])


ROTAS: tuple[Rota, ...] = (
    Rota("GET", "/health", _health, protegida=False),
    Rota(
        "GET",
        "/fluxos",
        _fluxos,
        respostas={200: esquemas.FLUXOS},
        resumo="Lista os fluxos disponíveis e seus ids — use o id como flowId em /atendimentos",
        tags=("fluxos",),
    ),
)
