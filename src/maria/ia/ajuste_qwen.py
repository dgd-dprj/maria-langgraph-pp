"""Regras acrescentadas aos prompts de triagem só quando o modelo é um Qwen (#458, homolog em São Paulo).

O prompt foi afinado no Haiku. Medido com os 66 casos de `tests/integracao/ia`, 3 passadas, no Bedrock de
`sa-east-1`: o Qwen3 VL 235B passou de 58,0 para 61,7 acertos com estas regras (Haiku 4.5 `us.`: 61,3 sem elas).
Para qualquer outro modelo o prompt fica idêntico ao de antes.
"""

from __future__ import annotations

import os

SUFIXO_NECESSIDADES = """
Conferência final antes de responder (vale para qualquer assunto):
- Cada necessidade precisa de um PEDIDO da pessoa. Fato citado sem pedido (alguém doente, desempregado, preso, morando longe) é só contexto e não vira necessidade, a menos que a pessoa peça algo sobre esse fato.
- Se "quantidade" for "uma" ou "mais_de_uma", a lista "necessidades" não pode ficar vazia. Confira cada assunto do relato contra o catálogo, um por um, e inclua todos os que cabem em algum id.
- Quando a informação que decide entre dois ids do catálogo não está no relato, marque "haAmbiguidade" como true e liste os dois ids em "idsEmAmbiguidade", em vez de escolher um sozinho. Exemplo de outro assunto: pedido de pensão sem dizer se é para filho ou para ex-cônjuge é dúvida entre os dois ids de pensão, e não a escolha de um deles.
- Quando o relato já traz a informação que decide, escolha só o id que cobre o caso e não acrescente outros por garantia."""  # noqa: E501

SUFIXO_FLUXOS = """
Como decidir (vale para qualquer assunto):
- Leia a descrição de cada fluxo inteira, inclusive as exclusões ("menos X", "não entra aqui", "só quando"). Se a descrição exclui o assunto do relato, esse fluxo não serve.
- Se o relato já traz a informação que separa dois fluxos, devolva só o fluxo que a descrição cobre. Não acrescente outro fluxo "por garantia".
- Se falta no relato justamente a informação que separa dois fluxos, devolva os dois. Exemplo de outro assunto: se um fluxo cobre pensão alimentícia de filhos e outro pensão entre ex-cônjuges, "preciso entrar com pedido de pensão" não diz qual dos dois e devolve os dois; "meu ex não paga a pensão do nosso filho" devolve só o primeiro.
- Não devolva lista vazia se algum fluxo cobre o assunto."""  # noqa: E501


def modelo_e_qwen() -> bool:
    """`BEDROCK_MODEL_ID` de um Qwen (`qwen.qwen3-vl-235b-a22b`). Lido a cada chamada, como `criar_modelo` lê na importação."""
    return os.environ.get("BEDROCK_MODEL_ID", "").strip().lower().startswith("qwen")


def com_ajuste_qwen(sistema: str, sufixo: str) -> str:
    return sistema + sufixo if modelo_e_qwen() else sistema
