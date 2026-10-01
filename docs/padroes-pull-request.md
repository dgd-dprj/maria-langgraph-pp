# Padrões de pull request

## Regras gerais

- Destino padrão: `develop` (`hotfix/*` → `main`).
- Um PR = uma issue; pequeno e focado.
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

PR que muda fluxo de negócio, arquitetura ou sequência de integração pode se beneficiar de um diagrama no corpo:

1. Gerar com o agente `diagram-specialist` (Mermaid, estilo fixo — losango = decisão, paralelogramo = chamada externa, verde = sucesso, vermelho = handoff/erro).
2. **Nunca** commitar o `.mmd`/`.png` fonte no git — só o resultado publicado.
3. Subir o PNG final pro bucket de docs: `aws s3 cp <nome>.png s3://maria-langgraph-pp-docs-185327115563/diagramas/<nome>.png --content-type image/png --region us-east-1`.
4. Confirmar `200` na URL pública antes de referenciar (`curl -s -o /dev/null -w "%{http_code}\n" <url>`).
5. Embutir no corpo do PR (ex: na seção "O que foi feito" ou "Observações"): `![descrição](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/<nome>.png)`.

## Checklist antes de abrir

Branch conforme [`padroes-branch.md`](padroes-branch.md) · título `:emoji: tipo:` · `Closes #N` · typecheck/lint passando · critérios de aceitação da issue atendidos · sem segredos no diff.
