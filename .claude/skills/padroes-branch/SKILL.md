---
name: padroes-branch
description: Convenção de nome e fluxo de branch deste repositório. Use antes de criar qualquer branch de trabalho.
---

# Padrões de branch

A versão completa está em [`docs/padroes-branch.md`](../../../docs/padroes-branch.md) — este arquivo é o resumo que a skill carrega.

## Fluxo

- `develop` = dev (integração); base de toda branch de trabalho e destino padrão dos PRs.
- `staging` = QA (alimenta o release); recebe merge só de `develop`.
- `main` = produção; recebe merge só de `staging`.
- Correção urgente segue o mesmo caminho: `develop` → `staging` → `main` (#427).
- Nunca commitar direto em `develop`, `staging` ou `main`: tudo entra por pull request.

## Nomenclatura

```
tipo/numero-da-issue-descricao-curta
```

- `tipo`: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `ci`, `perf`.
- `numero-da-issue`: número da issue do GitHub (obrigatório quando existir issue).
- `descricao-curta`: kebab-case, minúsculas, sem acentos, 2–5 palavras.
- Sem issue (raro): `tipo/descricao-curta`.
- Toda branch de trabalho parte de `develop`, inclusive a de correção urgente (#427).

Exemplos: `feat/1-cliente-http-token-env`, `fix/12-banner-503-nao-fecha`.

## Antes de criar a branch: procurar e marcar (obrigatório)

1. **Procure** PR ou branch com o número da issue: `gh pr list --search "<número>" --state all` e `git ls-remote --heads origin "*<número>*"`. Se houver, pare e avise quem pediu o trabalho.
2. **Marque**: `gh issue edit <número> --add-assignee @me`. Issue atribuída a outra pessoa: pare e avise.
3. **Uma issue, uma sessão**: não trabalhe numa issue que outra sessão já esteja fazendo.

Motivo: em 2026-10-22, duas sessões implementaram a mesma issue com um minuto de diferença (PRs #289 e #290). Detalhe em [`docs/padroes-branch.md`](../../../docs/padroes-branch.md).

## Regras

- Uma branch = uma issue. Escopo cresceu → nova issue + nova branch.
- Criar a partir de `develop` atualizada (`git pull` antes).
- Apagar a branch após o merge.
