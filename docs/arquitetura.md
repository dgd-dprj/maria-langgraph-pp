# Arquitetura

## O que é

Maria é a ponte entre a **Tykhe** (plataforma de chatbot que atende o cidadão — WhatsApp/web) e o **Verde** (sistema da Defensoria Pública do RJ que tem os dados reais: pessoa presa, processo, endereço, órgãos de atendimento). A Tykhe não fala com o Verde diretamente — ela fala com esta API, que decide as perguntas, chama o Verde quando precisa, e devolve a próxima pergunta (ou a conclusão) num contrato HTTP fixo.

Cada "conversa" é um **atendimento**: uma sequência de perguntas e respostas que termina em `concluido` (resolvido pelo bot) ou `handoff_humano` (alguém da Defensoria precisa assumir).

![Diagrama de componentes AWS](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/arquitetura.png)

> O diagrama acima não mostra o CloudWatch — o Grafana também lê métricas e logs direto do CloudWatch (`cloudwatch:GetMetricData`/`GetMetricStatistics`/`ListMetrics`/`Describe*Alarm*` + logs, tudo **somente leitura**, via task role própria dele — ver `infra/terraform/grafana.tf`), além do datasource Postgres já representado. Ver seção Observabilidade abaixo.

## Por que LangGraph

O fluxo de cada atendimento é uma máquina de estados com pausa/retomada: pergunta → espera resposta → decide a próxima pergunta a partir do que já sabe → repete até concluir. LangGraph modela isso nativamente:

- **`interrupt()`** pausa o grafo no meio de um nó e devolve o controle pro chamador (aqui, a resposta HTTP) — sem isso, teríamos que serializar "em que ponto da conversa estamos" manualmente a cada request.
- **Checkpointer** persiste o estado do grafo entre chamadas HTTP (cada POST é uma invocação nova do processo, sem estado em memória entre requests) — ver seção Persistência abaixo.
- **`StateGraph` + `addConditionalEdges`** dá um jeito declarativo de desenhar "depois desta pergunta, vai pra cá ou pra lá dependendo da resposta" — o desenho do grafo em cada `fluxos/*/graph.ts` É a documentação executável do fluxo de negócio.

A alternativa (state machine manual, switch/case por "qual pergunta estamos") funcionaria, mas LangGraph já resolve pausa/retomada + persistência prontos — não reinventar isso foi a troca.

## Por que Fastify

API fina, poucas rotas (`/atendimentos`, `/atendimentos/:chatId`, `/atendimentos/respostas`, `/fluxos`, `/orquestrador`). Fastify dá:

- **Schema-first**: cada rota declara `body`/`response` como JSON Schema — serialização rápida (fast-json-stringify) e, de bônus, gera o OpenAPI (`/docs`) sem manter um YAML solto (ver `@fastify/swagger` em `src/app.ts`).
- **`app.inject()`**: testa a API inteira (rotas + auth + serialização) sem abrir uma porta de verdade — é como os testes `*.http.test.ts` funcionam.

## Estrutura de pastas

```
src/
  app.ts              # monta o Fastify (rotas, auth, swagger) — sem listen()
  server.ts           # importa app.ts e chama listen() — só isso muda entre "testável" e "rodando de verdade"
  fluxos/
    index.ts           # registro: flowId (uuid) -> {grafo, schema de metadados, mensagens}
    pessoaPresa/        # grafo + state + schema HTTP deste fluxo
    violenciaDomestica/ # idem
    padrao/              # grafo genérico (1 nó, conclui na hora) pra categoria sem fluxo próprio ainda
  orquestrador/        # classifica um relato livre pro flowId certo (ver docs/contrato-tykhe.md)
  subgrafos/           # StateGraph reaproveitável, sem flowId próprio — embutido como nó dentro de um fluxo (ver docs/novo-fluxo.md)
  integracoes/
    verde.ts            # toda chamada HTTP pro Verde mora aqui (ver docs/integracao-verde.md)
  ia/                  # chamadas de IA (Bedrock): reescrever pergunta, extrair campos, classificar, sumarizar
  rotas/                # HTTP: atendimentos.ts (core), fluxos.ts, orquestrador.ts
  shared/
    checkpointer.ts     # persistência do LangGraph (Postgres)
    atendimentosDb.ts   # tabela chatId -> flowId (+ colunas de desfecho pra métricas)
    perguntasDb.ts       # árvore de perguntas do Verde por categoria (retrieval do orquestrador)
    fluxosPlanejadosDb.ts # catálogo de categorias sem fluxo implementado ainda
    logger.ts / contexto.ts # pino + correlação de log por fluxoId/chatId fora do request handler
infra/
  terraform/            # toda a infra AWS
  grafana/               # dashboards e alertas versionados (ver seção Observabilidade)
docs/                   # este diretório
```

