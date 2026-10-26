# Contribuindo

Setup local, variáveis de ambiente e estrutura de pastas: ver [`README.md`](README.md). Este arquivo cobre só o fluxo de contribuição.

## Branches e ambientes

| Branch | Papel | Ambiente | O que dispara o deploy |
|---|---|---|---|
| `develop` | **staging**: integração e validação pela equipe | homologação, chamado de `release` na infraestrutura (serviço `api-release`) | todo merge em `develop` (`deploy-release.yml`) |
| `main` | **produção** | produção (serviço `api`) | todo merge em `main` (`deploy-prod.yml`) |

- **Os nomes ficam como estão** até depois do corte da migração (#268), por decisão de 2026-10-22: renomear branch ou ambiente no meio do teste da equipe confundiria qualquer problema que aparecesse. Uma branch de integração separada e a troca de nomes ficam para depois, junto com o ambiente novo da #286.
- **Todo merge em `develop` reinicia o release.** Quem estiver testando pelo WhatsApp perde a conversa em andamento, porque a ponte guarda as conversas abertas em memória ([`docs/bridge-whatsapp.md`](docs/bridge-whatsapp.md)). Durante uma rodada de teste da equipe, combine o horário do merge.
- **Corrigido em 2026-10-26: a equipe testa na `main` (produção), pela Tykhe, e não no release.** Hoje ninguém usa o release, então merge em `develop` não precisa de horário combinado. O horário combinado vale para o PR de release (`develop` → `main`), que reinicia a produção, onde estão a equipe e o atendimento real. A coluna "Papel" da tabela acima descreve o desenho, e não o uso atual.

**Proteção (rulesets do GitHub, desde 2026-10-22, #214):**

| Regra | `develop` | `main` |
|---|---|---|
| Push direto | bloqueado: tudo entra por PR | bloqueado: tudo entra por PR |
| Checks obrigatórios | `test` e `imagem` | `test` e `imagem`, com a branch atualizada |
| Aprovações | nenhuma | 1 |
| Método de merge | squash (padrão) ou merge commit | só merge commit |
| Force push e exclusão da branch | bloqueados | bloqueados |

Ninguém contorna as regras, nem quem é admin. Numa emergência, um admin desativa o ruleset nas configurações do repositório, e isso fica registrado.

> **Não "corrija" esta configuração sem combinar com o Ícaro.** Ela existe porque as sessões do Claude do Ícaro reaproveitavam a mesma branch em PR após PR (`claude/project-thread-u8h56h`: #276, #284, #289, #291, #295, #315).
> - **`develop` aceita merge commit, e não só squash.** Com squash obrigatório, o PR seguinte de uma branch reaproveitada traria de novo commits já mergeados e entraria em conflito.
>
> Volta à mesa quando cada PR tiver a própria branch. Registro em `MIGRACAO.md`, seção "Branches, ambientes e proteção".

**A branch é apagada sozinha depois do merge** (religado em 2026-10-23). A exclusão automática ficou desligada enquanto a branch reaproveitada existia; o Ícaro apagou essa branch depois do #315. Se uma sessão recriar a branch com o mesmo nome, nada quebra: `develop` aceita merge commit.

## Antes de codar

1. Confirme que existe uma issue pro trabalho (crie uma se não existir — padrão em [`docs/padroes-issues.md`](docs/padroes-issues.md)).
2. Crie uma branch a partir de `develop` atualizada — nomenclatura em [`docs/padroes-branch.md`](docs/padroes-branch.md).

## Durante

- Commits seguem [`docs/padroes-commits.md`](docs/padroes-commits.md) (Conventional Commits em pt-BR com emoji).
- A verificação precisa passar antes de abrir PR — `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`; detalhes em [`docs/testes.md`](docs/testes.md).

## Abrindo o PR

- Template e regras de merge em [`docs/padroes-pull-request.md`](docs/padroes-pull-request.md).
- Destino padrão é `develop` (o GitHub recusa push direto em `main` e em `develop`).
- O CI precisa passar antes do merge, e o GitHub bloqueia o merge sem ele: o job `test` (lint, tipos, a suíte padrão e a suíte com Postgres) e o job `imagem` (constrói a imagem Docker e confere o `/health`).

## Resumo rápido

| O quê | Onde |
|---|---|
| Issue | [`docs/padroes-issues.md`](docs/padroes-issues.md) |
| Branch | [`docs/padroes-branch.md`](docs/padroes-branch.md) |
| Commit | [`docs/padroes-commits.md`](docs/padroes-commits.md) |
| Pull request | [`docs/padroes-pull-request.md`](docs/padroes-pull-request.md) |
| Arquitetura/regras de negócio | [`docs/arquitetura.md`](docs/arquitetura.md) e demais em [`docs/`](docs/) |
