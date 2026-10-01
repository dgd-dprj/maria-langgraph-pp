---
name: padroes-issues
description: Estrutura e checklist obrigatório pra criar issues neste repositório. Use antes de criar qualquer issue no GitHub.
---

# Padrões de criação de issues

A versão completa está em [`docs/padroes-issues.md`](../../../docs/padroes-issues.md) — este arquivo é o resumo que a skill carrega.

Toda issue: clara, acionável, testável, com contexto suficiente pra ser entendida sem esclarecimentos adicionais. Idioma: pt-BR.

## Título

```
[TYPE] Descrição curta e objetiva
```

Tipos: `[FEATURE]`, `[ENHANCEMENT]`, `[BUG]`, `[TECH]`.

## Estrutura obrigatória do corpo

1. **Contexto de Negócio** — por que este trabalho é necessário.
2. **Declaração do Problema** — situação atual.
3. **Solução Esperada** — comportamento desejado.
4. **Critérios de Aceitação** — checklist objetivo e testável (`- [ ]`).

## Quando aplicável

- **Cenários BDD** — sempre que houver comportamento descrito (sucesso + erro), formato Gherkin.
- **Requisitos Não Funcionais**, **Dependências**, **Fora de Escopo**.
- **Diagrama explicativo (opcional)** — fluxo/arquitetura/sequência pode ganhar diagrama: gerar com o agente `diagram-specialist` (Mermaid), nunca commitar a fonte, subir o PNG pro bucket `s3://maria-langgraph-pp-docs-185327115563/diagramas/`, embutir a URL pública na issue. Detalhe completo em [`docs/padroes-issues.md`](../../../docs/padroes-issues.md).

## Regras para o assistente de IA

- Gerar critérios de aceitação quando ausentes; gerar BDD quando houver comportamento.
- Identificar ambiguidades ANTES de implementar — nunca assumir requisito não informado.

Checklist completo e exemplos em [`docs/padroes-issues.md`](../../../docs/padroes-issues.md).
