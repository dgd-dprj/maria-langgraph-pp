# Padrões de branch

## Fluxo

- `main` = produção; recebe merge só de `develop` (release) ou `hotfix/*`.
- `develop` = integração; base de toda branch de trabalho e destino padrão dos PRs.
- Nunca commitar direto em `main`/`develop` — tudo entra por pull request.

## Nomenclatura

```
tipo/numero-da-issue-descricao-curta
```

- `tipo`: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `ci`, `perf`, `hotfix` (alinhado aos tipos de commit em [`padroes-commits.md`](padroes-commits.md)).
- `numero-da-issue`: número da issue do GitHub (obrigatório quando existir issue).
- `descricao-curta`: kebab-case, minúsculas, sem acentos, 2–5 palavras.
- Sem issue (raro): `tipo/descricao-curta`.
- `hotfix/*` é a exceção que parte de `main`.

Exemplos: `feat/1-cliente-http-token-env`, `fix/12-banner-503-nao-fecha`, `hotfix/21-crash-ao-abrir-fluxo`.

## Antes de criar a branch: procurar e marcar

Em 2026-10-22 houve três casos de trabalho duplicado num só dia: a #288 implementada duas vezes (PRs #289 e #290, com um minuto de diferença), as #292 e #293 abertas com 18 segundos de diferença, e o catálogo da #208 sobrescrito por duas sessões. Registro em `MIGRACAO.md`, "Aviso de processo".

1. **Procure.** Há PR ou branch com o número da issue? `gh pr list --search "<número>" --state all` e `git ls-remote --heads origin "*<número>*"`. Se houver, fale com quem abriu antes de começar.
2. **Marque.** Atribua a issue a você (`gh issue edit <número> --add-assignee @me`). Issue atribuída a outra pessoa: fale com ela antes.
3. **Uma issue, uma sessão.** Não entregue a mesma issue a duas sessões do Claude ao mesmo tempo.

## Regras

- Uma branch = uma issue. Escopo cresceu → nova issue + nova branch.
- Criar a partir de `develop` atualizada (`git pull` antes).
- Apagar a branch após o merge.
