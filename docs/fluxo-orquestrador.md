# Fluxo: orquestrador (classificação automática)

Alternativa a `POST /atendimentos` pra quem **não sabe de antemão** qual `flowId` usar: manda um relato livre (`mensagem`) e a Maria classifica com IA qual fluxo atende o caso, criando o atendimento normalmente nele.

Grafo próprio (`src/orquestrador/graph.ts`), rota HTTP dedicada (`POST /atendimentos/orquestrador`, `src/rotas/orquestrador.ts`).

Usa 4 dos 6 módulos de `src/ia/` (`classificar`, `classificarFluxos`, `desambiguar`, `sumarizar`) — **só o orquestrador chama esses 4**, nenhum fluxo de negócio (`fluxos/*/graph.ts`) usa. Os outros 2 módulos (`reescrever`, `extrair`) são o inverso: usados por fluxos, nunca pelo orquestrador. Sem sobreposição — ver `docs/ia.md` pro que cada módulo faz.

![Diagrama do fluxo orquestrador](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/orquestrador.png)

## Passo a passo

1. **`classificar`** — 1ª rodada: busca por similaridade (embedding, `fluxo_embeddings`) no catálogo completo (implementados + planejados, `catalogoParaClassificacao()`), retorna até 10 candidatos (`CANDIDATOS_MAXIMOS`). Chama IA (`classificarFluxosPlausiveis`) pra filtrar quais desses candidatos são plausíveis de verdade a partir do relato. Rodadas seguintes: classifica de novo, mas só **dentro** do subconjunto que já sobrou — nunca alarga de volta pro catálogo todo.
2. Decisão por quantos candidatos restaram (`depoisDeClassificar`):
   - **0** → `nenhum` → nó `naoIdentificado` → `handoff_humano` (`motivoHandoff: nao_identificado`).
   - **1** → `um` → nó `identificado` → segue pra criar o atendimento nesse `flowId`.
   - **2+** → `muitos` → precisa desambiguar (próximo passo) — **a menos que já tenha esgotado `LIMITE_RODADAS` (5)**, aí também cai em `nenhum`/handoff (nunca fica perguntando pra sempre).
3. **`prepararPerguntaDesambiguacao`** — antes de gerar pergunta por IA, checa se **todos** os candidatos restantes compartilham literalmente a mesma pergunta raiz do Verde (mesmo texto + mesmas opções, `buscarPerguntaRealCompartilhada`) — se sim, usa esse texto real (não gasta token de IA). Senão, gera pergunta por IA (`gerarPerguntaDesambiguacao`).
4. **`pedirDesambiguacao`** — `interrupt()` pausa esperando a resposta da pessoa (`tipoResposta: "texto"` sempre — decisão deliberada: mostrar nomes internos dos candidatos como menu soava técnico, deixa responder com as próprias palavras). Resposta é concatenada no relato bruto (`mensagem`, auditoria completa) e volta pro `classificar`.
5. A partir da 3ª rodada (`LIMITE_RODADAS_SUMARIZACAO`), o histórico vira resumo por IA (`sumarizarRelato`) + última resposta verbatim — evita mandar um relato bruto gigante pra classificação/desambiguação depois de várias idas e vindas.
6. Quando identifica 1 fluxo: `buscarFluxo(flowIdEscolhido)` resolve pro grafo implementado de verdade OU pro grafo padrão (fluxo planejado sem implementação própria ainda) — dali em diante o tratamento é idêntico nos 2 casos. O total de tokens gastos na triagem (classificação + desambiguação) é repassado como ponto de partida do acumulador do fluxo escolhido (`dadosConhecidos.tokensGastos`) — não perde o custo da fase de identificação.

## Regras de negócio

| Regra | Valor | Por quê |
|---|---|---|
| Candidatos por rodada de retrieval | 10 | Mesmo valor de antes da issue #28. |
| Limite de rodadas de desambiguação | 5 | Subiu de 3 (issue #43) — com 76 categorias no catálogo, relatos ambíguos entre categorias parecidas levam mais idas e vindas pra convergir. |
| Rodada em que começa a sumarizar | 3 | Issue #47 — histórico bruto cresce demais depois de algumas rodadas. |
| `candidatosRestantes` nunca alarga de volta | — | Cada rodada de classificação só filtra dentro do que já sobrou, nunca reconsidera candidato já descartado. |
| Pergunta usa texto real do Verde quando possível | — | Issue #32 — só quando **todos** os candidatos restantes compartilham a mesma pergunta raiz (mesmo texto + mesmas opções); senão, gera por IA. |
| `tipoResposta` sempre `"texto"` na desambiguação | — | Decisão 2026-09-11 — nomes internos de categoria como menu de opção soava técnico pro usuário real. |

## Contrato HTTP (resumo — ver `docs/contrato-tykhe.md` pro genérico)

- 1ª chamada: `{ chatId, mensagem }`.
- Enquanto desambiguando (`status: em_andamento` sem `flowId`): manda `{ chatId, resposta }` pra essa mesma rota (não `mensagem`).
- Quando resolve: `flowId` aparece na resposta e o atendimento já foi criado nesse fluxo — dali em diante é `GET`/`POST /atendimentos/respostas` normais, como qualquer atendimento criado direto.
- Checkpoint do orquestrador usa `thread_id` com prefixo (`orquestrador:${chatId}`) — namespace separado do fluxo final escolhido (que usa o `chatId` puro), pra não colidir os 2 grafos no mesmo `thread_id`.
