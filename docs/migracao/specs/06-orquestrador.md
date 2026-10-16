# SDD — Módulo `orquestrador`

Parte de #208. Issue: #244. Branch: `refactor/244-orquestrador-python`, criada a partir de `migration` @ `0161132` (depois do fluxos). **Fonte de comportamento: develop @ `1157a6d`**, que inclui o #242 (seção 0.1). **As linhas citadas (`arquivo:linha`) são de `1157a6d`.**

| Origem (develop) | Destino (migration) |
|---|---|
| `src/orquestrador/state.ts` (49 linhas) | `src/maria/orquestrador/state.py` |
| `src/orquestrador/graph.ts` (194) | `src/maria/orquestrador/graph.py` (`obter_grafo`, pela `FabricaGrafo` do fluxos) |
| `src/orquestrador/graph.test.ts` (2 testes) | `tests/orquestrador/` |
| `src/fluxos/index.ts` e `src/fluxos/tiposTykhe.ts`, na parte do #242 | `src/maria/fluxos/__init__.py` e `src/maria/fluxos/tipos_tykhe.py` (seção 0.1) |

**Fora deste módulo, no `api`:**
- a rota `POST /atendimentos/orquestrador` (`rotas/orquestrador.ts`): o `thread_id` `orquestrador:<chatId>`, os desfechos `redirecionado` e `handoff_humano`, os logs `orquestrador_*` e a entrega a `criarAtendimento` com os tokens;
- o bridge do WhatsApp;
- os 2 arquivos de teste de rota (`test/orquestrador.test.ts` e `test/webhookWhatsapp.test.ts`).

O painel do Grafana e os docs do #242 também ficam fora: vão para os módulos documentacao e corte.

**Regra desta spec** (`MIGRACAO.md`, "Padrão: afirmação sobre desfecho inferida do código, sem execução"): as afirmações sobre o comportamento de develop marcadas com **(lido)** vieram da leitura do código e ainda não foram executadas. Cada uma vira cenário da conferência diferencial (seção 6, item 9) antes do PR. As marcadas com **(executado)** já rodaram.

---

## 0. O que mudou desde o fluxos

### 0.1 Develop andou: `0aecd98` → `1157a6d` (o #242, para a #225)

O fluxos foi traduzido de `0aecd98`. O #242 entrou depois e mexe em código do **módulo fluxos, já mergeado**. Ele entra num commit próprio, no começo da branch, que diz que atualiza código mergeado, como foi feito com o #226 no fluxos.

| Arquivo | Mudança | Destino |
|---|---|---|
| `src/fluxos/tiposTykhe.ts` (novo) | `TIPOS_TYKHE`: 7 tipos que a Tykhe atende (`saude`, `novo-processo`, `andamento-processo`, `agendamentos`, `ajuda-app`, `outros`, `sair`), com `id` prefixado (`tykhe:…`), `nome`, `descricao` e `mensagem`; `tipoTykhePorId` e `tipoTykhePorCaso` | `fluxos/tipos_tykhe.py`, textos byte a byte (são contrato com a Tykhe, `docs/contrato-tykhe.md`) |
| `src/fluxos/index.ts:112-118` | `catalogoParaClassificacao` passa a ser implementados + `TIPOS_TYKHE`. Os planejados só entram com `ORQUESTRADOR_INCLUIR_PLANEJADOS === "true"`, lido a cada chamada | `catalogo_para_classificacao`, com a comparação exata `== "true"` (`"TRUE"` e `"1"` não ligam) |
| `src/rotas/orquestrador.ts`, `src/rotas/webhookWhatsapp.ts` | `redirecionado`, `tipoCaso` e o "não identificado" que vira `outros` | módulo `api` |

**Efeito no catálogo:** caiu de 76 opções para 9, por padrão. Os 2 fluxos implementados continuam primeiro, na mesma ordem.

#### Números de acerto antes e depois do #242 não são comparáveis