Cada fluxo é uma pasta autocontida (`graph.ts`, `state.ts`, `api.ts`) — adicionar um fluxo novo não toca nos outros, só registra em `fluxos/index.ts`.

## Persistência

Tudo no **mesmo** Postgres (RDS `maria-chat-prod-pg`, acessado via RDS Proxy compartilhado com o stack antigo), 4 preocupações diferentes:

1. **Checkpoints do LangGraph** (`PostgresSaver`, tabelas próprias que a lib cria) — o estado de cada conversa em andamento, indexado por `thread_id` (= `chatId`). Sem `DATABASE_URL` (testes), cai num `MemorySaver` em memória.
2. **Tabela `atendimentos`** (`chatId -> flowId` + colunas de desfecho) — o checkpointer do LangGraph indexa só por `thread_id`, sem separar por fluxo; sem essa tabela, o mesmo `chatId` usado em 2 fluxos diferentes colidiria no mesmo checkpoint. Também guarda `status_final`/`motivo_handoff`/`tokens_*` pra consulta SQL direta (Grafana), sem depender só de CloudWatch Logs. Desde a issue #166, guarda também `atualizado_em`/`aguardando_confirmacao_ttl`/`resposta_pendente_ttl` — controle de TTL de inatividade, já que o checkpointer do LangGraph em si não tem TTL nativo (isso é feature só do LangGraph Platform gerenciado, não do OSS self-hosted que usamos).
3. **`perguntas`/`assuntos_verde`/`flow_assuntos`** — árvore de perguntas do catálogo do Verde, coletada uma vez (`scripts/coletarArvorePerguntasVerde.ts`), usada pelo orquestrador pra desambiguação e retrieval.
4. **`fluxo_embeddings`** (extensão `vector`/pgvector, `src/shared/embeddingsFluxos.ts`) — embedding da descrição de cada fluxo do catálogo, usado pelo orquestrador pra busca por similaridade (`embedding <=> $1::vector`) na hora de decidir qual fluxo melhor casa com o relato livre do usuário.

Todas as tabelas são criadas via `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD COLUMN IF NOT EXISTS` no código (sem ferramenta de migração formal — repo pequeno, não justificou ainda). Desde a issue #114, essa criação roda no **startup do processo** (bloqueia o health check até terminar), não mais na primeira request de negócio — evita o deploy ficar "saudável" antes do schema estar pronto de verdade.

## Autenticação

Bearer token fixo (`API_KEY`), um valor só por ambiente, guardado em Secrets Manager. A Tykhe é o único consumidor esperado (chamada servidor-a-servidor) — sem OAuth/JWT por usuário porque não tem usuário final autenticando, é a Tykhe autenticando como aplicação. `/health` fica fora da autenticação (o ALB não manda Bearer).

## Observabilidade

