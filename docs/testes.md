# Testes

## Runner

Sem Jest/Vitest — `node --test` nativo (`--import tsx` pra rodar `.ts` direto, sem build prévio). Motivo: repo pequeno, runner nativo já resolve `describe`/`test`/`assert` sem dependência extra.

```bash
pnpm test              # test/**/*.test.ts + src/**/*.test.ts — modo mock, sem .env
pnpm test:integracao   # test-integracao/*.test.ts — chama IA real (Bedrock)
```

## Camadas

| Camada | Onde | O que cobre |
|---|---|---|
| Unidade do grafo | `src/fluxos/*/graph.test.ts` | Lógica de decisão do `StateGraph` isolada — invoca o grafo direto, sem HTTP. |
| HTTP por fluxo | `src/fluxos/*/http.test.ts` | Conteúdo/texto de pergunta de cada fluxo específico via `app.inject()`. |
| HTTP genérico | `test/app.test.ts` | Mecânica das rotas (auth, health, idempotência, status code, HATEOAS) — sem acoplar em texto de negócio de nenhum fluxo. Usa violência doméstica só como fixture (é o fluxo mais rápido de concluir). |
| Contrato Tykhe | `test/contratoTykhe.test.ts` | Shape da resposta HTTP que a Tykhe consome (ver `docs/contrato-tykhe.md`). |
| TTL de inatividade | `test/ttlInatividade.test.ts` | Confirmação de continuidade e expiração após `TTL_INATIVIDADE_HORAS` (issue #166) — usa `TTL_INATIVIDADE_HORAS=0` pra forçar expiração determinística, sem mockar `Date`. |
| Orquestrador | `test/orquestrador.test.ts`, `src/orquestrador/graph.test.ts` | Classificação/desambiguação de relato livre. |
| Auxiliares | `src/shared/*.test.ts` | `embeddingsFluxos`, `perguntasDb`, `tokensAcumulados` isolados. |
| Integração real com IA | `test-integracao/*.test.ts` | Chama Bedrock de verdade (classificar, desambiguar, extrair, parentesco, reescrever, sumarizar) — não roda no `pnpm test` normal nem no CI padrão, só sob demanda (custa tempo/dinheiro real). |

## Modo mock — por que os testes não tocam infra real

`pnpm test` roda com `API_KEY=teste-fixo-chave` fixo e **sem** `VERDE_JWT_TOKEN`/`DATABASE_URL` — isso já é o gatilho pro modo mock (ver `docs/integracao-verde.md`): `src/integracoes/verde.ts` cai nos mocks locais, `checkpointer.ts` cai no `MemorySaver` em memória (sem Postgres). Resultado: suite roda em qualquer máquina, sem AWS, sem segredo, sem rede — só `test-integracao/` sai desse modo de propósito.

## O que NÃO existe ainda

- **Teste de contrato automatizado contra o Verde real** — a validação contra a API real do Verde (shape de resposta, bugs de doc) é manual (ver checklist em `docs/integracao-verde.md`); já causou bug descoberto tarde (issue #108).
- **Coverage report** — sem `--coverage`/threshold configurado; nenhuma decisão tomada ainda sobre exigir um número mínimo.

## CI

`pnpm test` roda em todo push/PR (`.github/workflows/ci.yml`) e de novo como gate antes de deploy (`deploy-release.yml`/`deploy-prod.yml`) — falha em qualquer um dos três bloqueia merge/deploy.
