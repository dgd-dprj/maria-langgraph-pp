---
name: padroes-pull-request
description: Regras de destino, título, template e merge de pull request deste repositório. Use antes de abrir qualquer PR.
---

# Padrões de pull request

A versão completa está em [`docs/padroes-pull-request.md`](../../../docs/padroes-pull-request.md) — este arquivo é o resumo que a skill carrega.

## Quando abrir PR: só com mudança de código (regra de 2026-10-27, #357)

- **PR só com mudança de código de fato:** `src/`, `tests/`, `scripts/`, `infra/`, `.github/`, `Dockerfile`, `pyproject.toml`, `uv.lock` ou configuração que muda o que roda.
- **Nunca abra PR só para mudança de texto.** Isso vale para `docs/` (inclusive índice de issues e specs), `README.md`, `CONTRIBUTING.md`, `MIGRACAO.md`, `CLAUDE.md`, `.claude/` (skills) e comentário ou docstring sem mudança de lógica.
  - Ela vai junto no próximo PR com código, em commit próprio `:books: docs:`.
  - Até lá, o registro fica na issue e na #208.
- **Mensagem ao assistido em `src/` é código:** muda o comportamento e segue a janela das correções.
- **Exceção:** só com decisão registrada na #208.
- Vale para as issues abertas e para as que vierem. Detalhe em [`docs/padroes-pull-request.md`](../../../docs/padroes-pull-request.md).

## Regras gerais

- Destino padrão: `develop` (`hotfix/*` → `main`).
- Um PR = uma issue de código, pequeno e focado. Issues só de texto podem ir junto (`Closes #N` de cada uma).
- Idioma: pt-BR (título e corpo).
- CI passando antes do merge; apagar branch depois.
- Merge: **squash** para branch de trabalho → `develop`; **merge commit** (nunca squash) para release `develop` → `main`.

## Título

```
:emoji: tipo: Descrição curta e objetiva
```

## Corpo (template obrigatório)

```markdown
## Resumo

## Issue relacionada
Closes #<numero>

## O que foi feito

## Como testar

## Observações (opcional)
```

## Diagrama explicativo (opcional)

Mudança de fluxo/arquitetura/sequência pode ganhar diagrama no corpo do PR, no guia de estilo do agente `diagram-specialist`: no corpo do PR, **Mermaid no texto** (bloco ` ```mermaid `); PNG publicado no bucket `s3://maria-langgraph-pp-docs-185327115563/diagramas/` para o que for para `docs/*.md`. Nunca commitar a fonte. Detalhe completo em [`docs/padroes-pull-request.md`](../../../docs/padroes-pull-request.md).

## Checklist antes de abrir

Tem mudança de código de fato (senão, não abra) · branch conforme padrão · título `:emoji: tipo:` · `Closes #N` · testes passando · critérios de aceitação da issue atendidos · sem segredos no diff.
