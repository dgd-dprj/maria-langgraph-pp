# SDD — Módulo `api`

Parte de #208. Issue: #246. Branch: `refactor/246-api-python`, criada a partir de `migration` @ `05bb1bf` (depois do orquestrador). **Fonte de comportamento: develop @ `1157a6d`.** **As linhas citadas (`arquivo:linha`) são de `1157a6d`.**

**Regra desta spec** (`MIGRACAO.md`, "Padrão: afirmação sobre desfecho inferida do código, sem execução"):
- **(lido):** a afirmação sobre develop veio da leitura do código. Cada uma vira cenário da conferência diferencial (seção 7) antes do PR.
- **(executado):** a afirmação já rodou.
- **Lacuna:** a lição do orquestrador vale aqui. A varredura e a conferência acham o que nenhuma afirmação cobre, e neste módulo a entrada vem de fora, por HTTP.

| Origem (develop) | Destino (migration) |
|---|---|
| `src/app.ts` (108 linhas) | `src/maria/app.py`: registro das rotas, autenticação, tratadores de erro, log de requisição |
| `src/server.ts` (18) | `src/maria/main.py`: pré-aquecimento do catálogo de embeddings no boot (#180) |
| `src/rotas/fluxos.ts` (27) | `src/maria/api/fluxos.py` |
| `src/rotas/atendimentos.ts` (611) | `src/maria/api/atendimentos.py`: criar, consultar, responder, TTL (#166, #227, #234) |
| `src/rotas/orquestrador.ts` (254) | `src/maria/api/orquestrador.py`: inclui `redirecionado`/`tipoCaso` do #242 |
| `src/rotas/webhookWhatsapp.ts` (193) | `src/maria/api/webhook_whatsapp.py`: bridge do WhatsApp (#198, #203, #225) |
| `src/shared/respostaSimNao.ts` (#234) | completa `src/maria/shared/respostas.py` com `normalizar_resposta` e `resposta_eh_nao` |
| 74 testes: `app` 23, `contratoTykhe` 4, `orquestrador` 17, `ttlInatividade` 7, `webhookWhatsapp` 13, `http.test.ts` de violência doméstica 7 e de pessoa presa 3 | `tests/api/` |
| 50 fixtures HTTP e 5 de log (`tests/fixtures/contrato/`) | conferidas byte a byte (seção 6) |

**Fora deste módulo:**
- os painéis do Grafana (módulo corte);
- `docs/` (módulo documentacao);
- `scripts/` (módulo scripts).

---

## 0. O que mudou e o que já existe

### 0.1 As fixtures de contrato são de `4e695f2`, e a régua é `1157a6d`

As 50 fixtures HTTP e as 5 de log foram gravadas na fundação, com develop @ `4e695f2` rodando de verdade (receita na #209). Desde então, develop mudou em três PRs que tocam o contrato:

| PR | O que muda no contrato | Fixtures afetadas (lido) |
|---|---|---|
| #226 (#217) | A retomada depois da confirmação de TTL devolve a resposta guardada | `ttl-confirmacao-200` foi gravada com a store em memória, que já devolvia; a mudança é no Postgres. **Provavelmente não muda** |
| #234 (#227) | A confirmação de TTL aceita "sim" e repete a pergunta quando não reconhece | `ttl-recusa-expirado-200`, e possivelmente as outras `ttl-*` |
| #242 (#225) | "Não identificado" vira `redirecionado`/`outros`; aparecem `tipoCaso` e o bridge encerra com orientação fixa | **`orquestrador-nao-identificado-200` muda com certeza** (a fixture mostra `handoff_humano`); a do orquestrador identificado e a de desambiguação, a conferir |

**Proposta (D-1): regravar as 50 fixtures HTTP e as 5 de log contra develop @ `1157a6d`, num commit próprio, antes da tradução.**
- **Como:** com a receita da #209 e o worktree que já existe em `%TEMP%\m1157a6d`.
- **O diff contra as fixtures antigas vai no commit,** explicado fixture por fixture. Cada diferença precisa ter causa num dos três PRs. Uma diferença sem causa é achado.

### 0.2 O que os módulos anteriores entregam

| Peça | Onde | Situação |
|---|---|---|
| `criar_app`, lifespan, ordem de inicialização, `/health` | `app.py` (fundação) | Pronta; faltam as rotas, a autenticação e os tratadores |
| `main.py` (um worker, `0.0.0.0:3001`, `access_log=False`) | fundação | O log de requisição no formato do Fastify fica para este módulo |
| Logger pino (envelope, `serializar_erro`, nível fixo de bibliotecas) | `shared/logger.py` | Pronto; falta o log de requisição |
| `contexto_atual()` (`chatId`, `fluxoId` da config do run) | `shared/contexto.py` | Pronto |
| Stores (`registrar`, `buscar_flow_id`, `concluir`, `buscar_atividade`, `marcar_atividade`, `marcar_aguardando_confirmacao_ttl`, `resolver_confirmacao_ttl_continuar`) | `shared/atendimentos_db.py` | Prontas (#226 incluído) |
| `buscar_fluxo`, `fluxos_por_id`, `extrair_metadados` por fluxo, `TIPOS_TYKHE`, `tipo_tykhe_por_id`/`_por_caso` | `fluxos/` | Prontos (`extrair_metadados` na ordem de develop, conferida no fluxos) |
| Grafo do orquestrador | `orquestrador/graph.py` | Pronto (#244) |
| `extrair_mensagem_whatsapp`, `extrair_status_whatsapp`, `enviar_mensagem_whatsapp` | `integracoes/whatsapp.py` | Prontos |
| `resposta_eh_sim` | `shared/respostas.py` | Pronto. **Faltam `normalizar_resposta` e `resposta_eh_nao`** (#234) |
| `aquecer_catalogo` (#180) | `shared/embeddings_fluxos.py:251` | Pronto; o disparo no boot (fire-and-forget, como `server.ts:16-18`) entra aqui |

## 1. Contexto

Quatro grupos de rota, com autenticação diferente:

| Rota | Autenticação | Consumidor |
|---|---|---|
| `GET /health` (e `HEAD`) | nenhuma | ALB |
| `GET /docs`, `/docs/json` | nenhuma | pessoas (Swagger UI) |
| `GET /fluxos`, `POST /atendimentos`, `GET /atendimentos/:chatId`, `POST /atendimentos/respostas`, `POST /atendimentos/orquestrador` | Bearer (`API_KEY`) | Tykhe; o bridge, por chamada interna |
| `GET`/`POST /webhook/whatsapp` | nenhuma (`verify_token` só no `GET`) | Meta |

**Canais por ambiente** (verificado em 2026-10-16 no `ecs.tf` e no `release.tf` de `main` e de develop):
- **Tykhe:** produção e release.
- **Bridge do WhatsApp:** **só release.** As quatro variáveis `WHATSAPP_*` existem apenas no `release.tf`.
- **Em produção a rota do webhook existe,** mas sem `WHATSAPP_VERIFY_TOKEN`: o `GET` de verificação devolve 403 sempre (ver achado A1).

## 2. Contrato

- **HTTP:** status, `content-type`, `Location` e corpo **byte a byte** iguais às fixtures (regravadas, D-1). Campos ausentes são omitidos, e nunca `null`.
- **Ordem das chaves no corpo:** é a do **schema de resposta** de cada rota, porque o `fast-json-stringify` serializa na ordem declarada (lido; a fixture `erro-validacao-tipo-coagido-200` é coerente com isso). Propriedades além do schema só saem onde há `additionalProperties: true`, como no `erroSchema` do 409 (`atendimentos.ts:140`).
- **Logs:** os eventos de negócio (`atendimento_criado`, `pergunta_enviada`, `atendimento_finalizado`, `resposta_recebida`, `ttl_confirmacao_solicitada`, `ttl_confirmacao_repetida`, `atendimento_expirado`, `orquestrador_*`, `whatsapp_*`) têm os mesmos campos e valores. O **log de requisição** (`incoming request`/`request completed`, com `reqId` UUID, `req`, `res.statusCode`, `responseTime`) segue o envelope do Fastify, conferido contra as 5 fixtures de log.
- **Banco:** `atendimentos` gravado igual, inclusive `concluir` com `destino` e `tokens_*` (#83).

## 3. Comportamento: pontos onde a tradução ingênua erra

### 3.1 A ordem do pipeline do Fastify

**(lido)** O Fastify trata uma requisição nesta ordem:
1. procura a rota; se não acha, 404 no formato 4;
2. `onRequest` com o bearer-auth; se falha, 401 no formato 2;
3. parser do `content-type`: 415 no formato 5; JSON inválido, 400 `{}`;
4. validação do schema do corpo, com coerção (3.2): 400 `{}`;
5. o handler: formatos 6 e 7, ou sucesso;
6. a serialização da resposta pelo schema (3.3).

Um erro não tratado em qualquer ponto vira 500 no formato 3.

**O FastAPI faz diferente:**
- valida o corpo junto com as dependências e devolve **422** com `detail`;
- pode avaliar a autenticação depois do corpo.

Por isso a tradução **não usa a validação do FastAPI** nas rotas de negócio. Cada rota lê o `Request` cru, e um pipeline próprio reproduz a ordem acima, com tratadores de exceção que devolvem os sete formatos. Teste: cada combinação de "erro em duas etapas" (por exemplo, sem autenticação **e** JSON inválido) dá o erro da etapa que vem primeiro.

### 3.2 Coerção de tipos do ajv no corpo

**(executado na captura)** `chatId: 12345` vira `"12345"` e responde 200 (fixture `erro-validacao-tipo-coagido-200`).

**(lido)** O ajv do Fastify usa `coerceTypes`:
- número e booleano viram string;
- `null` vira `""` num campo string;
- objeto ou lista num campo string dão 400;
- em `dadosConhecidos` (`type: object`), lista e `null` dão 400.

Duas consequências que a tradução precisa reproduzir:
- **`mensagem: null` no orquestrador vira `""`** e cai no caminho do relato vazio (ponto do `MIGRACAO.md`);
- **`resposta: null` vira `""`** e cai no 400 "resposta obrigatório".

O Pydantic, em modo lax, **não** converte número em string. A coerção fica num validador próprio, com as regras do ajv, e cada regra vira cenário da varredura.

### 3.3 Serialização da resposta pelo schema

**(lido)** O `fast-json-stringify` faz três coisas na saída:
- **descarta** campos não declarados (o comentário de `orquestrador.ts:30-36` registra o achado ao vivo);
- **converte** para o tipo do schema: uma `pergunta` numérica do modelo (#212, achado do orquestrador) sai como `"7"` em `resposta`, e um objeto sai como o template do JS;
- **omite** o que é `undefined`.

A tradução serializa com um serializador próprio, guiado pelo mesmo schema declarativo, e não com o `jsonable_encoder` do FastAPI. A saída do modelo de outro tipo, que o orquestrador deixou para cá, é testada aqui.

### 3.4 Os sete formatos de erro (#208)

| # | Status | Corpo | Quando |
|---|---|---|---|
| 1 | 400 | `{}` | Falha de schema ou de parse |
| 2 | 401 | `{"error":"missing authorization header"}` ou `{"error":"invalid authorization header"}` | Bearer-auth |
| 3 | 500 | `{"statusCode":500,"error":"Internal Server Error","message":"<texto>"}` | Erro não tratado. O teste compara tudo menos o valor de `message` (#210) |
| 4 | 404 | `{"message":"Route GET:/x not found","error":"Not Found","statusCode":404}` | Rota inexistente, inclusive com barra final |
| 5 | 415 | `{"statusCode":415,"code":"FST_ERR_CTP_INVALID_MEDIA_TYPE","error":"Unsupported Media Type","message":"Unsupported Media Type"}` | `content-type` sem parser |
| 6 | 400/404/409 | `{"erro":"<mensagem>"}` | Erros de negócio dos handlers |
| 7 | 409 | `{"erro":"<mensagem>", ...atendimento}` | Resposta em atendimento concluído ou expirado |

Fora da tabela:
- o 403 do webhook tem corpo vazio;
- o `HEAD /health` devolve 200 com corpo vazio e `content-type: application/json; charset=utf-8` (executado na captura, fixture `health-head`).

### 3.5 `Command(resume="")`: 500 em develop, aceito em Python

- **develop (executado na #217):** `new Command({ resume: "" })` lança `EmptyInputError`, e a rota responde 500. O LangGraph JS trata `""` como "sem resume".
- **Python (executado em 2026-10-16, LangGraph 1.2.14):** `Command(resume="")` **retoma o grafo com `""`** e segue. Numa pergunta sim/não, `""` conta como "não".
- **Onde acontece:** as rotas barram `resposta` vazia com 400 (#185). O único caminho até `resume=""` é a **retomada depois da confirmação de TTL** (`atendimentos.ts:542`). Ela acontece quando `resolver_confirmacao_ttl_continuar` devolve vazio ou `None`, o que levava à #217 e, depois do #226, só pode acontecer com a flag de confirmação desfeita no meio do caminho (concorrência).
- **Decisão D-2.**

### 3.6 `TTL_INATIVIDADE_HORAS` com a semântica do `Number()` do JS

**(lido)** `Number(process.env.TTL_INATIVIDADE_HORAS ?? "24")` é lido a cada requisição:

| Valor | JS | `float()` do Python |
|---|---|---|
| `"abc"` | `NaN`, e `horasInativo > NaN` é sempre falso: **o TTL nunca dispara** | lança: 500 em toda resposta |
| `""` | `0`: o TTL dispara sempre | lança |
| `"0x10"` | `16` | lança |
| `" 5 "` | `5` | `5` |

A tradução usa uma função `numero_js` que reproduz o `Number()`, e cada linha da tabela tem teste.

### 3.7 `chatId` obrigatório fora de `APP_ENV=test`, nas duas rotas

`criarAtendimento` (`atendimentos.ts:270`) e a rota do orquestrador (`orquestrador.ts:149`) testam `!chatId && NODE_ENV !== "test"`:
- **`""` conta como ausente;**
- em `test`, um UUID é gerado, com `warn` em `criarAtendimento`.

No Python, a condição é `APP_ENV != "test"`. A imagem define `APP_ENV=production` (`Dockerfile`), como o `NODE_ENV=production` de develop. Com `APP_ENV` ausente, o `chatId` é obrigatório.

### 3.8 `dadosConhecidos` e o estado do grafo

- **`viaOrquestrador`** vindo de `dadosConhecidos` é **descartado**, e só o parâmetro explícito vale (#191, `atendimentos.ts:319`).
- **Na rota do orquestrador,** `tokensGastos` é **sobrescrito** pelo da triagem (`orquestrador.ts:237-240`).
- **Em `POST /atendimentos`,** `dadosConhecidos.tokensGastos` entra no reducer de soma:
  - **(executado na captura)** com `null`, develop dá 500 "Cannot read properties of null (reading 'input')" (fixture `erro-nao-tratado-500`);
  - **(lido)** com texto ou objeto parcial, o JS soma `undefined` e dá `NaN`, que o schema serializa de algum jeito, e o Python lançaria (achado A3, para a varredura).
- **`enderecoDetalhado` inteiro nos metadados (#237):** o `extrair_metadados` de violência doméstica já devolve o `dadosPessoa` inteiro (spec 05). A rota não filtra, e a tradução também não.
- **Qualquer canal pode ser pré-preenchido (#240):** o LangGraph filtra a entrada só pelos canais do estado.

### 3.9 Bridge do WhatsApp

- **Chamada interna:** o `app.inject` vira uma chamada ASGI em processo (`httpx` com `ASGITransport`), com o mesmo `Authorization`. **(lido)** O `inject` do Fastify passa pelo pipeline inteiro, inclusive pelo log de requisição. A conferência confirma se as linhas internas aparecem nos logs de develop.
- **Estado em memória por número:** `conversasAtivas` e a fila serializada por número (`executarSerializado`). Em Python, um `dict` e um `asyncio.Lock` por número, com **um worker** (já é assim no `main.py`).
- **`#sair`:** `trim().toLowerCase() === "#sair"`, com `trim_js` e `lower()`.
- **`GET` de verificação:** `200 text/plain` com o `challenge`, ou `403` com corpo vazio. O token é lido a cada requisição.

### 3.10 Erro não tratado

O tratador de erro do Fastify loga o erro e responde no formato 3, com `message = err.message`. No Python, `message` é o `str(exc)`. As notas que o LangGraph anexa à exceção não entram no `str()` (verificado no orquestrador). Para as exceções que a tradução reproduz com a mensagem do JS (`TypeError` do `ids.map`, do `.trim()`, do `null.toUpperCase()`), `message` é igual; nas demais, difere, e o teste compara tudo menos o valor (#210).

### 3.11 `normalizarResposta` e o TTL (#234)

`normalize("NFD")`, remoção de U+0300 a U+036F, `trim()`, `toLowerCase()`, como o `resposta_eh_sim` já faz. Os conjuntos `CONTINUAR_TTL` e `RECOMECAR_TTL` são reproduzidos byte a byte.

## 4. O que não muda

Rotas, métodos, status, corpos, headers, `_links`, mensagens fixas, eventos e campos de log, gravações no banco, autenticação, o `thread_id` `orquestrador:<chatId>`, a idempotência do `POST /atendimentos` e o estado em memória do bridge.

## 5. Observabilidade

- **Log de requisição** no envelope do Fastify (seção 2), conferido contra as 5 fixtures de log.
- **Eventos de negócio** com os mesmos campos. `chatId`/`fluxoId` são a correlação; nenhum dado pessoal novo.
- **Achado A2:** no bridge, o `chatId` é `whatsapp:<número>:<timestamp>`, e com ele **o telefone vai a todo log e à tabela `atendimentos`**. Só existe em release, com números de teste. A tradução reproduz.

## 6. Testes que provam

**Traduzidos:** os 74 de develop (cabeçalho), com o checkpointer e as stores em memória e o Verde em mock.

**Novos:**
1. **Contrato:** as 50 fixtures HTTP, uma por teste, byte a byte (corpo bruto, status, `content-type`, `Location`). O 500 compara tudo menos o valor de `message`.
2. **Logs:** as 5 instâncias das fixtures de log, linha a linha, ignorando `time`, `pid`, `hostname`, `reqId` e `responseTime`.
3. **Pipeline (3.1):** cada par de erros em etapas diferentes dá o erro da primeira etapa.
4. **Coerção (3.2):** cada regra do ajv, nos campos de cada rota.
5. **Serialização (3.3):** a ordem das chaves pelo schema; campo não declarado descartado; `pergunta` numérica e objeto em `resposta`.
6. **`resume=""` (3.5):** o comportamento escolhido na D-2.
7. **`numero_js` (3.6):** cada linha da tabela.
8. **`chatId` (3.7):** ausente, `""` e numérico, em `test` e fora de `test`, nas duas rotas.
9. **`dadosConhecidos` (3.8):** `viaOrquestrador` descartado; `tokensGastos` sobrescrito no orquestrador; `null` dá 500.
10. **Bridge (3.9):** duas mensagens simultâneas do mesmo número são processadas em série; `#sair` com e sem conversa ativa; `redirecionado` com `sair` e com outro `tipoCaso`.

**Mutações a executar antes do PR** (a lista cresce com a conferência):

| Mutação | Teste |
|---|---|
| Validação do FastAPI (422) no lugar do pipeline próprio | 3 |
| Autenticação depois do parse do corpo | 3 |
| Pydantic lax no lugar da coerção do ajv | 4 |
| `jsonable_encoder` no lugar do serializador por schema | 5, 1 |
| `float()` no lugar de `numero_js` | 7 |
| `if not chat_id` trocado por `chat_id is None` | 8 |
| `viaOrquestrador` aceito de `dadosConhecidos` | 9 |
| Lock por número removido | 10 |
| `strip()` no `#sair` | 10 |

## 7. Conferência diferencial e varredura

- **Contra develop @ `1157a6d`, por HTTP:** os dois servidores rodam de verdade, develop no worktree `%TEMP%\m1157a6d`, com o mesmo Verde em mock e o mesmo Bedrock falso do orquestrador. Os mesmos cenários rodam nos dois lados, e a comparação é byte a byte para status, headers relevantes, corpo e as linhas de log normalizadas.
- **Varredura, com a entrada vindo de fora:** cada campo de corpo de cada rota (`chatId`, `flowId`, `resposta`, `mensagem`, `dadosConhecidos` e cada canal dentro dele, inclusive `tokensGastos`) recebe `null`, texto, número, booleano, `{}`, `[]`, `""` e a chave ausente. Também entram:
  - `content-type` variados;
  - corpo vazio;
  - JSON inválido;
  - cada combinação de autenticação.
- **Cada item (lido) desta spec vira cenário.**

## 8. Critérios de aceite

- [ ] Fixtures regravadas contra `1157a6d` (D-1), em commit próprio, com o diff explicado.
- [ ] `respostas.py` completo (#234) em commit próprio.
- [ ] 74 testes traduzidos e os novos da seção 6 passando sem rede.
- [ ] As 50 fixtures HTTP e as 5 de log conferidas byte a byte.
- [ ] Conferência diferencial e varredura (seção 7), com o resultado no PR e todo item (lido) confirmado ou corrigido.
- [ ] Mutações executadas, com a lista e o resultado no PR.
- [ ] `MIGRACAO.md` com a seção do módulo.
- [ ] `ruff`, `ruff format --check`, `mypy` strict e `pytest` verdes; jobs `test` e `imagem` verdes.

## 9. Decisões (aprovadas em 2026-10-16)

| Decisão | O que fica |
|---|---|
| **D-1** | Regravar, em commit próprio, separando o que mudou pelo #234, pelo #242 e o que não mudou. O par antes/depois da `orquestrador-nao-identificado-200` é a evidência da mudança de desfecho registrada na #244 |
| **D-2** | Reproduzir o 500. Aceitar `""` e contar como "não" é responder no lugar da pessoa atendida, sem ela saber |
| **D-3** | Servir o `/docs` |
| **D-4** | Dois PRs. O primeiro dá porta HTTP aos fluxos, que é o que o Ícaro precisa para testar |

**Requisito novo (2026-10-16): rodar a API de fora.** O Ícaro vai rodar a API no computador dele, e o **PR 1** passa a incluir o mínimo para alguém de fora subir o serviço sem depender de quem fez a migração:
- um documento próprio (`docs/rodar-localmente.md`, com link no README) com:
  - requisitos;
  - instalação;
  - variáveis de ambiente em tabela;
  - como rodar;
- o que acontece sem `DATABASE_URL` (checkpointer e stores em memória, que não persistem) e sem credencial AWS (o que funciona em mock e o que falha);
- comandos que funcionam colados direto, **testados numa pasta limpa** antes do PR.

A reescrita completa do README continua no módulo 10 (documentacao).

### Texto original das decisões

**D-1. Regravar as fixtures contra `1157a6d` antes da tradução.**
- **Recomendação: sim.** A régua é `1157a6d`, e pelo menos uma fixture (`orquestrador-nao-identificado-200`) descreve um comportamento que develop não tem mais.
- **Alternativa:** manter as fixtures de `4e695f2` e editar à mão as afetadas. Isso transforma fixture gravada em fixture inferida, que é exatamente o erro que a regra do desfecho existe para evitar.

**D-2. `Command(resume="")`: reproduzir o 500 de develop ou aceitar o Python.**
- **develop:** 500 (`EmptyInputError`).
- **Python:** retoma com `""`, e numa pergunta sim/não isso conta como "não", **sem nenhum sinal**.
- **Recomendação: reproduzir o 500,** com uma guarda antes do `invoke` que lança com a mesma mensagem do JS. O caminho só existe por concorrência na confirmação de TTL. A falha visível é melhor que um "não" silencioso, que mudaria o desfecho do atendimento sem ninguém notar. É o raciocínio do D-1 do fluxos, só que no sentido inverso: aqui é o JS que falha alto.

**D-3. `/docs` e `/docs/json`.**
- Em develop, o Swagger UI do Fastify é gerado dos schemas. O FastAPI gera outro documento e outra página.
- Não é contrato com a Tykhe: nenhuma fixture cobre essas rotas, que ficam fora da autenticação.
- **Recomendação:** servir `/docs` e `/docs/json` gerados a partir do mesmo schema declarativo usado na serialização (3.3), e aceitar a divergência no conteúdo, com registro.

**D-4. Um PR ou dois.**
- O módulo tem cerca de 1.200 linhas de origem e 74 testes, além da regravação das fixtures.
- **Proposta:** uma issue e dois PRs, na ordem:
  1. **núcleo:** pipeline, autenticação, erros, log de requisição, `/fluxos`, `/atendimentos` com TTL;
  2. **orquestrador e bridge.**
- O primeiro já deixa os fluxos com porta HTTP. O segundo fecha o caminho para teste.

## 10. Achados (lido; a confirmar na conferência)

| # | Achado | Onde | Efeito |
|---|---|---|---|
| A1 | **Achado de segurança no webhook do WhatsApp, confirmado por execução em 2026-10-16.** Os detalhes ficam fora do repositório público, num registro privado (GitHub Security Advisory), até a correção | webhookWhatsapp.ts | A tradução reproduz develop; a correção segue pelo registro privado |
| A2 | Telefone dentro do `chatId` do bridge, em todo log e na tabela `atendimentos` | `webhookWhatsapp.ts:47` | Dado pessoal em log; só release |
| A3 | `dadosConhecidos.tokensGastos` vindo da Tykhe entra no reducer de soma | `atendimentos.ts:320`; `shared/tokensAcumulados.ts` | Com `null`, 500 (executado). Com texto ou objeto parcial, `NaN` em develop. Mesma família do #240 |
| A4 | `TTL_INATIVIDADE_HORAS` inválido desliga o TTL em silêncio (`NaN`) | `atendimentos.ts:28-30` | Configuração errada sem nenhum sinal |
| A5 | Relato vazio no orquestrador vai para `outros` sem classificação; em produção hoje, para `handoff_humano` | `orquestrador.ts:141-157` | Já registrado no `MIGRACAO.md`, com a consulta de contagem na #208 |

## Dependências

- `migration` @ `05bb1bf`: todos os módulos de domínio.
- develop @ `1157a6d`, com o worktree em `%TEMP%\m1157a6d` para a regravação e a conferência.
- Issues afetadas: #185, #191, #198, #203, #210, #211, #217, #225, #227, #228, #237, #240.
