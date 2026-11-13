# Contribuindo

Setup local, variáveis de ambiente e estrutura de pastas: ver [`README.md`](README.md). Este arquivo cobre só o fluxo de contribuição.

## Branches e ambientes

Três branches permanentes, no estilo do GitLab Flow (#427, decisão da Nicole de 2026-11-06). O código sobe sempre por PR: branch de trabalho → `develop` → `staging` → `main`.

| Branch | Papel | Ambiente | O que dispara o deploy |
|---|---|---|---|
| `develop` | **dev**: integração de tudo que é feito | nenhum: só o CI e os testes locais | nada |
| `staging` | **QA**: validação antes da produção | o release (serviço `api-release`), que é o ambiente de QA | todo merge em `staging` (`deploy-release.yml`) |
| `main` | **produção** | produção (serviço `api`) | todo merge em `main` (`deploy-prod.yml`) |

- **Promover para QA:** PR de `develop` para `staging`, quando um conjunto de mudanças estiver pronto para validar. O CI recusa PR para `staging` que não venha da `develop`.
- **Promover para a produção:** PR de `staging` para `main`, depois da validação no release, no horário combinado (reinicia a produção, onde estão a equipe e o atendimento real). O CI recusa PR para `main` que não venha da `staging`.
- **Correção urgente** também passa pelas três: `develop` → `staging` → `main`, com o horário combinado.
- **O ambiente continua se chamando `release` na infraestrutura.** Renomear recriaria o segredo, o serviço, o banco e os logs (#286). O release é o QA.
- **Cada merge em `staging` reinicia o release.** Quem estiver testando pelo WhatsApp perde a conversa em andamento, porque a ponte guarda as conversas abertas em memória ([`docs/bridge-whatsapp.md`](docs/bridge-whatsapp.md)). Durante uma rodada de teste, combine o horário da promoção.
- **Até 2026-11-06,** `develop` fazia o papel de staging e cada merge nela subia no release. A decisão de 2026-10-22 de deixar os nomes como estavam até o corte (#268) foi revista na #427.

**Proteção (rulesets do GitHub):** proteção leve, porque a equipe é pequena. A decisão é da Nicole, de 2026-11-06, e substitui as regras de 2026-10-22 (#214).

| Regra | `develop` | `staging` (#427) | `main` |
|---|---|---|---|
| CI verde obrigatório (`test` e `imagem`) | sim | sim | sim |
| Entrada só por PR | não exigida pelo ruleset | sim | sim |
| De onde vem o PR | branch de trabalho | só `develop` (conferido pelo CI) | só `staging` (conferido pelo CI) |
| Revisão aprovada | não exigida | não exigida | não exigida |
| Método de merge | squash (padrão) ou merge commit | só merge commit | só merge commit |
| Force push e exclusão da branch | bloqueados | bloqueados | bloqueados |

Nada além disso. Na `develop`, o caminho continua sendo o PR: o CI só roda nos PRs, então um push direto chega sem o CI verde e é recusado.

A promoção (`develop` → `staging` e `staging` → `main`) usa sempre merge commit, e o ruleset das duas branches só aceita esse método: squash reescreveria commits que já estão na branch de origem, e a promoção seguinte entraria em conflito.

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
- Destino padrão é `develop` (o GitHub recusa push direto em `staging` e em `main`, e na `develop` o push direto não passa sem o CI verde). PR para `staging` só vem da `develop`, e para `main` só da `staging`.
- O CI precisa passar antes do merge, e o GitHub bloqueia o merge sem ele: o job `test` (lint, tipos, a suíte padrão e a suíte com Postgres) e o job `imagem` (constrói a imagem Docker e confere o `/health`).

## Resumo rápido

| O quê | Onde |
|---|---|
| Issue | [`docs/padroes-issues.md`](docs/padroes-issues.md) |
| Branch | [`docs/padroes-branch.md`](docs/padroes-branch.md) |
| Commit | [`docs/padroes-commits.md`](docs/padroes-commits.md) |
| Pull request | [`docs/padroes-pull-request.md`](docs/padroes-pull-request.md) |
| Arquitetura/regras de negócio | [`docs/arquitetura.md`](docs/arquitetura.md) e demais em [`docs/`](docs/) |
