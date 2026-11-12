"""Regras acrescentadas aos prompts da IA só quando o modelo é um Qwen (#458, homolog em São Paulo).

O prompt foi afinado no Haiku. Medido com os 66 casos de `tests/integracao/ia`, 3 passadas, no Bedrock de
`sa-east-1`: o Qwen3 VL 235B passou de 58,0 para 61,7 acertos com estas regras (Haiku 4.5 `us.`: 61,3 sem elas).
Para qualquer outro modelo o prompt fica idêntico ao de antes.

#472 (2026-11-12): três outras versões das regras da triagem foram medidas com o VL 235B, 3 passadas cada (61,0,
61,7 e 61,0), sem ganho acima da variação entre rodadas (cerca de 3 casos); as regras da triagem ficaram as de
cima. O Qwen3 Coder 30B fez 54 de 66 com elas. Entrou só a regra da pergunta de desambiguação, que com o Qwen
perguntava sobre uma opção só ("Seu plano de saúde está envolvido nisso?").
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

SUFIXO_DESAMBIGUAR = """
Na pergunta, cite as opções em dúvida pelo que as separa, de forma neutra e na mesma pergunta (por exemplo: "pelo plano de saúde ou pelo SUS?", "você já tem um processo ou quer abrir um novo?"). Não pergunte só sobre uma das opções."""  # noqa: E501

# #212 (decisão da Nicole, 2026-11-12): o parentesco só da lista, sem inventar. Medido na comparação da #472, com 53
# respostas no formato das da produção (1 a 4 palavras): o VL 235B foi de 48 para 60 de 61 (8 delas fora dos exemplos
# do prompt), igual em 2 passadas. No Haiku, as mesmas regras derrubaram o acerto (52 de 61, contra 57,3 com o prompt
# de sempre), com "mãe" lido como "Filho(a)": o prompt dele fica o de sempre, e o valor fora da lista é barrado no
# fluxo para os dois modelos. Erro que fica com o Qwen: quem é casado com o filho ou a filha da pessoa presa ("genro",
# "sou casado com a filha dele") vira "Sogro(a)". Uma regra geral de direção ("quem escreve é [valor] da pessoa
# presa") não corrigiu e fez a "nora" voltar a errar (3 passadas, 2026-11-12): ficou esta versão.
SUFIXO_PARENTESCO = """
Regras a mais:
- Responda só com um dos parentescos possíveis, escrito exatamente como na lista (por exemplo, "Irmão(a)", e não "Irmã" nem "Irmã(o)"), ou com "nenhum". Nunca invente outro valor.
- O parentesco é o de quem escreve em relação à pessoa presa. Uma palavra só, ou "X dele/dela", diz quem a pessoa que escreve é, sem inverter: "filha" → "Filho(a)", "neta" → "Neto(a)", "mamãe" → "Mãe", "vó dele" → "Avô/Avó". Quem vive junto sem casar no papel → "Companheiro(a)".
- Só inverta quando a pessoa usa "meu" ou "minha" para dizer quem a pessoa presa é para ela: "minha mãe" → "Filho(a)", "meu marido" → "Esposo(a)", "meu neto" → "Avô/Avó". Se a inversão deixa dúvida entre dois parentescos ("meu filho" pode ser "Mãe" ou "Pai"), responda "nenhum".
- Parente que não está na lista (enteado(a), padrasto, madrasta, nora, genro, padrinho, tio-avô) e quem não é parente (advogado, vizinho, colega) → "Outro". Não troque por um parentesco parecido: nora e genro não são "Sogro(a)", enteado(a) não é "Filho(a)", e ex-companheiro(a) é "Ex-esposo(a)", não "Companheiro(a)"."""  # noqa: E501


def modelo_e_qwen() -> bool:
    """`BEDROCK_MODEL_ID` de um Qwen (`qwen.qwen3-vl-235b-a22b`). Lido a cada chamada, como `criar_modelo` lê na importação."""
    return os.environ.get("BEDROCK_MODEL_ID", "").strip().lower().startswith("qwen")


def com_ajuste_qwen(sistema: str, sufixo: str) -> str:
    return sistema + sufixo if modelo_e_qwen() else sistema
