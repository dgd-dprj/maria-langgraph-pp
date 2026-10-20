# SDD — Módulo `documentacao`

Parte de #208. Issue: #258. Branch: `refactor/258-documentacao-python`, a partir de `migration` @ `437dee0` (depois do scripts). **Fonte de conteúdo: develop @ `1157a6d`**, para o que a documentação diz sobre comportamento; **a `migration`**, para o que ela diz sobre código, caminhos, comandos e ferramentas.

**Regra desta spec** (a mesma das specs 07 e 08): **(lido)** é afirmação tirada da leitura; **(executado)** já rodou.

**O objetivo, pela #208:** "Documentação atualizada para descrever o repositório como ele passa a ser." **Não é trocar palavras** (`pnpm` → `uv`, `.ts` → `.py`): cada documento é relido contra o que a `migration` faz hoje e reescrito onde a descrição deixou de valer. O guia [`docs/rodar-localmente.md`](../../rodar-localmente.md), escrito no módulo api e testado numa pasta limpa, é a base do "como rodar".

| Origem | Destino |
|---|---|
| `README.md` (36 linhas na `migration`; ainda descreve a versão TypeScript como principal) | reescrito para o repositório em Python (seção 3.1) |
| `CLAUDE.md`, `CONTRIBUTING.md` | comandos e caminhos da versão Python; as regras de develop (#229) trazidas |
| 13 arquivos em `docs/` | relidos um a um (seção 3.2) |
| `.claude/agents/code-reviewer.md`, `.claude/agents/diagram-specialist.md`, `.claude/skills/*`, `docs/harness.md` | o harness do Claude Code descrito como ele é hoje |
| `.github/ISSUE_TEMPLATE/bug.yml` | trazido de develop (#229) |
| `scripts/README.md` | já reescrito no módulo scripts; só conferido |
| `MIGRACAO.md`, `docs/migracao/` | **ficam como registro** da migração; o README aponta para eles |

**Fora deste módulo:**
- os comentários no código (ver a regra de referências históricas, seção 2);
- o merge em `develop`, os painéis do Grafana e a execução do plano de corte (módulo corte);
- regenerar os diagramas PNG no S3 (decisão D-4).

---

## 0. O que já existe

| Peça | Onde | Situação |
|---|---|---|
| Guia para rodar localmente, testado numa pasta limpa (PowerShell e Git Bash, modo A e modo B) | `docs/rodar-localmente.md` (módulo api, #246) | Pronto; é a base do "como rodar" |
| README de `scripts/` | módulo scripts (#252) | Pronto |
| Registro da migração e specs 01 a 08 | `MIGRACAO.md`, `docs/migracao/` | Pronto; fica como registro |
| Índice de issues | `docs/migracao/INDICE-ISSUES.md` | **Desatualizado na `migration`** desde o merge do #257: a cópia do repositório anda na branch do módulo seguinte, que é esta |
| Hook de typecheck do Claude Code roda o `mypy` em `.py` | `.claude/hooks/typecheck-after-edit.mjs` (fundação) | Pronto. A fundação decidiu que **os hooks continuam em Node**: são do Claude Code, e não da aplicação |

## 1. Contexto: o que está desatualizado (executado em 2026-10-20)

Inventário dos documentos nos dois lados (`git ls-tree` em develop @ `1157a6d` e na `migration` @ `437dee0`), com as referências ao mundo TypeScript que o texto da `migration` ainda tem (`pnpm`/`npm`/`npx`, `tsx`/`node`, caminhos `.ts`, `Fastify`, `NODE_ENV`, `package.json`, caminhos `src/` de develop):

| Arquivo | Igual a develop? | Referências TypeScript na `migration` |
|---|---|---|
| `README.md` | não (a fundação acrescentou o guia Python) | 3 pnpm, 4 `.ts`, 1 Fastify, 4 `src/` |
| `CLAUDE.md` | não (develop mudou: #229) | 1 pnpm |
| `CONTRIBUTING.md` | sim | 2 pnpm |
| `docs/arquitetura.md` | sim | **23 `.ts`**, 3 Fastify |
| `docs/novo-fluxo.md` | sim | **20 `.ts`**, 11 `src/` |
| `docs/testes.md` | não (develop mudou: #226) | 5 pnpm, 2 node, 14 `.ts` |
| `docs/ia.md` | sim | 8 `.ts`, 1 `NODE_ENV` |
| `docs/integracao-verde.md` | sim | 7 `.ts` |
| `docs/bridge-whatsapp.md` | sim | 6 `.ts` |
| `docs/contrato-tykhe.md` | não (develop mudou: #242 e #234) | 4 `.ts` |
| `docs/fluxo-orquestrador.md` | não (develop mudou: #242) | 3 `.ts` |
| `docs/fluxo-pessoa-presa.md`, `docs/fluxo-violencia-domestica.md` | sim | 2 e 1 `.ts` |
| `docs/harness.md` | sim | 2 pnpm, 2 `.ts`; descreve o hook de typecheck como `pnpm typecheck` em `.ts` |
| `docs/padroes-issues.md`, `docs/padroes-pull-request.md` | não (develop mudou: #229) | — |
| `docs/padroes-branch.md`, `docs/padroes-commits.md` | sim | — |
| `.claude/agents/code-reviewer.md` | sim | 2 pnpm, 2 `.ts` |
| `.claude/agents/diagram-specialist.md`, `.claude/skills/padroes-issues/SKILL.md`, `.claude/skills/padroes-pull-request/SKILL.md` | não (develop mudou: #229) | 2 npm/npx no agente |
| `.github/ISSUE_TEMPLATE/bug.yml` | **só existe em develop** (#229) | — |

### 1.1 Documentação que develop mudou depois que a `migration` nasceu

A `migration` saiu de develop em `4e695f2` (2026-10-02). Depois disso, quatro commits de develop mudaram documentação, e **nenhum chegou à `migration`** (executado, `git log 4e695f2..1157a6d`):

| Commit | Issue/PR | Arquivos de documentação |
|---|---|---|
| `665714c` | #229 (padrão de evidência em issues, diagramas Mermaid inline, formulário de bug) | `CLAUDE.md`, `docs/padroes-issues.md`, `docs/padroes-pull-request.md`, `.claude/agents/diagram-specialist.md`, `.claude/skills/padroes-issues/SKILL.md`, `.claude/skills/padroes-pull-request/SKILL.md`, `.github/ISSUE_TEMPLATE/bug.yml` |
| `c59d43c` | #242 (catálogo de 9 opções, `redirecionado`/`tipoCaso`) | `docs/contrato-tykhe.md`, `docs/fluxo-orquestrador.md` |
| `8a97be0` | #234 (confirmação de TTL tolerante) | `docs/contrato-tykhe.md` |
| `cb11a5e` | #226 (resposta preservada no TTL) | `docs/testes.md` |

O código desses PRs já está na `migration` (o #242, o #234 e o #226 foram traduzidos nos módulos fluxos, orquestrador e api). **Só a documentação ficou para trás.** O #229 é só documentação, com destino declarado neste módulo (`MIGRACAO.md`, seção do fluxos).

### 1.2 Diagramas publicados no S3 (executado: os 7 PNGs baixados e conferidos)

| Diagrama | Usado em | Situação |
|---|---|---|
| `arquitetura.png` | `docs/arquitetura.md` | **Certo:** infraestrutura (ECS, ALB, CloudFront, RDS), sem depender da linguagem |
| `orquestrador.png` | `docs/fluxo-orquestrador.md` | **Errado desde o #242, em develop também:** desenha "0 candidatos → HANDOFF `nao_identificado`"; hoje é `redirecionado`/`outros`, e o catálogo inclui os tipos da Tykhe |
| `padrao-comum-ia.png` | `docs/ia.md` | **Errado para a versão Python:** "`NODE_ENV=test`" e "saída estruturada (Zod)" |
| `contrato-tykhe.png`, `pessoa-presa.png`, `violencia-domestica.png`, `mapa-modulos-ia.png` | os docs dos fluxos, do contrato e da IA | a conferir item a item na tradução (o do contrato é anterior ao #242) |

### 1.3 Variáveis de ambiente: o código contra a documentação (executado)

O código Python lê **25 variáveis** (`os.environ` em `src/maria/`). O guia `docs/rodar-localmente.md` documenta 14. **Faltam 11:** `EXTRACAO_LIVRE_IA`, `REESCREVER_IA`, as quatro `WHATSAPP_*`, e seis `MOCK_*` de teste (`MOCK_CADASTRO_FALHA`, `MOCK_CEP_INCOMPLETO`, `MOCK_CLASSIFICACAO_PARENTESCO`, `MOCK_ENCAMINHAMENTO_FALHA`, `MOCK_PLANTAO_VIGENTE`, `MOCK_SUMARIZACAO_RESUMO`). A #208 pede o `APP_ENV` no README "com os três valores e o efeito de cada um", mas **o código só distingue `test` do resto** (achado C4).

## 2. Regra das referências históricas

**Fica como está, mesmo citando arquivo que não existe mais:**
- **decisões datadas** (por exemplo, "Decisão 2026-09-04: reaproveita cluster/IAM…");
- **registros de incidente** e achados ao vivo (por exemplo, os "bugs já encontrados ao vivo" de `docs/integracao-verde.md`, ou "achado ao vivo 2026-09-11");
- **números de issue** e **comentários no código**, inclusive os que citam `verde.ts`, `graph.ts:192` ou `app.ts:87`: a tradução os manteve de propósito, como rastro de onde cada comportamento veio;
- `MIGRACAO.md` e `docs/migracao/`, inteiros.

**Muda:**
- **instruções** (como rodar, como testar, como criar um fluxo);
- **caminhos e comandos** que alguém vai seguir hoje;
- **descrições do comportamento atual** que deixaram de valer (por exemplo, `nao_identificado` depois do #242);
- **a lista de variáveis de ambiente.**

**Quando um trecho histórico cita um caminho TypeScript sem dizer que é histórico**, o trecho não é reescrito: ganha uma nota curta no início da seção ("Registro de 2026-09: os caminhos citados são da versão TypeScript"). Decisão D-2.

## 3. O que muda, documento a documento

### 3.1 `README.md`

Reescrito para o repositório como ele passa a ser, e não com palavras trocadas:
- **o que é** a Maria (Tykhe ↔ Verde ↔ LangGraph), com o link do LangGraph trocado da versão JS para a Python;
- **como rodar:** resumo curto e o link para `docs/rodar-localmente.md`, que é a referência (modo A, modo B, problemas comuns). **Sai** o bloco "Versão TypeScript (develop)";
- **variáveis de ambiente:** a tabela completa (seção 1.3), com o `APP_ENV` como ele é: **o código só distingue `test`** (IA e embeddings simulados, `chatId` opcional); qualquer outro valor, inclusive `development` e ausente, se comporta como produção (achado C4);
- **estrutura** de `src/maria/` (`api/`, `fluxos/`, `subgrafos/`, `orquestrador/`, `ia/`, `integracoes/`, `shared/`), `tests/`, `scripts/`, `infra/`;
- **como testar:** `uv run pytest` e os marcadores `postgres` e `integracao`;
- **ferramentas fora do Python:** Node é preciso só para os hooks do Claude Code, para o `scripts/logs-prod.sh` (`pino-pretty`) e para gerar diagramas (`mermaid-cli`);
- **a migração:** um parágrafo e o link para `MIGRACAO.md` e `docs/migracao/`.

### 3.2 `docs/`

| Documento | O que muda |
|---|---|
| `arquitetura.md` | o stack (FastAPI com o pipeline que reproduz o Fastify, LangGraph Python, psycopg, uv); os caminhos atuais; o `scripts/coletarArvorePerguntasVerde.ts` (`:67`) vira o `.py`. As decisões datadas ficam |
| `novo-fluxo.md` | **reescrito**: o passo a passo de um fluxo novo em Python (`src/maria/fluxos/<nome>/`, a fábrica de grafo, o registro em `fluxos_por_id`, os testes). Verificado seguindo o guia (seção 6) |
| `testes.md` | `pytest`, os marcadores, as duas etapas do CI (suíte padrão e `postgres`), o modo mock por `APP_ENV=test`, as fixtures de contrato; o #226 de develop |
| `ia.md` | `APP_ENV` no lugar de `NODE_ENV`; os caminhos `src/maria/ia/`; o retry em duas camadas (#222) |
| `integracao-verde.md` | os caminhos e o cliente HTTP (`cliente_http.py`, `verde.py`); os prazos (30 s total, 10 s de conexão; seção "Prazos" do `MIGRACAO.md`). Os bugs encontrados ao vivo ficam |
| `bridge-whatsapp.md` | os caminhos; a chamada interna em processo no lugar do `app.inject` |
| `contrato-tykhe.md` | o #242 e o #234 de develop; os campos que distinguem os desfechos (`status`, `flowId`, `_links.responder`), conferidos com respostas reais no teste com a Tykhe (2026-10-19) |
| `fluxo-orquestrador.md` | o #242 de develop; o catálogo de 9 opções; a busca vetorial inativa (#256) |
| `fluxo-pessoa-presa.md`, `fluxo-violencia-domestica.md` | só os caminhos (as regras de negócio não mudaram) |
| `harness.md` | o hook de typecheck roda o `mypy` em `.py`; `src/maria/ia/CLAUDE.md`; os hooks continuam em Node |
| `padroes-issues.md`, `padroes-pull-request.md` | o #229 de develop |
| `padroes-branch.md`, `padroes-commits.md` | conferidos; sem mudança prevista |

### 3.3 Harness e contribuição

- `CLAUDE.md` (raiz): o #229; os comandos de verificação (`uv run ruff check`, `uv run mypy`, `uv run pytest`).
- `CONTRIBUTING.md`: os comandos.
- `.claude/agents/code-reviewer.md`: o checklist com `ruff`, `mypy` e `pytest`, e os caminhos `.py`.
- `.claude/agents/diagram-specialist.md` e as skills: o #229 de develop.
- `.github/ISSUE_TEMPLATE/bug.yml`: trazido de develop.

## 4. O que não muda

- As regras de negócio dos fluxos.
- O contrato com a Tykhe (só a descrição, que passa a incluir o #242 e o #234, como develop).
- Os padrões de branch e de commit.
- As referências históricas (seção 2).
- `MIGRACAO.md` e `docs/migracao/`.

## 5. Observabilidade

Sem mudança: a documentação não muda o log. A seção de observabilidade de `docs/arquitetura.md` é conferida contra o envelope pino e os campos reproduzidos.

## 6. Verificação

A documentação também passa por verificação executada:
1. **Links e caminhos:** um teste (`tests/test_documentacao.py`) confere que todo link relativo de `README.md`, `CLAUDE.md`, `CONTRIBUTING.md` e `docs/*.md` (fora de `docs/migracao/`) aponta para um arquivo que existe, e que todo caminho citado em código com `src/maria/`, `tests/` ou `scripts/` existe. Caminhos `.ts` são aceitos só nos trechos marcados como históricos (D-2).
2. **Variáveis de ambiente:** um teste confere que o conjunto de variáveis lidas em `src/maria/` é igual ao conjunto documentado na tabela do README. Uma variável nova sem documentação quebra o teste.
3. **Comandos executados numa pasta limpa:** os comandos do README e do `docs/testes.md`, como foi feito com o `docs/rodar-localmente.md` no módulo api.
4. **O guia de fluxo novo, seguido de verdade:** numa branch descartável, criar um fluxo de brinquedo só com o `docs/novo-fluxo.md` e chegar aos testes passando. Um passo que faltar ou estiver errado no guia aparece aí.
5. **O #229, o #242, o #234 e o #226 trazidos:** o diff contra develop @ `1157a6d` dos arquivos que não precisam de adaptação (`padroes-*.md`, as skills, o `bug.yml`) fica vazio.

## 7. Critérios de aceite

- [ ] Os quatro commits de documentação de develop (seção 1.1) trazidos, em commit próprio, antes da reescrita (D-1).
- [ ] `README.md` reescrito (seção 3.1), com a tabela completa de variáveis e o `APP_ENV`.
- [ ] Cada documento da seção 3.2 relido e atualizado; as referências históricas preservadas (seção 2).
- [ ] O harness (seção 3.3) atualizado; o `bug.yml` trazido.
- [ ] Os testes da seção 6 (links e caminhos, variáveis) passando.
- [ ] Os comandos executados numa pasta limpa, e o guia de fluxo novo seguido de verdade (seção 6), com o resultado no PR.
- [ ] Os diagramas tratados conforme a D-4.
- [ ] `docs/migracao/INDICE-ISSUES.md` atualizado; `MIGRACAO.md` com a seção do módulo; a #208 atualizada.
- [ ] `ruff`, `ruff format --check`, `mypy` strict e `pytest` verdes; os jobs `test` e `imagem` verdes.

## 8. Decisões (aprovadas em 2026-10-20)

| Decisão | Proposta | O que mudaria |
|---|---|---|
| **D-1** Trazer a documentação de develop primeiro | Os quatro commits da seção 1.1, aplicados sobre a `migration` num commit próprio, antes de qualquer reescrita. A reescrita parte do texto mais novo de develop, e o diff da tradução fica limpo | Trazer junto com a reescrita misturaria "o que develop mudou" com "o que a migração mudou" |
| **D-2** Referências históricas | A regra da seção 2. Trecho histórico sem marca ganha uma nota curta no início da seção, sem reescrever o trecho | Reescrever os trechos históricos apagaria o rastro de onde cada decisão veio |
| **D-3** `MIGRACAO.md` e `docs/migracao/` depois da migração | Ficam no repositório como registro, com link no README. Nada é apagado | Mover para fora do repositório perderia a ligação entre o código e as decisões |
| **D-4** Diagramas no S3 | Escrevo o Mermaid novo de cada diagrama que mudou (`orquestrador`, `padrao-comum-ia` e os que a conferência da seção 1.2 apontar), com o guia de estilo do `diagram-specialist`. **Gerar o PNG e gravar no bucket é escrita na AWS:** fica com quem tem a credencial, ou com uma autorização explícita sua. Até lá, o `docs/*.md` mostra o bloco Mermaid no lugar do PNG desatualizado, que é o caminho do #229 para issues e PRs | Manter o PNG antigo deixaria a documentação descrevendo um comportamento que não existe desde o #242 |
| **D-5** Node como ferramenta de apoio | Documentar que o Node continua necessário para os hooks do Claude Code, o `logs-prod.sh` e o `mermaid-cli`, e para nada da aplicação | Portar os hooks para Python tiraria a dependência, mas é mudança de ferramenta, fora da régua |

## 9. Achados

| Id | Achado | Origem | Proposta |
|---|---|---|---|
| **C1** | O diagrama `orquestrador.png` está errado **em develop também**, desde o #242: desenha o `nao_identificado` como handoff, que é justamente o comportamento que o #242 trocou por `redirecionado`. **O alcance vai além da documentação:** é o diagrama que quem lê o fluxo de produção consulta, e ele induz um entendimento errado do fluxo atual. É a mesma mudança que a #249 discute, vista de outro ângulo | executado (PNG baixado e conferido) | Corrigir aqui (D-4); avisar na #249 e na #225, onde nasceu o #242 |
| **C2** | Faltam 11 variáveis de ambiente na documentação, entre elas as quatro `WHATSAPP_*` e as duas flags de IA | executado (o conjunto do código contra o do guia) | O teste da seção 6 impede que volte a acontecer |
| **C3** | O índice de issues do repositório fica desatualizado entre o merge de um módulo e a branch do seguinte | lido (a regra da cópia na branch de trabalho) | Registrar no `MIGRACAO.md`, na seção do índice, que a cópia do repositório anda na branch do módulo seguinte |
| **C4** | **O `APP_ENV` tem dois comportamentos, e não três.** As 15 leituras em `src/maria/` comparam só com `"test"`; `development` e ausente fazem o mesmo. O critério da #208 pede "os três valores e o efeito de cada um", e o `docs/rodar-localmente.md` diz que `development` liga a "IA real", o que também vale para ausente. Develop é igual: as 10 comparações de `NODE_ENV` em `src/` são com `"test"`, e um comentário de develop diz "obrigatório (produção E desenvolvimento); só NODE_ENV=test relaxa". A tradução reproduziu certo; só a documentação promete três | executado nos dois lados | **Decidido em 2026-10-20:** documentar os dois comportamentos que existem e corrigir o critério da #208. Documentar comportamento que não existe é pior que não documentar. Se `development` deve ter efeito próprio, é mudança de comportamento, fora da régua |

| **C5** | O `docs/arquitetura.md` (igual em develop) diz que o release é roteado pelo header `X-Maria-App`. Pelo Terraform, o CloudFront do release injeta `X-Maria-Env: release` (`release.tf`); `X-Maria-App` é o header do Grafana (`grafana.tf`) | lido (Terraform) | Corrigido no doc |
| **C6** | O mesmo doc diz que o release usa "dado real do Verde (homolog)". Os comentários do `release.tf` dizem o contrário: o release foi criado para testar com o Verde de **produção** ("quando a credencial chegar"), e o `prod` aponta para a homologação. Os valores reais estão nos segredos e não foram lidos | lido (Terraform) | Doc segue o Terraform, sem citar URL. Conferir os segredos de cada ambiente é leitura na AWS, a fazer no corte |
| **C7** | **Registrar um fluxo novo quebra 12 testes**, e 6 deles conferem `GET /fluxos` contra respostas gravadas da versão TypeScript (`tests/fixtures/contrato/`). Depois do corte não há versão TypeScript para regravar: toda evolução do contrato exige editar a fixture à mão | executado (guia seguido, seção 10) | O guia diz quais são. **Decisão em aberto:** como as fixtures gravadas evoluem depois do corte |
| **C8** | O README tinha só a forma bash do `.env` (`printf`) e a verificação com `&&`; nenhum dos dois existe no Windows PowerShell 5.1 | executado | Forma PowerShell e nota acrescentadas |
| **C9** | Os 2 testes do `publish-grafana` falham, em vez de serem pulados, quando o `bash` do PATH é o do WSL sem distribuição funcionando | executado | Registrado no `docs/testes.md`; é do ambiente |
| **C10** | O `pessoa-presa.png` não desenha os subgrafos do #183 quando o atendimento vem pelo orquestrador. Vale para develop também | executado (PNG conferido) | Registrado; o PNG fica até ser regerado (D-4) |

## 10. Resultado da execução dos guias (2026-10-20)

Num clone limpo da branch (`a015172`), no Windows 11 com PowerShell 5.1:

| Guia | O que foi executado | Resultado |
|---|---|---|
| README, "Rodando local" | `uv sync` (4 s); o `.env` mínimo; o servidor; `/health`, `GET /fluxos`, `POST /atendimentos`, `POST /atendimentos/orquestrador`, `/docs` | Tudo 200. O `printf` não existe no PowerShell (C8). Com o `.env` mínimo, o orquestrador devolve `redirecionado`/`outros`, como a tabela diz |
| README e `docs/testes.md`, verificação | ruff, format, mypy, a suíte padrão | Verde, menos os 2 testes do C9 (falham também sem a mudança). O `&&` não existe no PowerShell 5.1 (C8) |
| `docs/testes.md`, Postgres | o `docker run` do guia e `pytest -m postgres` | 25 passaram |
| `docs/testes.md`, integração | não executado | chama o Bedrock com custo real |
| `docs/novo-fluxo.md` | um fluxo de exemplo (1 pergunta sim/não), só com o guia e os arquivos que ele aponta: pasta, registro, `langgraph.json`, teste do grafo, teste HTTP, doc com link no README | Os testes do fluxo passaram (3 do grafo, 1 HTTP) e o teste de documentação cobriu o doc novo. **A suíte inteira quebrou em 12 testes que fixam o catálogo (C7)**, e o guia não avisava. Faltava também o `resposta_eh_sim`. Ambos corrigidos no guia. O diagrama não foi gerado: gravar no S3 é escrita na AWS |

## Dependências

- `migration` @ `437dee0`: todos os módulos de código.
- develop @ `1157a6d`, com os quatro commits de documentação da seção 1.1.
- Issues afetadas: #208 (critérios de documentação e `APP_ENV`), #229, #225/#242, #227/#234, #217/#226, #256.
