# Contribuindo

Setup local, variáveis de ambiente e estrutura de pastas: ver [`README.md`](README.md). Este arquivo cobre só o fluxo de contribuição.

## Antes de codar

1. Confirme que existe uma issue pro trabalho (crie uma se não existir — padrão em [`docs/padroes-issues.md`](docs/padroes-issues.md)).
2. Crie uma branch a partir de `develop` atualizada — nomenclatura em [`docs/padroes-branch.md`](docs/padroes-branch.md).

## Durante

- Commits seguem [`docs/padroes-commits.md`](docs/padroes-commits.md) (Conventional Commits em pt-BR com emoji).
- `pnpm test` precisa passar antes de abrir PR — detalhes em [`docs/testes.md`](docs/testes.md).

## Abrindo o PR

- Template e regras de merge em [`docs/padroes-pull-request.md`](docs/padroes-pull-request.md).
- Destino padrão é `develop` (nunca commitar direto em `main`/`develop`).
- CI (`pnpm test`) precisa passar antes do merge.

## Resumo rápido

| O quê | Onde |
|---|---|
| Issue | [`docs/padroes-issues.md`](docs/padroes-issues.md) |
| Branch | [`docs/padroes-branch.md`](docs/padroes-branch.md) |
| Commit | [`docs/padroes-commits.md`](docs/padroes-commits.md) |
| Pull request | [`docs/padroes-pull-request.md`](docs/padroes-pull-request.md) |
| Arquitetura/regras de negócio | [`docs/arquitetura.md`](docs/arquitetura.md) e demais em [`docs/`](docs/) |
