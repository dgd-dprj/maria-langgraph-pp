# Arquitetura

## O que é

Maria é a ponte entre a **Tykhe** (plataforma de chatbot que atende o cidadão — WhatsApp/web) e o **Verde** (sistema da Defensoria Pública do RJ que tem os dados reais: pessoa presa, processo, endereço, órgãos de atendimento). A Tykhe não fala com o Verde diretamente — ela fala com esta API, que decide as perguntas, chama o Verde quando precisa, e devolve a próxima pergunta (ou a conclusão) num contrato HTTP fixo.

Cada "conversa" é um **atendimento**: uma sequência de perguntas e respostas que termina em `concluido` (resolvido pelo bot) ou `handoff_humano` (alguém da Defensoria precisa assumir).

![Diagrama de componentes AWS](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/arquitetura.png)

> O diagrama acima não mostra o CloudWatch: o painel de acompanhamento (Visor Maria, repositório `dgd-dprj/visor-maria`) lê métricas e logs dele direto, só leitura. O Grafana foi removido (#380). Ver seção Observabilidade abaixo.

## Por que LangGraph

O fluxo de cada atendimento é uma máquina de estados com pausa/retomada: pergunta → espera resposta → decide a próxima pergunta a partir do que já sabe → repete até concluir. LangGraph modela isso nativamente:

- **`interrupt()`** pausa o grafo no meio de um nó e devolve o controle pro chamador (aqui, a resposta HTTP) — sem isso, teríamos que serializar "em que ponto da conversa estamos" manualmente a cada request.
- **Checkpointer** persiste o estado do grafo entre chamadas HTTP (cada POST é uma invocação nova do processo, sem estado em memória entre requests) — ver seção Persistência abaixo.
- **`StateGraph` + `add_conditional_edges`** dá um jeito declarativo de desenhar "depois desta pergunta, vai pra cá ou pra lá dependendo da resposta" — o desenho do grafo em cada `src/maria/fluxos/<fluxo>/graph.py` É a documentação executável do fluxo de negócio.
- **Compilação sob demanda:** o grafo é compilado na primeira chamada (`src/maria/fluxos/_fabrica.py`), e o checkpointer é criado na inicialização da aplicação. Importar um fluxo não conecta em nada.

A alternativa (state machine manual, switch/case por "qual pergunta estamos") funcionaria, mas LangGraph já resolve pausa/retomada + persistência prontos — não reinventar isso foi a troca.

## HTTP: FastAPI com o pipeline da versão anterior

API fina, poucas rotas (`/atendimentos`, `/atendimentos/:chatId`, `/atendimentos/respostas`, `/atendimentos/orquestrador`, `/fluxos`, `/webhook/whatsapp`). O servidor é FastAPI sobre uvicorn, mas **as rotas não usam a validação do FastAPI**: passam por um pipeline próprio (`src/maria/api/pipeline.py`) que reproduz o Fastify da versão TypeScript — a ordem de autenticação, parse e validação, a coerção de tipos do ajv, a serialização pelo schema de resposta e os sete formatos de erro. Motivo: o contrato com a Tykhe foi conferido byte a byte contra a versão anterior (50 respostas gravadas, `tests/fixtures/contrato/`), e uma tradução direta para a validação do FastAPI mudaria status e corpos sem erro.

- **Schema-first**: cada rota declara corpo e respostas como JSON Schema (`src/maria/api/esquemas.py`); o OpenAPI de `/docs` sai das mesmas definições (`src/maria/api/docs.py`).
- **Testes por ASGI**: a API inteira (rotas + auth + serialização) roda nos testes sem abrir porta, chamada direto pelo ASGI.

## Estrutura de pastas

```
src/maria/
  main.py               # sobe o uvicorn (1 worker, porta 3001)
  app.py                # monta a aplicação: rotas, autenticação, ordem de inicialização (lifespan)
  api/                  # HTTP: pipeline.py (a ordem e os erros do Fastify), atendimentos.py (core), orquestrador.py,
                        #   basicas.py (/health, /fluxos), webhook_whatsapp.py, docs.py (/docs)
  fluxos/
    __init__.py         # registro: flowId (uuid) -> {grafo, schema de metadados, mensagens}
    pessoa_presa/       # grafo + state + metadados e mensagens deste fluxo
    violencia_domestica/ # idem
    padrao/             # grafo genérico (1 nó, conclui na hora) pra categoria sem fluxo próprio ainda
    tipos_tykhe.py      # os 7 tipos de caso que a própria Tykhe atende (#225)
  orquestrador/         # classifica um relato livre pro flowId certo (ver docs/fluxo-orquestrador.md)
  subgrafos/            # StateGraph reaproveitável, sem flowId próprio — embutido como nó dentro de um fluxo (ver docs/novo-fluxo.md)
  integracoes/
    verde.py            # toda chamada HTTP pro Verde mora aqui (ver docs/integracao-verde.md)
    whatsapp.py         # envio pela API da Meta (bridge do WhatsApp)
    cliente_http.py     # cliente HTTP único do processo, com os parâmetros do fetch da versão anterior
  ia/                   # chamadas de IA (Bedrock): classificar, desambiguar, extrair, reescrever, sumarizar
  shared/
    checkpointer.py     # persistência do LangGraph (Postgres, schema próprio)
    atendimentos_db.py  # tabela chatId -> flowId (+ colunas de desfecho pra métricas)
    perguntas_db.py     # árvore de perguntas do Verde por categoria
    fluxos_planejados_db.py # catálogo de categorias sem fluxo implementado ainda
    embeddings_fluxos.py # busca por similaridade (pgvector)
    pool.py             # parâmetros dos pools Postgres
    logger.py / contexto.py # log JSON no envelope do pino + correlação por fluxoId/chatId
    _js.py              # semântica do JavaScript que a tradução reproduz (verdade, trim, Number())
tests/                  # espelha src/maria/ (ver docs/testes.md)
scripts/                # utilitários de manutenção, fora da imagem (ver scripts/README.md)
infra/
  terraform/            # toda a infra AWS
docs/                   # este diretório
```

Cada fluxo é uma pasta autocontida (`graph.py`, `state.py`, `api.py`) — adicionar um fluxo novo não toca nos outros, só registra em `src/maria/fluxos/__init__.py`.

## Persistência

Tudo no **mesmo** Postgres (RDS `maria-chat-prod-pg`, acessado via RDS Proxy compartilhado com o stack antigo), 4 preocupações diferentes:

1. **Checkpoints do LangGraph** (`AsyncPostgresSaver`, tabelas próprias que a lib cria, no schema `checkpoint_py`) — o estado de cada conversa em andamento, indexado por `thread_id` (= `chatId`; no orquestrador, `orquestrador:<chatId>`). Sem `DATABASE_URL` (testes), cai num `InMemorySaver` em memória. O schema é separado das tabelas que a versão TypeScript criava em `public`, porque as duas serializações são incompatíveis (plano de corte da #208).
2. **Tabela `atendimentos`** (`chatId -> flowId` + colunas de desfecho) — o checkpointer do LangGraph indexa só por `thread_id`, sem separar por fluxo; sem essa tabela, o mesmo `chatId` usado em 2 fluxos diferentes colidiria no mesmo checkpoint. Também guarda `status_final`/`motivo_handoff`/`tokens_*` pra consulta SQL direta, sem depender só de CloudWatch Logs. Desde a issue #166, guarda também `atualizado_em`/`aguardando_confirmacao_ttl`/`resposta_pendente_ttl` — controle de TTL de inatividade, já que o checkpointer do LangGraph em si não tem TTL nativo (isso é feature só do LangGraph Platform gerenciado, não do OSS self-hosted que usamos).
3. **`perguntas`/`assuntos_verde`/`flow_assuntos`** — árvore de perguntas do catálogo do Verde, coletada sob demanda (`scripts/coletar_arvore_perguntas_verde.py`), usada pelo orquestrador pra desambiguação (pergunta real do Verde quando todos os candidatos compartilham a raiz).
4. **`fluxo_embeddings`** (extensão `vector`/pgvector, `src/maria/shared/embeddings_fluxos.py`) — embedding da descrição de cada fluxo do catálogo, usado pelo orquestrador pra busca por similaridade (`embedding <=> ...::vector`) na hora de decidir qual fluxo melhor casa com o relato livre do usuário. **Com o catálogo de 9 opções de hoje, a busca não corta nada** (só age acima de 10; #256), mas o boot ainda indexa as descrições.

Todas as tabelas são criadas via `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD COLUMN IF NOT EXISTS` no código (sem ferramenta de migração formal — repo pequeno, não justificou ainda). Desde a issue #114, essa criação roda no **startup do processo** (bloqueia o health check até terminar), não mais na primeira request de negócio — evita o deploy ficar "saudável" antes do schema estar pronto de verdade.

## Autenticação

Bearer token fixo (`API_KEY`), um valor só por ambiente, guardado em Secrets Manager. A Tykhe é o único consumidor esperado (chamada servidor-a-servidor) — sem OAuth/JWT por usuário porque não tem usuário final autenticando, é a Tykhe autenticando como aplicação. `/health` fica fora da autenticação (o ALB não manda Bearer).

## Observabilidade

- **Logs estruturados** (JSON no envelope do pino, reproduzido em Python em `src/maria/shared/logger.py` para os painéis e as consultas continuarem valendo) — todo log de negócio carrega `chatId`/`fluxoId` pra correlacionar uma conversa inteira entre requests diferentes (`reqId` sozinho só correlaciona 1 request). `evento` é um campo fixo (`atendimento_criado`, `pergunta_enviada`, `atendimento_finalizado`, `verde_chamada`...) — filtra por isso, não pelo texto livre da mensagem.
- **CloudWatch Logs Insights** — consulta os logs acima. O painel de acompanhamento é o Visor Maria (`dgd-dprj/visor-maria`), que lê o CloudWatch e o GitHub, sem acesso ao banco.
- **Detecção de drift de Terraform** (`.github/workflows/terraform-drift.yml`) — roda `terraform plan` e falha se tiver mudança pendente, separado dos workflows de deploy de propósito (drift de infra não deve travar um fix de bug simples de subir).

## Infra (AWS)

- **ECS Fargate** (sem servidor pra gerenciar) atrás de um **ALB** único, com **CloudFront** na frente só pra ter HTTPS sem precisar de domínio próprio (certificado `*.cloudfront.net` grátis/automático — decisão documentada em `infra/terraform/cloudfront.tf`).
- **2 ambientes, mesmo padrão**: `prod` (deploy em push pra `main`) e `release` (deploy em push pra `develop`) — serviços ECS separados, mesmo cluster/ALB. A distribuição CloudFront do release injeta o header `X-Maria-Env: release`, que o ALB usa para rotear (`infra/terraform/release.tf`). Pelo Terraform, o release foi criado para testar com o **Verde de produção** ("quando a credencial chegar"), em paralelo ao `prod`, que aponta para a **homologação** (`release.tf:1-3`, `iam.tf:25-26`). Mas as credenciais do release **começam iguais às da homologação até a credencial de produção do Verde chegar** (`release.tf:20-22`), e o Terraform não sabe se ela chegou: os valores são gravados fora dele (`PREENCHER`, com `ignore_changes`). Qual Verde cada ambiente usa hoje só o segredo diz. O bridge do WhatsApp existe só no release.
- **VPC/subnets/RDS compartilhados** com um stack Terraform antigo (`data.terraform_remote_state.old`) — não duplica rede nem banco, só lê os IDs de lá. Esse repo nunca escreve no state antigo.
- **RDS Proxy compartilhado** — a app e o stack antigo se conectam ao Postgres pelo mesmo proxy; cada security group novo (task da app) ganha uma regra de ingress própria no SG do proxy, sem o stack antigo precisar saber desse repo na hora de escrever o `.tf` dele.
- **Deploy via GitHub Actions com OIDC** (sem chave AWS fixa guardada como secret) — token de curta duração emitido pelo GitHub a cada run, `assume-role` restrito pelo `sub` do token a só `main`/`develop`.
- **Tag semver + GitHub Release automáticos** (issue #145) — todo deploy que chega em `main` com sucesso ganha uma tag `vX.Y.Z` (job `tag` em `deploy-prod.yml`): bump calculado a partir dos tipos de commit desde a última tag (`feat` → minor, `BREAKING CHANGE` no corpo → major, qualquer outro caso → patch), Release criada com changelog gerado automaticamente (`gh release create --generate-notes`).
- **Secrets fora do Terraform** — todo valor real (token do Verde, senha do Postgres, API_KEY) é preenchido manualmente via `aws secretsmanager put-secret-value` depois do `apply` (o `.tf` só cria o secret vazio, com placeholder `"PREENCHER"`) — decisão deliberada pra nunca ter segredo real em texto plano no state/código.
- **Interface VPC Endpoint pro Bedrock** (`infra/terraform/bedrock-endpoint.tf`, issue #141) — tráfego das tasks pro Bedrock fica 100% dentro da VPC, sem passar pelo NAT Gateway/rota pública. Custo fixo (~US$14,60/mês, 2 AZs) supera a economia esperada no NAT pro volume de tráfego atual — decisão de arquitetura autorizada mesmo assim, não motivada por custo.

## O que NÃO tem (de propósito, por enquanto)

- **Migração de schema formal** — DDL idempotente no código, sem Flyway/Drizzle Kit (ver issue #114 e a seção Persistência acima).
- **Autoscaling** — 1 task fixa por ambiente, tráfego baixo não justifica ainda.
- **Domínio próprio** — `*.cloudfront.net` resolve HTTPS sem precisar de Route53/ACM.
- **Testes de contrato automatizados contra o Verde real** — `tests/integracao/` existe mas cobre pouco (só o Bedrock); a maior parte da validação contra a API real do Verde é feita manualmente (ver `docs/integracao-verde.md`), o que já causou mais de um bug descoberto tarde (ver esse mesmo doc).
