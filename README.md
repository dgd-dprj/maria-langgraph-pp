# Maria

Ponte entre a **Tykhe** (chatbot) e o **Verde** (sistema da Defensoria Pública do RJ), construída com [LangGraph](https://langchain-ai.github.io/langgraphjs/) — cada fluxo de atendimento é um grafo de estados com pausa/retomada nativa.

Vai contribuir? Ver [`CONTRIBUTING.md`](CONTRIBUTING.md) (fluxo de issue/branch/commit/PR).

## Documentação

- [`docs/arquitetura.md`](docs/arquitetura.md) — visão geral, decisões de infra (e o porquê de cada uma), persistência, observabilidade.
- [`docs/fluxo-pessoa-presa.md`](docs/fluxo-pessoa-presa.md) — regras de negócio do fluxo pessoa presa.
- [`docs/fluxo-violencia-domestica.md`](docs/fluxo-violencia-domestica.md) — regras de negócio do fluxo violência doméstica.
- [`docs/fluxo-orquestrador.md`](docs/fluxo-orquestrador.md) — como a classificação automática (relato livre → flowId) funciona.
- [`docs/integracao-verde.md`](docs/integracao-verde.md) — cada endpoint do Verde usado, shape real de resposta, bugs já encontrados ao vivo.
- [`docs/ia.md`](docs/ia.md) — cada módulo de IA (Bedrock): o que faz, padrão comum de retry/fallback/mock, flags de ambiente.
- [`docs/contrato-tykhe.md`](docs/contrato-tykhe.md) — o que a API expõe pra Tykhe, schema da resposta.
- [`docs/testes.md`](docs/testes.md) — como os testes são organizados e rodados, modo mock, o que roda no CI.
- [`scripts/README.md`](scripts/README.md) — o que cada script em `scripts/` faz e quando rodar (não é doc da aplicação em si, fica junto do tooling).
- [`docs/novo-fluxo.md`](docs/novo-fluxo.md) — guia passo a passo pra implementar um fluxo novo.
- [`docs/padroes-issues.md`](docs/padroes-issues.md), [`docs/padroes-branch.md`](docs/padroes-branch.md), [`docs/padroes-commits.md`](docs/padroes-commits.md), [`docs/padroes-pull-request.md`](docs/padroes-pull-request.md) — convenções de contribuição (ver [`CONTRIBUTING.md`](CONTRIBUTING.md)).
- [`docs/harness.md`](docs/harness.md) — agents/skills/hooks/commands do Claude Code neste repo.

## Rodando local

```bash
pnpm install
echo "API_KEY=dev-local" > .env   # sem VERDE_JWT_TOKEN/DATABASE_URL, cai em modo mock (memória, sem Postgres/Verde real)
pnpm dev
```

Variáveis principais (todas opcionais em dev — ausentes = modo mock): `VERDE_API_URL`, `VERDE_JWT_TOKEN`, `VERDE_CLIENT_ID`, `DATABASE_URL`, `API_KEY` (obrigatória, sem default). `EXTRACAO_LIVRE_IA=true` liga a extração por IA opcional no fluxo pessoa presa (desligada por padrão). `TTL_INATIVIDADE_HORAS` (default `24`) — horas de inatividade antes de perguntar se a pessoa quer continuar o atendimento (issue #166).

`GET /docs` — Swagger UI com o contrato HTTP completo. `pnpm test` — testes (não precisa de `.env`, roda em modo mock/memória; detalhes em [`docs/testes.md`](docs/testes.md)).

## Estrutura

```
src/fluxos/<nome>/       # 1 fluxo = 1 grafo LangGraph (graph.ts + state.ts + api.ts)
src/integracoes/verde.ts # toda chamada HTTP pro Verde
src/rotas/               # HTTP (Fastify)
src/shared/              # persistência, logger, checkpointer
infra/terraform/         # infra AWS
infra/grafana/           # dashboards/alertas versionados
```

Detalhes em [`docs/arquitetura.md`](docs/arquitetura.md).
