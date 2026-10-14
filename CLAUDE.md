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
- Commit no formato `:emoji: tipo: Descrição` em pt-BR ([`docs/padroes-commits.md`](docs/padroes-commits.md)).
- `pnpm test` passando antes de abrir PR ([`docs/testes.md`](docs/testes.md)).

## Infra

- Bucket de imagens de documentação: `s3://maria-langgraph-pp-docs-185327115563/diagramas/` (leitura pública, escrita só via credencial AWS). URL: `https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/<nome>.png`.
- VPC/subnets/RDS são de um stack Terraform **antigo**, só lido via `data.terraform_remote_state.old` — este repo nunca escreve nesse state.
- Secrets reais (token Verde, senha Postgres, API_KEY) são preenchidos manualmente via `aws secretsmanager put-secret-value` — nunca em texto plano no `.tf`/state.

## Diagramas

Fluxo/arquitetura/sequência: usar o guia de estilo do agente `diagram-specialist` (Mermaid, estilo fixo). Dois caminhos:
- **Issues e PRs**: bloco ` ```mermaid ` no próprio texto (o GitHub desenha).
- **`docs/*.md` e documentação estável**: PNG publicado no bucket acima, referenciado pela URL. Nunca commitar `.mmd`/`.png` fonte.
