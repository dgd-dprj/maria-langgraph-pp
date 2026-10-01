---
name: padroes-branch
description: Convenção de nome e fluxo de branch deste repositório. Use antes de criar qualquer branch de trabalho.
---

# Padrões de branch

A versão completa está em [`docs/padroes-branch.md`](../../../docs/padroes-branch.md) — este arquivo é o resumo que a skill carrega.

## Fluxo

- `main` = produção; recebe merge só de `develop` (release) ou `hotfix/*`.
- `develop` = integração; base de toda branch de trabalho e destino padrão dos PRs.
- Nunca commitar direto em `main`/`develop` — tudo entra por pull request.

## Nomenclatura

```
tipo/numero-da-issue-descricao-curta
```

- `tipo`: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `ci`, `perf`, `hotfix`.
- `numero-da-issue`: número da issue do GitHub (obrigatório quando existir issue).
- `descricao-curta`: kebab-case, minúsculas, sem acentos, 2–5 palavras.
- Sem issue (raro): `tipo/descricao-curta`.
- `hotfix/*` é a exceção que parte de `main`.

Exemplos: `feat/1-cliente-http-token-env`, `fix/12-banner-503-nao-fecha`, `hotfix/21-crash-ao-abrir-fluxo`.

## Regras

- Uma branch = uma issue. Escopo cresceu → nova issue + nova branch.
- Criar a partir de `develop` atualizada (`git pull` antes).
- Apagar a branch após o merge.
