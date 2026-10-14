"""Classifica o relato livre entre os fluxos cadastrados (issue #28), traduzido de
`src/ia/classificarFluxos.ts`.

Devolve TODOS os fluxos plausíveis; o orquestrador decide o que fazer com 0
(handoff), 1 (segue direto) ou vários (pergunta para desambiguar). A chamada
real fica em `classificar.classificar_multiplo_entre_opcoes`; aqui ficam só o
prompt e o guard de teste.
"""

from __future__ import annotations

import os
from typing import TypedDict

from maria.ia.classificar import ResultadoClassificacaoMultipla, classificar_multiplo_entre_opcoes


class FluxoParaClassificar(TypedDict):
    id: str
    nome: str
    descricao: str


async def classificar_fluxos_plausiveis(mensagem: str, fluxos: list[FluxoParaClassificar]) -> ResultadoClassificacaoMultipla:
    # APP_ENV=test nunca chama o Bedrock. MOCK_CLASSIFICACAO_FLOWIDS (lista
    # separada por vírgula) vale mesmo vazia; MOCK_CLASSIFICACAO_FLOWID é o
    # fallback de 1 item. Os ids mockados não são conferidos contra `fluxos`
    # (o orquestrador depende disso).
    if os.environ.get("APP_ENV") == "test":
        mock_ids = os.environ.get("MOCK_CLASSIFICACAO_FLOWIDS")
        if mock_ids is not None:
            return {"ids": [s.strip() for s in mock_ids.split(",") if s.strip()], "viaIA": False}
        mock_id = os.environ.get("MOCK_CLASSIFICACAO_FLOWID")
        return {"ids": [mock_id] if mock_id else [], "viaIA": False}
    ids = [f["id"] for f in fluxos]
    descricoes = "\n".join(f'- id "{f["id"]}" ({f["nome"]}): {f["descricao"]}' for f in fluxos)
    sistema = f"""Você tria o relato de alguém buscando atendimento na Defensoria Pública do RJ, decidindo quais fluxos de atendimento PODEM resolver o caso.
Fluxos disponíveis:
{descricoes}
Regras: devolva os ids de TODOS os fluxos que plausivelmente atendem ao relato — nenhum (lista vazia) se não bater com confiança em nenhum, 1 só se for claro, ou vários se o relato for genuinamente ambíguo entre mais de um. Nunca invente id fora da lista."""  # noqa: E501
    return await classificar_multiplo_entre_opcoes(mensagem, sistema, ids)
