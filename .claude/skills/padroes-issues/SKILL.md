---
name: padroes-issues
description: Estrutura, evidência e checklist obrigatórios para issues neste repositório. Use antes de criar, ampliar, corrigir ou fechar qualquer issue no GitHub, e antes de comentar um achado numa issue.
---

# Padrões de criação de issues

A versão completa está em [`docs/padroes-issues.md`](../../../docs/padroes-issues.md) — este arquivo é o resumo que a skill carrega.

Toda issue: clara, acionável, testável, com contexto suficiente pra ser entendida sem esclarecimentos adicionais. Idioma: pt-BR.

## Antes de abrir

- **Procurar duplicata** (abertas e fechadas): `gh issue list --state all --search "<termos>"`. Existe? Comente nela ou amplie o escopo ("**Ampliada em AAAA-MM-DD:** …" no topo) em vez de abrir outra. Duplicata aberta por engano: fechar a mais nova apontando a original.
- **Conferir cada `arquivo:linha`** no commit citado antes de publicar.
- **Uma issue = um assunto.** Outro problema achado vira outra issue, com referência cruzada.

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

- Toda afirmação com fonte: `arquivo:linha` em `develop @ <commit>`, execução (o quê, versão, data) ou link de documentação.
- **Cada afirmação com a sua marca**: **lido** (código/doc, sem executar), **executado** (o quê, onde, quando), **relato** (de quem), **não verificado**. Tabela "O quê | Onde | Evidência" quando houver várias.
- **Herdado × regressão**: se o defeito já existia antes, dizer e mostrar o controle.
- Consulta de log sempre com **conferência manual** (um controle que prova que a consulta acha o que procura) — senão zero por ausência e zero por consulta errada parecem iguais.
- Correção de issue publicada: comentário datado + marca "**Corrigido em AAAA-MM-DD:** …" no corpo. Nada some sem explicação.
- Nenhum dado pessoal: só contagens e conclusões, nunca o conteúdo (CPF, RG, nome, telefone, relato, `chatId` de WhatsApp).

## Depois de abrir, mudar ou fechar

- **Catálogo no mesmo passo**: issue nova, mudança de estado ou de escopo entra em `docs/migracao/INDICE-ISSUES.md` (número, tipo, módulo, estado, resumo) e no catálogo publicado na #208.
- **Relacionadas nos dois sentidos**: comentar também na issue relacionada.
- **Ao fechar**: comentário com o que resolveu (PR/commit) ou o motivo (duplicada, decidido não fazer).

## Regras para o assistente de IA

- Gerar critérios de aceitação quando ausentes; gerar BDD quando houver comportamento.
- Identificar ambiguidades ANTES de implementar — nunca assumir requisito não informado.

Checklist completo e exemplos em [`docs/padroes-issues.md`](../../../docs/padroes-issues.md).
