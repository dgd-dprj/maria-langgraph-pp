# IA (`src/ia/`)

Toda chamada de IA (Bedrock) do sistema mora aqui — 6 módulos, cada um resolvendo 1 problema específico. Nenhum fluxo (`src/fluxos/*/graph.ts`) ou o orquestrador chama Bedrock direto; todos passam por um destes.

## Visão de conjunto — quem chama qual módulo

![Mapa dos módulos de IA](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/mapa-modulos-ia.png)

## Padrão comum a todos os módulos

![Padrão comum de um módulo de IA](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/padrao-comum-ia.png)

- **Modelo**: `ChatBedrockConverse`, via `BEDROCK_MODEL_ID` (default `anthropic.claude-3-haiku-20240307-v1:0`) e `AWS_REGION` (default `us-east-1`). Instância própria por módulo — repo pequeno não justifica factory compartilhado.
- **Retry**: 3 tentativas (`TENTATIVAS_RETRY_IA`) antes de desistir — absorve instabilidade passageira do Bedrock (throttle, timeout de rede), não mascara erro real.
- **Fallback nunca quebra o fluxo**: se a chamada falhar mesmo depois do retry, cada módulo cai num valor seguro (texto original, lista vazia, `undefined`) — a pergunta/fluxo continua funcionando, só sem o benefício da IA naquela vez. Nunca propaga a exceção pro chamador.
- **`viaIA: boolean`** no retorno de todos — `true` só quando a chamada de IA aconteceu de verdade; `false` cobre tanto "não chamou" (modo mock/flag desligada) quanto "chamou e falhou". Tokens (`tokensEntrada`/`tokensSaida`/`tokensTotal`) só vêm preenchidos quando `viaIA:true` — capturados de `usage_metadata` da `AIMessage` crua (`includeRaw: true` no `withStructuredOutput`).
- **Mock em teste**: `NODE_ENV === "test"` pula a chamada real em todo módulo — suíte rápida, sem custo, sem variabilidade de resposta de LLM quebrando assert de texto fixo.

## Os 6 módulos

### `classificar.ts`

Núcleo reaproveitável: "texto livre + lista de candidatos rotulados → candidato(s) escolhido(s) via IA". Duas funções:
- `classificarEntreOpcoes` — força 1 escolha só (ou `undefined` se nada bater com confiança).
- `classificarMultiploEntreOpcoes` — devolve **todos** os candidatos plausíveis (0, 1 ou vários) — usado quando o chamador precisa saber se o relato é ambíguo, não só qual é o melhor.

Cada chamador mantém seu próprio guard de teste/mock — este módulo só faz a chamada quando invocado, não decide isso.

### `classificarFluxos.ts`

Usa `classificarMultiploEntreOpcoes` pra montar o prompt específico de "escolher fluxo de atendimento a partir do catálogo completo" — chamado pelo orquestrador (`src/orquestrador/graph.ts`). Mock em teste: `MOCK_CLASSIFICACAO_FLOWIDS` (lista separada por vírgula, testa ambiguidade) ou `MOCK_CLASSIFICACAO_FLOWID` (singular, 1 id só).

### `desambiguar.ts`

Gera o **texto** de 1 pergunta que ajuda a distinguir entre candidatos ambíguos — as opções em si (nome de cada fluxo) são montadas deterministicamente pelo chamador, nunca pela IA (evita inventar opção que não existe no catálogo). Fallback: `"Pra te ajudar melhor, qual dessas opções descreve o que você precisa?"`.

### `extrair.ts`

Extrai campos estruturados (`temProcesso`, `numeroProcesso`, `rg`, `parentesco`) de texto livre — regra explícita no prompt: nunca inferir além do que foi dito. Só roda com `EXTRACAO_LIVRE_IA=true` **e** fora de teste (desligada por padrão) — usada na extração livre opcional do fluxo pessoa presa.

### `reescrever.ts`

Reescreve o **texto** de uma pergunta pra ficar mais natural, sem mudar o que é perguntado (campo/ordem continuam determinísticos no grafo). Só roda com `REESCREVER_IA=true` **e** fora de teste — **desligada por padrão desde 2026-08-31**, decisão explícita depois de ver fraseado estranho em produção real (ex: "Essa é o Fulano presa?"). Também expõe `prepararPergunta()`, helper usado por todos os fluxos no padrão de 2 nós "preparar" (chama IA 1x) + "pedir" (só lê o texto pronto e pausa em `interrupt()") — separar em 2 nós evita gastar Bedrock de novo a cada resume (gotcha do LangGraph: código antes do `interrupt()` no mesmo nó reexecuta a cada retomada).

### `sumarizar.ts`

Resume o relato acumulado do orquestrador quando a desambiguação passa de um limite de rodadas (ver `docs/fluxo-orquestrador.md`) — evita reenviar histórico bruto crescente em toda chamada seguinte. Se falhar, mantém o texto original (nunca perde contexto por causa de falha de resumo). Mock em teste: `MOCK_SUMARIZACAO_RESUMO` simula uma compressão de verdade (sem ele, o texto original é devolvido sem encolher).

## Flags de ambiente

| Flag | Default | Efeito |
|---|---|---|
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-haiku-20240307-v1:0` | Modelo usado por todos os módulos. |
| `AWS_REGION` | `us-east-1` | Região do Bedrock. |
| `REESCREVER_IA` | desligada | Reescrita de texto de pergunta — desligada por decisão de produto. |
| `EXTRACAO_LIVRE_IA` | desligada | Extração de campos por IA no fluxo pessoa presa. |

Ver `src/ia/CLAUDE.md` pras regras que não podem falhar (nunca logar dado sensível indo pro Bedrock, nunca remover o caminho mock).