- **Logs estruturados** (pino, JSON) — todo log de negócio carrega `chatId`/`fluxoId` pra correlacionar uma conversa inteira entre requests diferentes (`reqId` sozinho só correlaciona 1 request). `evento` é um campo fixo (`atendimento_criado`, `pergunta_enviada`, `atendimento_finalizado`, `verde_chamada`...) — filtra por isso, não pelo texto livre da mensagem.
- **CloudWatch Logs Insights** — consulta os logs acima. Dashboard versionado em `infra/grafana/dashboards/observabilidade.json`.
- **Datasource CloudWatch no Grafana** — o Grafana chama a API do CloudWatch direto (métricas e logs), com task role própria de **somente leitura** (`cloudwatch:GetMetricData`/`GetMetricStatistics`/`ListMetrics`/`Describe*Alarm*` + logs, ver `infra/terraform/grafana.tf`) — não fica limitado ao Logs Insights manual, os dashboards já plotam isso direto.
- **Datasource Postgres no Grafana** — consulta direto a tabela `atendimentos` via SQL (joins/agregações que CloudWatch não faz bem), usuário **somente leitura** dedicado (`grafana_readonly`).
- **Alertas** (`infra/grafana/alerts/saude-operacional.json`) — host saudável, taxa de erro 5xx, CPU alta, latência alta, por ambiente (prod/release). Toda regra **precisa ter `uid`** — `publish-grafana.yml` faz PUT (atualiza) por `uid`, mas cria uma regra NOVA via POST pra qualquer entrada sem `uid`; já causou duplicação real (issue #163) por um erro de edição que deixou uma cópia velha sem `uid` no arquivo. Latência usa janela de 15min (não 5min) de propósito — tráfego baixo dá poucas amostras por avaliação, e p99 com poucas amostras é ruidoso (1 request lenta isolada já estoura o p99 de uma janela pequena).
- **Publish automatizado** (`.github/workflows/publish-grafana.yml`) — dashboards/alertas versionados no repo são aplicados no Grafana automaticamente a cada push que toque `infra/grafana/**`. Sem isso, o que está no repo e o que está publicado divergem silenciosamente (já aconteceu 2x numa mesma sessão de trabalho).
- **Detecção de drift de Terraform** (`.github/workflows/terraform-drift.yml`) — roda `terraform plan` e falha se tiver mudança pendente, separado dos workflows de deploy de propósito (drift de infra não deve travar um fix de bug simples de subir).

## Infra (AWS)

- **ECS Fargate** (sem servidor pra gerenciar) atrás de um **ALB** único, com **CloudFront** na frente só pra ter HTTPS sem precisar de domínio próprio (certificado `*.cloudfront.net` grátis/automático — decisão documentada em `infra/terraform/cloudfront.tf`).
- **2 ambientes, mesmo padrão**: `prod` (deploy em push pra `main`) e `release`/homolog (deploy em push pra `develop`) — serviços ECS separados, mesmo cluster/ALB, roteados por header (`X-Maria-App`) que o CloudFront injeta. Permite testar em release com dado real do Verde (homolog) antes de ir pra prod.
- **VPC/subnets/RDS compartilhados** com um stack Terraform antigo (`data.terraform_remote_state.old`) — não duplica rede nem banco, só lê os IDs de lá. Esse repo nunca escreve no state antigo.
- **RDS Proxy compartilhado** — o app e o Grafana se conectam ao Postgres através do mesmo proxy que o stack antigo já usa; cada security group novo (task da app, task do Grafana) ganha uma regra de ingress própria no SG do proxy, sem o stack antigo precisar saber desse repo na hora de escrever o `.tf` dele.
- **Deploy via GitHub Actions com OIDC** (sem chave AWS fixa guardada como secret) — token de curta duração emitido pelo GitHub a cada run, `assume-role` restrito pelo `sub` do token a só `main`/`develop`.
- **Tag semver + GitHub Release automáticos** (issue #145) — todo deploy que chega em `main` com sucesso ganha uma tag `vX.Y.Z` (job `tag` em `deploy-prod.yml`): bump calculado a partir dos tipos de commit desde a última tag (`feat` → minor, `BREAKING CHANGE` no corpo → major, qualquer outro caso → patch), Release criada com changelog gerado automaticamente (`gh release create --generate-notes`).
- **Secrets fora do Terraform** — todo valor real (token do Verde, senha do Postgres, API_KEY) é preenchido manualmente via `aws secretsmanager put-secret-value` depois do `apply` (o `.tf` só cria o secret vazio, com placeholder `"PREENCHER"`) — decisão deliberada pra nunca ter segredo real em texto plano no state/código.
- **Interface VPC Endpoint pro Bedrock** (`infra/terraform/bedrock-endpoint.tf`, issue #141) — tráfego das tasks pro Bedrock fica 100% dentro da VPC, sem passar pelo NAT Gateway/rota pública. Custo fixo (~US$14,60/mês, 2 AZs) supera a economia esperada no NAT pro volume de tráfego atual — decisão de arquitetura autorizada mesmo assim, não motivada por custo.

## O que NÃO tem (de propósito, por enquanto)

- **Migração de schema formal** — DDL idempotente no código, sem Flyway/Drizzle Kit (ver issue #114 e a seção Persistência acima).
- **Autoscaling** — 1 task fixa por ambiente, tráfego baixo não justifica ainda.
- **Domínio próprio** — `*.cloudfront.net` resolve HTTPS sem precisar de Route53/ACM.
- **Testes de contrato automatizados contra o Verde real** — `test-integracao/` existe mas cobre pouco; a maior parte da validação contra a API real do Verde é feita manualmente (ver `docs/integracao-verde.md`), o que já causou mais de um bug descoberto tarde (ver esse mesmo doc).
