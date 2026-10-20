# Testes

## Runner

`pytest`, com `pytest-asyncio` (`asyncio_mode = "auto"`: teste `async def` roda sem decorador). Configuração em `pyproject.toml`.

```bash
uv run pytest                          # suíte padrão: modo mock, sem banco, sem rede, sem .env
uv run pytest -m postgres              # contra um Postgres real com pgvector (precisa de DATABASE_URL)
uv run pytest -m integracao            # chama o Bedrock de verdade (custo real; precisa de credencial AWS)
```

A verificação completa antes de um PR é `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` (no Windows PowerShell 5.1, que não tem `&&`, um comando por vez).

## Camadas

Os testes espelham `src/maria/` (`tests/<pasta>/test_*.py`).

| Camada | Onde | O que cobre |
|---|---|---|
| Unidade do grafo | `tests/fluxos/`, `tests/subgrafos/`, `tests/orquestrador/` | Lógica de decisão de cada grafo, invocado direto, sem HTTP. |
| HTTP | `tests/api/` | Mecânica das rotas (autenticação, `/health`, idempotência, status, `_links`), o pipeline que reproduz a ordem e os formatos de erro do Fastify da versão anterior, o TTL de inatividade (issue #166, com `TTL_INATIVIDADE_HORAS=0` para forçar a expiração sem mexer no relógio) e o bridge do WhatsApp. |
| Contrato Tykhe | `tests/api/test_contrato.py`, `tests/test_fixtures_contrato.py` | As 50 respostas HTTP e as 5 de log gravadas contra a versão TypeScript (`tests/fixtures/contrato/`), conferidas byte a byte (ver [`docs/contrato-tykhe.md`](contrato-tykhe.md)). |
| Conferência com a versão TypeScript | `tests/api/test_conferencia_pr1.py`, `tests/api/test_conferencia_pr2.py` | Centenas de cenários gravados contra a versão TypeScript, repetidos a cada execução como teste de regressão. |
| IA | `tests/ia/` | O padrão comum das chamadas ao Bedrock (simulação, retentativa, prazos), com um Bedrock falso que conta as requisições (`tests/ia/conftest.py`). |
| Integrações | `tests/integracoes/` | O cliente do Verde e o do WhatsApp contra servidores falsos. |
| Persistência | `tests/shared/` | As stores (`atendimentos`, `perguntas`, `fluxos_planejados`, embeddings), o checkpointer, o pool e o logger. Os testes marcados `postgres` rodam contra banco real. |
| Scripts | `tests/scripts/` | Os scripts de manutenção, inclusive a verificação dos 74 fluxos planejados contra o seed original. |
| Documentação | `tests/test_documentacao.py` | Links e caminhos dos documentos, referências à versão TypeScript só em registro histórico, e as variáveis de ambiente do código contra a tabela do README. |
| Integração real com IA | `tests/integracao/ia/` | Chama o Bedrock de verdade — não roda na suíte padrão nem no CI, só sob demanda (custa tempo e dinheiro real). |

## Modo mock — por que os testes não tocam infra real

`tests/conftest.py` fixa `APP_ENV=test` e `API_KEY=teste-fixo-chave` antes de importar a aplicação, e a suíte roda **sem** `VERDE_JWT_TOKEN` e **sem** `DATABASE_URL`. Isso já é o gatilho do modo mock: o cliente do Verde (`src/maria/integracoes/verde.py`) cai nas respostas simuladas, o checkpointer cai no `InMemorySaver`, as stores ficam em memória, e as chamadas de IA devolvem respostas simuladas (ver [`docs/ia.md`](ia.md)). Resultado: a suíte roda em qualquer máquina, sem AWS, sem segredo e sem rede.

**Store Postgres.** Os testes marcados `postgres` precisam de `DATABASE_URL` apontando para um Postgres 16 com pgvector, e apagam as tabelas de negócio antes de cada teste. **Nunca apontar para banco de produção ou de release.** Localmente, com Docker: `docker run -d --rm --name pg-teste -e POSTGRES_USER=maria -e POSTGRES_PASSWORD=maria -e POSTGRES_DB=maria -p 55432:5432 pgvector/pgvector:pg16` e `DATABASE_URL=postgresql://maria:maria@localhost:55432/maria uv run pytest -m postgres`. A issue #217 mostrou por que isso importa: um defeito que a store em memória escondia.

**Windows.** `tests/conftest.py` troca o loop de eventos pelo `WindowsSelectorEventLoopPolicy`, porque o psycopg assíncrono não funciona com o loop padrão do Windows. O CI e a imagem são Linux. Alguns testes precisam de um `sh` POSIX ou do comportamento de rede do Linux e são pulados no Windows; no CI, nada é pulado. Exceção: os 2 testes do `publish-grafana` (`tests/test_workflows.py`) só são pulados quando não há `bash` no PATH. Se o `bash` encontrado for o do WSL sem uma distribuição funcionando, eles **falham** em vez de serem pulados; a falha é do ambiente, não do código.

## O que NÃO existe ainda

- **Teste de contrato automatizado contra o Verde real** — a validação contra a API real do Verde (shape de resposta, bugs de doc) é manual (ver checklist em [`docs/integracao-verde.md`](integracao-verde.md)); já causou bug descoberto tarde (issue #108).
- **Coverage report** — sem cobertura medida nem limite mínimo; nenhuma decisão tomada ainda.

## CI

O `.github/workflows/ci.yml` tem dois jobs:
- **`test`:** `ruff check`, `ruff format --check`, `mypy`, a suíte padrão e, numa segunda etapa, a suíte `postgres` contra um Postgres 16 com pgvector (serviço do próprio job);
- **`imagem`:** constrói a imagem Docker e confere que ela sobe e responde `/health`.

Os deploys (`deploy-release.yml` e `deploy-prod.yml`) rodam os testes de novo antes de publicar — falha em qualquer etapa bloqueia o merge ou o deploy. Durante a migração, o `ci.yml` roda só em PR para a branch `migration`; os gatilhos de `develop` e `main` voltam no corte (#208).
