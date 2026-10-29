---
name: padroes-issues
description: Estrutura e checklist obrigatório pra criar issues neste repositório. Use antes de criar qualquer issue no GitHub.
---

# Padrões de criação de issues

A versão completa está em [`docs/padroes-issues.md`](../../../docs/padroes-issues.md) — este arquivo é o resumo que a skill carrega.

Toda issue: clara, acionável, testável, com contexto suficiente pra ser entendida sem esclarecimentos adicionais. Idioma: pt-BR.

## Antes de abrir: procurar (obrigatório)

- **Procure issue aberta sobre o mesmo assunto:** `gh issue list --state open --search "<palavras do assunto>"`. Se houver, acrescente nela (comentário) em vez de abrir outra.
- **Achou duplicata depois de abrir:** feche a que foi aberta **por último**, pelo horário de criação do GitHub (`gh issue view <n> --json createdAt`), citando a outra e um motivo que dê para conferir. Não escreva o motivo de memória: em 2026-10-22, a #292 foi fechada dizendo que a #293 era "minutos antes", e ela era 18 segundos depois.

## Issue só de texto: sem branch e sem PR próprios (regra de 2026-10-27, #357)

- Issue de documentação, índice, padrão, skill ou `MIGRACAO.md` não ganha branch nem PR próprios.
- O texto entra junto no próximo PR com mudança de código (commit `:books: docs:`), e a issue fecha com o `Closes #N` desse PR.
- Nos critérios de aceitação, escreva: "entra junto no próximo PR com código".
- Mensagem ao assistido em `src/` é código, não "só texto".
- Vale para as issues abertas e para as que vierem. Regra completa na skill `padroes-pull-request`.

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
