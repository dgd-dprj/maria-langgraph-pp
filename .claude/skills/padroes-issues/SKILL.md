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
- **Diagrama explicativo (opcional)** — fluxo/arquitetura/sequência pode ganhar diagrama, sempre no guia de estilo do agente `diagram-specialist`. Em issue: **Mermaid no texto** (bloco ` ```mermaid `, o GitHub desenha). PNG publicado no bucket `s3://maria-langgraph-pp-docs-185327115563/diagramas/` fica para `docs/*.md` e documentação estável. Dados de exemplo sempre fictícios. Detalhe em [`docs/padroes-issues.md`](../../../docs/padroes-issues.md).

## Evidência e rastreabilidade (obrigatório em `[BUG]` e afirmações sobre o comportamento atual)

- Toda afirmação com fonte: `arquivo:linha` em `develop @ <commit>`, execução (o quê, versão, data) ou link de documentação. O que não foi verificado é marcado **não verificado**.
- Consulta de log sempre com **conferência manual** (um controle que prova que a consulta acha o que procura) — senão zero por ausência e zero por consulta errada parecem iguais.
- Correção de issue publicada: comentário datado + marca "**Corrigido em AAAA-MM-DD:** …" no corpo. Nada some sem explicação.
- Nenhum dado pessoal: só contagens e conclusões, nunca o conteúdo (CPF, RG, nome, telefone, relato, `chatId` de WhatsApp).

## Regras para o assistente de IA

- Gerar critérios de aceitação quando ausentes; gerar BDD quando houver comportamento.
- Identificar ambiguidades ANTES de implementar — nunca assumir requisito não informado.

Checklist completo e exemplos em [`docs/padroes-issues.md`](../../../docs/padroes-issues.md).
