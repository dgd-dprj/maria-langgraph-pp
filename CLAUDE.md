# Maria — regras sempre válidas

Contexto completo: [`README.md`](README.md) e [`docs/`](docs/). Fluxo de contribuição: [`CONTRIBUTING.md`](CONTRIBUTING.md). Isto aqui é só o que precisa estar sempre presente, sem depender de disparar a skill certa.

## Nunca

- Commitar direto em `develop`/`main` — tudo entra por pull request ([`docs/padroes-branch.md`](docs/padroes-branch.md)).
- Logar CPF, RG, nome ou endereço de pessoa presa/vítima de violência doméstica em texto plano — são dados sensíveis (LGPD, categoria especial pra vítima de violência). Logs de negócio usam `chatId`/`fluxoId` pra correlação, nunca o dado em si.
- Commitar fonte de diagrama (`.mmd`, `.eraser`) ou o `.png` gerado — só a URL pública do bucket de docs entra em markdown (ver seção Diagramas abaixo).
- Rodar `terraform apply` sem `-target` explícito fora de uma sessão claramente autorizada pro escopo inteiro.

## Sempre

- Issue antes do código quando o pedido for "cria X" (ver [`docs/padroes-issues.md`](docs/padroes-issues.md)).
- Branch a partir de `develop` atualizada, nomenclatura `tipo/numero-descricao`.
- **Antes de começar uma issue, ou de abrir uma, procure se o trabalho já existe:** PR e branch com o número dela (`gh pr list --search "<número>" --state all`) e issue aberta sobre o mesmo assunto (`gh issue list --search`). Ao começar, atribua a issue a você. Uma issue, uma sessão. Detalhe em [`docs/padroes-branch.md`](docs/padroes-branch.md) e [`docs/padroes-issues.md`](docs/padroes-issues.md).
- **Comentário compartilhado** (como o catálogo de issues na #208): leia de novo logo antes de gravar e confira que ninguém gravou depois da sua leitura (`updated_at`). Em 2026-10-22, duas sessões gravaram por cima uma da outra, e uma linha sumiu.
- Commit no formato `:emoji: tipo: Descrição` em pt-BR ([`docs/padroes-commits.md`](docs/padroes-commits.md)).
- `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` passando antes de abrir PR ([`docs/testes.md`](docs/testes.md)).
- Ao mudar documentação, preservar as referências históricas: decisões datadas, registros de incidente e números de issue ficam como estão, mesmo citando arquivos da versão TypeScript ([`docs/migracao/`](docs/migracao/), spec 09).

## Infra

- Bucket de imagens de documentação: `s3://maria-langgraph-pp-docs-185327115563/diagramas/` (leitura pública, escrita só via credencial AWS). URL: `https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/<nome>.png`.
- VPC/subnets/RDS são de um stack Terraform **antigo**, só lido via `data.terraform_remote_state.old` — este repo nunca escreve nesse state.
- Secrets reais (token Verde, senha Postgres, API_KEY) são preenchidos manualmente via `aws secretsmanager put-secret-value` — nunca em texto plano no `.tf`/state.

## Diagramas

Fluxo/arquitetura/sequência: usar o guia de estilo do agente `diagram-specialist` (Mermaid, estilo fixo). Dois caminhos:
- **Issues e PRs**: bloco ` ```mermaid ` no próprio texto (o GitHub desenha).
- **`docs/*.md` e documentação estável**: PNG publicado no bucket acima, referenciado pela URL. Nunca commitar `.mmd`/`.png` fonte.
