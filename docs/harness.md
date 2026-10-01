# Harness (Claude Code neste repo)

Config em volta do agente, tudo project-scoped (dentro do repo — qualquer colaborador que abrir com Claude Code já carrega, sem depender de config global de ninguém).

## `CLAUDE.md`

Contexto sempre carregado, sem precisar de gatilho:

- [`CLAUDE.md`](../CLAUDE.md) (raiz) — regras que não podem falhar: nunca commitar direto em `develop`/`main`, nunca logar dado sensível LGPD em plaintext, nunca commitar fonte de diagrama, infra (bucket de docs, stack antigo, secrets).
- [`infra/terraform/CLAUDE.md`](../infra/terraform/CLAUDE.md) — sempre `-target` explícito, nunca escrever no state antigo.
- [`src/ia/CLAUDE.md`](../src/ia/CLAUDE.md) — custo real de chamada ao Bedrock, nunca logar prompt/resposta com dado sensível, manter caminho mock em teste.

## Skills (`.claude/skills/`)

Carregam sob gatilho (criar issue, commit, branch, PR):

- `padroes-branch`, `padroes-commits`, `padroes-issues`, `padroes-pull-request` — resumo; versão completa em [`docs/padroes-branch.md`](padroes-branch.md), [`docs/padroes-commits.md`](padroes-commits.md), [`docs/padroes-issues.md`](padroes-issues.md), [`docs/padroes-pull-request.md`](padroes-pull-request.md).

## Agentes (`.claude/agents/`)

- **`diagram-specialist`** — gera diagrama Mermaid com estilo fixo (losango=decisão, paralelogramo=chamada externa, verde=sucesso, vermelho=handoff), publica no bucket de docs. Nunca commita a fonte.
- **`code-reviewer`** — revisa diff de uma branch/PR: segredo no diff, dado sensível em log, convenção de commit/branch, teste/doc faltando, `pnpm test`/`typecheck`. Não edita código, só reporta.

## Slash commands (`.claude/commands/`)

- **`/release`** — abre o PR `develop`→`main` seguindo o padrão do repo (lista o que está entrando, lembra que o merge tem que ser merge commit, nunca squash).

## Hooks (`.claude/settings.json` + `.claude/hooks/`)

- **`block-secrets.mjs`** (PreToolUse, `Edit|Write`) — bloqueia edição em arquivo que provavelmente guarda segredo real (`.env`, `*.pem`, `*.key`, `credentials*.json`).
- **`typecheck-after-edit.mjs`** (PostToolUse, `Edit|Write`) — depois de editar um `.ts`, roda `pnpm typecheck` e reporta erro na hora, sem esperar o CI.

Ambos falham aberto: erro inesperado no script nunca bloqueia por engano, só bloqueia quando reconhece o padrão de risco de verdade.
