# Padrões de pull request

## Quando abrir PR: só com mudança de código

Regra de 2026-10-27 (Nicole, #357), para as issues abertas e para as que vierem.

- **Abra PR só quando houver mudança de código de fato:** `src/`, `tests/`, `scripts/`, `infra/`, `.github/`, `Dockerfile`, `pyproject.toml`, `uv.lock` ou outra configuração que muda o que roda.
- **Mudança só de texto não ganha PR próprio.** Exemplos: `docs/` (inclusive `docs/migracao/`: índice de issues e specs), `README.md`, `CONTRIBUTING.md`, `MIGRACAO.md`, `CLAUDE.md`, `.claude/` (skills e agentes), comentário ou docstring sem mudança de lógica.
  - Ela entra junto no próximo PR que tenha código, num commit próprio `:books: docs:`, listado em "O que foi feito".
  - Até lá, o registro fica na issue, no comentário da #208 e na cópia de trabalho fora do repositório.
- **Texto que o assistido vê conta como código.** As mensagens em `src/` mudam o comportamento e seguem as regras da janela das correções: guia de teste e horário combinado.
- **Exceção:** só com decisão registrada na #208. Exemplo: um documento errado que a equipe está usando no teste.
- **Por quê:** das 30 últimas execuções do CI em PR (#199 a #228, de 23 a 27/10), 19 eram de PR com título `:books: docs:` (levantamento da #357). Cada uma rodou a esteira inteira para validar texto, e cada PR a mais é mais uma rodada de revisão e merge.

## Regras gerais

- Destino padrão: `develop` (`hotfix/*` → `main`).
- Um PR = uma issue de código, pequeno e focado. Issues só de texto podem ir junto (`Closes #N` de cada uma).
- Idioma: pt-BR (título e corpo).
- CI passando antes do merge; apagar branch depois.
- Merge: **squash** para branch de trabalho → `develop`; **merge commit** (nunca squash) para release `develop` → `main` — squash no release reescreve commits compartilhados e gera conflito no próximo.

## Título

Mesmo formato dos commits (ver [`padroes-commits.md`](padroes-commits.md)):

```
:emoji: tipo: Descrição curta e objetiva
```

Ex: `:sparkles: feat: Cliente HTTP com token por env`

## Corpo (template obrigatório)

```markdown
## Resumo

O que este PR faz e por quê, em 1–3 frases.

## Issue relacionada

Closes #<numero>

## O que foi feito

- Mudança 1
- Mudança 2

## Como testar

Passos objetivos para o revisor validar.

## Observações (opcional)

Decisões, débitos assumidos, prints.
```

- `Closes #N` / `Fixes #N` para fechar a issue no merge.
- "Como testar" obrigatório quando há mudança de comportamento visível.

## Diagrama explicativo (opcional)

PR que muda fluxo de negócio, arquitetura ou sequência de integração pode se beneficiar de um diagrama no corpo. Mesmo guia de estilo do agente `diagram-specialist` (losango = decisão, paralelogramo = chamada externa, verde = sucesso, laranja = handoff/erro), dois caminhos:

- **A. Mermaid no texto (padrão no corpo do PR)** — bloco ` ```mermaid `; o GitHub desenha sozinho.
- **B. PNG publicado no S3 (padrão para `docs/*.md`)** — quando o PR também atualiza documentação estável:
  1. Gerar com o `diagram-specialist`; **nunca** commitar o `.mmd`/`.png` fonte no git.
  2. Subir: `aws s3 cp <nome>.png s3://maria-langgraph-pp-docs-185327115563/diagramas/<nome>.png --content-type image/png --region us-east-1`.
  3. Confirmar `200` na URL pública antes de referenciar (`curl -s -o /dev/null -w "%{http_code}\n" <url>`).
  4. Embutir: `![descrição](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/<nome>.png)`.

## Checklist antes de abrir

Tem mudança de código de fato (senão, não abra; ver "Quando abrir PR") · branch conforme [`padroes-branch.md`](padroes-branch.md) · título `:emoji: tipo:` · `Closes #N` · typecheck/lint passando · critérios de aceitação da issue atendidos · sem segredos no diff.