Com 76 opções, o orquestrador escolhia entre muitas categorias próximas do Verde, e a desambiguação existia para separá-las (o `LIMITE_RODADAS` subiu de 3 para 5 por isso, #43). Com 9, o problema é outro:
- são 2 fluxos que a Maria conduz e 7 tipos amplos da Tykhe;
- um deles, `outros`, é a saída para o que não se encaixa.

**Qualquer número medido antes do #242 mede outro problema e não serve de referência para depois.** Isso vale para taxa de identificação, de "não identificado", número de rodadas, tokens por triagem e o que mais for. Comparar as duas fases como se fossem a mesma coisa daria uma conclusão errada. A régua da migração continua sendo develop @ `1157a6d`, já com o catálogo de 9.

#### `ORQUESTRADOR_INCLUIR_PLANEJADOS` em cada ambiente (verificado em 2026-10-16)

| Ambiente | Serviço ECS e branch publicada | Código | Variável |
|---|---|---|---|
| Produção | `api`, publicado de `main` (`deploy-prod.yml`) | `main` @ `06f2157` (2026-10-01), **sem o #242** | **não existe no código.** O catálogo é o antigo: implementados + planejados, 76 opções |
| Release | `api-release`, publicado de `develop` (`deploy-release.yml`) | `develop` @ `1157a6d`, com o #242 | **ausente no `ecs.tf` e no `release.tf`** (nem em `main`, nem em `develop`): vale o padrão do código, **desligada**. Catálogo de 9 |

- **Como foi verificado:** `git grep` em `infra/terraform/ecs.tf` e `release.tf` nas duas branches, e os gatilhos dos workflows de deploy.
- **Não verificado:** a task definition em execução no ECS. Uma variável posta à mão no console não aparece no Terraform. Conferir exigiria `aws ecs describe-task-definition`, que não foi autorizado. O `terraform-drift.yml` existe para pegar esse tipo de diferença.
- **Consequência para a tradução:** o caminho que vai a produção no próximo release é o **padrão, com a variável desligada** (9 opções). A conferência diferencial principal roda assim. O caminho com `"true"` é reproduzido, porque existe em develop e tem teste lá (`test/orquestrador.test.ts:437`), mas entra só como cenário secundário.
- **Produção hoje não roda nenhuma das duas versões do catálogo de develop.** Até o próximo release de `main`, ela classifica entre 76 opções e faz `handoff_humano` no não identificado.

### 0.2 Regra de estado: `undefined` × `null`, caso a caso

O orquestrador recebe menos entrada externa que os fluxos. **A Tykhe não pré-preenche o estado**: a rota só passa `{mensagem}` no primeiro invoke e a `resposta` no resume (`rotas/orquestrador.ts:154-157`), e o `dadosConhecidos` vai só para o fluxo escolhido. **O `null` entra por duas portas:**
- **o modelo**, sem validação (#212): `ids`, `pergunta`, `resumo`;
- **o nosso banco**: a pergunta raiz (`perguntas`), na desambiguação pela pergunta real.

| Canal | develop grava `undefined`? | O `null` entra? | Tradução | Por quê / o que mudaria |
|---|---|---|---|---|
| `mensagem` | não | não (a rota manda `body.mensagem ?? ""`) | valor direto | Se a rota mudar, é o `api` que decide |
| `resumoRelato` | **sim**: `sumarizarRelato` sem a chave `resumo` (`graph.ts:165-168`) | **sim**, pelo modelo (`resumo: null`) | `None` = `undefined` | **Conflito: decisão D-1 (seção 8).** (lido) Com `resumo: null`, develop guarda `null`, e `textoParaClassificacao` (`:37`, `=== undefined`) monta `"null\n<última resposta>"`: a classificação perde todo o histórico. O Python trata como "ainda não sumarizou" e manda o histórico bruto |
| `ultimaResposta` | não (sempre a `resposta` do resume, string) | não | valor direto | — |
| `candidatosRestantes` | não (`classificar` sempre grava uma lista) | não | `None` só antes da 1ª rodada; o guarda é `is None`, **nunca** truthiness | `[]` levaria a `nenhum`, e o grafo termina antes de reclassificar. Com `or`, o mesmo `[]` refaria o retrieval |
| `rodada` | não | não | ausente → `0` (`?? 0`) | — |
| `flowIdEscolhido` | não (`identificado` só roda com 1 candidato, e o id vem do catálogo) | não | valor direto | — |
| `statusFinal` | não | não | valor direto | — |
| `perguntaAtualTexto` | **sim**: `gerarPerguntaDesambiguacao` sem a chave `pergunta` | **sim**, pelo modelo | `None` = `undefined` | **Sem divergência:** o único leitor é o `??` de `pedirDesambiguacao` (`:147`), que trata os dois igual |
| `tokensGastosRodada` | **sim**: `tokensTotal` ausente no `classificar` (`:65`); `somarTokens` com os dois lados ausentes (`:121-124`) | não (vem do `usage`) | `None` = `undefined` | Lido só no log da rota |
| `tokensGastosConversa` | não (reducer de soma, delta `?? 0`) | não | `CanalTokensGastos` do fluxos | — |

**Chave ausente que não pode virar `None`:** quando `prepararPerguntaDesambiguacao` acha a pergunta no banco (`:131`), devolve **só** `perguntaAtualTexto`. Escrever `tokensGastosRodada: None` ali apagaria o valor que o `classificar` acabou de gravar. É mutação da seção 6.

### 0.3 O que os módulos anteriores já entregam e o orquestrador usa

| Peça | Onde | Situação |
|---|---|---|
| `buscar_candidatos(mensagem, k, catalogo)` | `shared/embeddings_fluxos.py:247` | traduzida no persistencia |
| `classificar_fluxos_plausiveis`, com os mocks `MOCK_CLASSIFICACAO_FLOWIDS`/`FLOWID` | `ia/classificar_fluxos.py:24` | traduzida no ia. `ids` é `NotRequired[Any]` (#212) |
| `gerar_pergunta_desambiguacao` (`TEXTO_FALLBACK` no teste e na falha) | `ia/desambiguar.py:51` | traduzida no ia. `pergunta` é `NotRequired[Any]` |
| `sumarizar_relato` (`MOCK_SUMARIZACAO_RESUMO` com `??`) | `ia/sumarizar.py:46` | traduzida no ia. `resumo` é `NotRequired[Any]` |
| `obter_perguntas_store().buscar_pergunta_raiz` | `shared/perguntas_db.py:82` | traduzida no persistencia |
| `catalogo_para_classificacao` | `fluxos/__init__.py:103` | **versão de `0aecd98`**, atualizada na seção 0.1 |
| `CanalTokensGastos`, `somar_tokens` | `shared/tokens_acumulados.py` | traduzidos na fundação |
| `FabricaGrafo` (`obter`, `criar`) | `fluxos/_fabrica.py` | do fluxos |
| `trim_js`, `texto_template` | `shared/_js.py` | do subgrafos e do fluxos |

## 1. Contexto

Um grafo de 5 nós que classifica o relato livre entre as opções do catálogo e, quando sobra mais de uma, pergunta até convergir:
- **`classificar`:** na 1ª rodada, faz o retrieval no catálogo completo (`buscarCandidatos`, `CANDIDATOS_MAXIMOS = 10`) e classifica; nas seguintes, classifica só dentro de `candidatosRestantes`.
- **Roteamento (`depoisDeClassificar`):**
  - 0 candidatos: `naoIdentificado`;
  - 1 candidato: `identificado`;
  - mais de um, com `rodada >= LIMITE_RODADAS` (5): também `naoIdentificado`;
  - nos outros casos: desambiguação.
- **`prepararPerguntaDesambiguacao`:** usa a pergunta raiz real, se todos os candidatos compartilham o mesmo texto e o mesmo conjunto de opções (#32). Senão, gera a pergunta por IA.
- **`pedirDesambiguacao`:** `interrupt` com `{pergunta, tipo: "texto"}`, sem `opcoes`. No resume, a resposta é concatenada em `mensagem`. A partir de `LIMITE_RODADAS_SUMARIZACAO` (3), sumariza o que veio antes e guarda a resposta atual em `ultimaResposta` (#47).
- **`identificado`** e **`naoIdentificado`** gravam `statusFinal` e o `flowIdEscolhido`. O que fazer com isso é da rota (`api`).

Topologia: `START → classificar`; `classificar ⇢ {naoIdentificado, identificado, prepararPerguntaDesambiguacao}`; `prepararPerguntaDesambiguacao → pedirDesambiguacao → classificar`; `identificado → END`; `naoIdentificado → END`.

## 2. Contrato

- **Nomes:** os de develop para nós e canais (camelCase), como nos fluxos. Os rótulos do roteamento são `nenhum`, `um` e `muitos`.
- **Constantes:** `CANDIDATOS_MAXIMOS = 10`, `LIMITE_RODADAS = 5` e `LIMITE_RODADAS_SUMARIZACAO = 3`, com os comentários de origem (#28, #43, #47).
- **`obter_grafo()`:** pela `FabricaGrafo`, compilado com o checkpointer do processo. Fica fora do `langgraph.json`, como em develop.
- **Interrupt:** `{"pergunta": …, "tipo": "texto"}`, sem a chave `opcoes`. O fallback do payload é "Pra te ajudar melhor, pode contar com mais detalhes o que você precisa?".
- **`CandidatoOrquestrador`:** `{id, nome, descricao}`.

## 3. Comportamento: pontos onde a tradução ingênua erra

### 3.1 Saída do modelo sem validação (#212)

| Saída | develop | Tradução ingênua | Tradução certa |
|---|---|---|---|
| `ids` ausente, `null` ou número | (lido) `ids.map` lança `TypeError` fora do `try` da IA: 500 | `for` sobre `None` também lança, mas com outra mensagem | lança `TypeError` |
| `ids` string (`"abc"`) | (lido) `"abc".map` não existe: `TypeError` | **itera os caracteres** e segue | exige lista: `TypeError` se não for |
| `ids` objeto (`{}`) | (lido) `TypeError` | **itera as chaves** e segue | exige lista |
| item de `ids` lista ou objeto | (lido) `Map.get` devolve `undefined`, e o item é filtrado | **`dict.get` lança `TypeError`** (não hasheável) | item que não é `str` não acha nada e é filtrado |
| item de `ids` número `5` com id `"5"` no catálogo | (lido) `Map.get(5)` não acha (SameValueZero) | `dict.get(5)` também não acha | igual, com teste |
| item de `ids` repetido | (lido) entra duas vezes: com o mesmo id duas vezes, `n = 2` e a desambiguação é "entre ele e ele mesmo" | igual | reproduz, com teste (achado A3) |
| `resumo` número, booleano, objeto ou lista | (lido) `` `${resumo}\n…` ``: `"5\n…"`, `"[object Object]\n…"` | f-string com `str()` (`"True"`, `"{}"`) | `texto_template` |
| `resumo` `null` | ver 0.2 e D-1 | — | — |
| `pergunta` número ou objeto | (lido) vai crua no payload do interrupt | igual | reproduz. A serialização é da rota (`api`) |

### 3.2 Texto

| Ponto | develop | Python |
|---|---|---|
| `mesmoConjuntoDeOpcoes` (`:91-96`) | `resposta.trim().toUpperCase()`, ordena e compara | `trim_js` e `upper()`. A ordenação do JS (code units UTF-16) e a do Python (code points) diferem, mas **não muda o resultado**: depois de ordenar os dois lados do mesmo jeito, comparar posição a posição é comparar multiconjuntos. Teste com caractere fora do BMP para fixar isso |
| `textoParaClassificacao` (`:36-39`) | `` `${resumoRelato}\n${ultimaResposta ?? ""}` `` | `texto_template` e `coalesce` |
| Concatenação da resposta (`:157`) | `` `${state.mensagem}\n${resposta}` `` | idem; a resposta chega string pela rota |
| `if (perguntaDoBanco)` (`:131`) | truthiness: `""` cai para a IA | `if pergunta_do_banco:` (para `str`, a truthiness coincide) |

### 3.3 Concorrência

`buscarPerguntaRealCompartilhada` faz `Promise.all` de até 10 consultas (`:109`). O Python usa `asyncio.gather` no mesmo pool. O pool de `perguntas` tem no máximo 10 conexões (`shared/pool.py`, igual ao `pg`), o mesmo número de `CANDIDATOS_MAXIMOS`. Um atendimento sozinho cabe no pool. **(lido)** Com atendimentos simultâneos na desambiguação, as consultas que passarem do limite esperam na fila, sem erro, até o prazo do pool (`timeout=120`, decisão provisória da #208). Teste com 10 candidatos contra a store em memória e, no CI, contra Postgres.

### 3.4 Guardas de ambiente

- `MOCK_CLASSIFICACAO_FLOWIDS`, `MOCK_CLASSIFICACAO_FLOWID` e `MOCK_SUMARIZACAO_RESUMO` já estão no ia, sob `APP_ENV=test`.
- `ORQUESTRADOR_INCLUIR_PLANEJADOS` é lido a cada chamada de `catalogo_para_classificacao` (0.1).

### 3.5 Defeitos reproduzidos, com issue

| Issue | Onde |
|---|---|
| #212 | saída do modelo sem validação (3.1) |
| #222 | com o Bedrock fora, o retrieval do 1º `classificar` herda os 12,5 a 14,7 min do embedding |
| #225 | o desfecho está na rota; aqui, só o catálogo (0.1) |

## 4. O que não muda

Constantes, topologia, nomes, payload do interrupt, a ordem do catálogo (implementados, Tykhe e, com a variável, planejados), o texto que vai à classificação, a desambiguação e a sumarização, e a soma de tokens.

## 5. Observabilidade

Nenhum log dentro de `src/orquestrador`. Os logs `orquestrador_*` estão na rota (`api`). As funções de IA já registram as próprias falhas (`[desambiguar]`, `[sumarizar]`, `[classificar]`). A tradução não acrescenta nenhum log.

## 6. Testes que provam

**Traduzidos:** os 2 de `graph.test.ts`: sem sumarização abaixo do limite, e sumarização com `ultimaResposta` verbatim no limite.

**Novos:**
1. Topologia igual à de develop (lista literal de nós e arestas).
2. Interrupt: payload `{pergunta, tipo}` sem `opcoes`; fallback quando `perguntaAtualTexto` é `None`.
3. Tabela da seção 0.2, um teste por linha. No caso da pergunta vinda do banco, `tokensGastosRodada` continua com o valor do `classificar`.
4. Roteamento:
   - 0 → `naoIdentificado`;
   - 1 → `identificado`, com o `flowIdEscolhido`;
   - vários → desambiguação;
   - vários na 5ª rodada → `naoIdentificado`.
5. Sumarização:
   - a 1ª passagem pelo limite resume o histórico bruto;
   - as seguintes resumem resumo + última resposta;
   - `resumo` com o mesmo texto do mock vazio (`""` é resumo válido).
6. Saída do modelo (3.1): um teste por linha, com o Bedrock falso do ia.
7. Pergunta real compartilhada:
   - mesmo texto e mesmas opções, em ordem e caixa diferentes → usa o banco e não gasta tokens;
   - opções diferentes → IA;
   - um candidato sem pergunta raiz → IA;
   - menos de 2 candidatos → IA.
8. Catálogo (0.1): 9 opções na ordem certa; `"true"` inclui os planejados; `"TRUE"` e `"1"` não incluem; textos de `TIPOS_TYKHE` byte a byte com develop.
9. **Conferência diferencial contra develop @ `1157a6d`**, com o #242 dentro (D-2), e nunca contra `0aecd98`, cujo catálogo tem 76 opções. **Os cenários principais rodam com `ORQUESTRADOR_INCLUIR_PLANEJADOS` ausente**, que é o caminho do próximo release (0.1); os cenários com `"true"` são secundários. Os mesmos cenários rodam nos dois lados, com o mesmo Bedrock falso e a mesma store, comparando byte a byte o payload de cada interrupt, o estado final, o texto enviado à classificação, à desambiguação e à sumarização em cada rodada, e a exceção. **Cada item (lido) desta spec vira cenário.**
10. **Varredura (técnica do `MIGRACAO.md`):**
    - **Saída do modelo:** cada saída (`idsPlausiveis`, `pergunta`, `resumo`) com `null`, texto, número, booleano, `{}`, `[]` e `""`, e com a chave ausente.
    - **Pergunta raiz do banco:** `textoPergunta` e `resposta` das opções com `null` e `""`.
    - **Por que o canal varrido muda:** aqui a Tykhe não pré-preenche o estado. Por isso as portas varridas são as da seção 0.2, e não o `dadosConhecidos`.

**Mutações a executar antes do PR:**

| Mutação | Teste |
|---|---|
| `candidatosRestantes or …` no lugar de `is None` | 3 |
| `tokensGastosRodada: None` na pergunta do banco | 3 |
| `resumoRelato` testado por truthiness (`""` vira "não sumarizou") | 5 |
| f-string com `str()` em `textoParaClassificacao` | 6 |
| `ids` iterado sem exigir lista | 6 |
| `dict.get` sem filtrar item não hasheável | 6 |
| `"opcoes": None` no interrupt | 2 |
| `strip()` no lugar de `trim_js` em `mesmoConjuntoDeOpcoes` | 7 |
| `LIMITE_RODADAS` com `>` no lugar de `>=` | 4 |
| sumarização a partir de `rodada > 3` | 5 |
| `ORQUESTRADOR_INCLUIR_PLANEJADOS` comparado sem caixa | 8 |

## 7. Critérios de aceite

- [ ] Commit próprio, no começo da branch, trazendo o #242 para o fluxos (0.1) e dizendo que atualiza código mergeado.
- [ ] 2 testes traduzidos e os novos da seção 6 passando sem rede.
- [ ] Tabela da seção 0.2 com um teste por linha.
- [ ] Conferência diferencial e varredura contra develop @ `1157a6d`, com o resultado no PR. **Todo item (lido) desta spec confirmado ou corrigido por execução**, com a correção registrada.
- [ ] Mutações executadas, com a lista e o resultado no PR.
- [ ] `MIGRACAO.md` com a seção do módulo.
- [ ] `ruff`, `ruff format --check`, `mypy` strict e `pytest` verdes; jobs `test` e `imagem` verdes.

## 8. Decisões (aprovadas em 2026-10-16)

**D-1. `resumo: null` vindo do modelo** (`resumoRelato`, conflito da seção 0.2). **Aprovada: (a), divergência aceita e registrada.** É o mesmo colapso de `undefined` e `null` do `rg` e do `id`.

- **develop (lido):** guarda `null`. `textoParaClassificacao` testa `=== undefined` e manda `"null\n<última resposta>"` à classificação e à desambiguação. **Todo o histórico anterior se perde** até a próxima sumarização, que também resume `"null\n…"`.
- **Python:** `None` = `undefined`. Trata como "ainda não sumarizou" e manda o histórico bruto.
- **Alcance:** só acontece se o modelo violar o schema (`resumo` é obrigatório e string). A falha da chamada já cai no fallback, que devolve o texto original.
- **Opções:**
  - (a) aceitar como divergência registrada;
  - (b) distinguir os dois no canal (por exemplo, gravar o texto `"null"`) para reproduzir develop.
- **Recomendação: (a).** É o mesmo colapso de `undefined` e `null` das divergências do `rg` e do `id` no fluxos. O Python fica com o histórico, e develop o perde. Reproduzir exigiria codificar no canal uma distinção que só serve para preservar a perda.

**D-2. Escopo do #242 neste módulo.** **Aprovada.**

- A parte de fluxos do #242 (0.1) entra aqui, num commit próprio no começo da branch, como o #226 no fluxos. A parte de rota entra no `api`.
- **Cuidado de base:** o catálogo cai de 76 para 9 opções, e isso muda a base de referência. **A conferência diferencial roda contra develop @ `1157a6d`, com o #242 dentro.** Comparar com `0aecd98` seria comparar com um comportamento que não existe mais.
- **Por que aqui:** o orquestrador classifica contra o catálogo. Testar o grafo contra o catálogo de `0aecd98` (76 opções) seria testar contra um contrato que develop já abandonou.

## 9. Achados (defeitos de develop, a confirmar por execução)

| # | Achado | Onde | Efeito |
|---|---|---|---|
| A1 | (lido) **O texto de fallback da desambiguação fala de opções que não existem.** `TEXTO_FALLBACK` é "Pra te ajudar melhor, qual dessas opções descreve o que você precisa?", mas o interrupt é `tipo: "texto"`, sem opções, desde a decisão de 2026-09-11 (`graph.ts:140-144`) | `ia/desambiguar.ts`; `graph.ts:146-149` | Na falha do Bedrock (e sempre em `APP_ENV=test`), a pessoa recebe uma pergunta sobre "dessas opções" sem nenhuma opção na tela |
| A2 | (lido) **`tokensGastosRodada` perde o custo da sumarização.** `pedirDesambiguacao` soma os tokens do resumo em `tokensGastosRodada`, e o `classificar` seguinte sobrescreve o campo (`:65`) antes de qualquer leitura | `graph.ts:171`, `:65` | O log `tokensGastosTotal` da rota subconta as rodadas com sumarização. O total da conversa (`tokensGastosConversa`) está certo |
| A3 | (lido) **Id repetido na saída do modelo vira desambiguação de um candidato com ele mesmo.** `plausiveis` não remove duplicatas | `graph.ts:58` | Pergunta desnecessária, e a 5ª rodada termina em `naoIdentificado`, hoje `outros` na Tykhe. Depende de #212 |
| A4 | (lido; a verificar no banco) **A pergunta real compartilhada (#32) pode ter ficado sem uso com o #242.** Ela só vale entre candidatos com pergunta raiz na tabela `perguntas`. Os 9 do catálogo padrão são 2 implementados e 7 da Tykhe, e os da Tykhe não têm pergunta raiz | `graph.ts:106-116` | Sem a variável, o caminho do banco pode nunca disparar. Não é defeito por si, mas é código que só os testes exercitam |

Nenhum vira issue antes de ser executado na conferência diferencial (regra do `MIGRACAO.md`). Os confirmados vão para o `MIGRACAO.md`, em "Melhorias registradas", e os que tiverem efeito para a pessoa atendida ganham issue.

## Dependências

- `migration` @ `0161132`: fluxos, subgrafos, ia, integracoes, persistencia e `shared/`.
- develop @ `1157a6d`.
- Issues afetadas: #212, #222, #225, #240 (no `api`).
