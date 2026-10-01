---
name: padroes-commits
description: Convenção de mensagem de commit deste repositório (Conventional Commits em pt-BR com emoji). Use ao criar qualquer commit.
---

# Padrões de commits

A versão completa está em [`docs/padroes-commits.md`](../../../docs/padroes-commits.md) — este arquivo é o resumo que a skill carrega.

Toda mensagem de commit segue **Conventional Commits em pt-BR com emoji**:

```
:emoji: tipo: Descrição curta
```

Exemplo real do histórico: `:sparkles: feat: Criação da estrutura com Shadcn UI`

## Regras

- Emoji no início, em formato `:codigo:` (GitHub renderiza).
- Descrição sucinta em pt-BR; detalhes vão no corpo do commit.
- Corpo (opcional): motivos, impactos e instruções para intervenções futuras.
- Rodapé (opcional): revisor e referência de card/issue. Ex: `Reviewed-by: Fulano Refs #133`.
- Links sempre na forma autêntica (sem encurtadores).

## Tipos principais

| Tipo | Uso | Emoji padrão |
|---|---|---|
| `feat` | novo recurso | ✨ `:sparkles:` |
| `fix` | correção de bug | 🐛 `:bug:` |
| `docs` | documentação | 📚 `:books:` |
| `test` | testes | 🧪 `:test_tube:` |
| `build` | build e dependências | 📦 `:package:` |
| `refactor` | refatoração sem mudar comportamento | ♻️ `:recycle:` |
| `chore` | tarefas de build/config/pacotes | 🔧 `:wrench:` |
| `ci` | integração contínua | 🧱 `:bricks:` |

Tabela completa de tipos e emojis por contexto em [`docs/padroes-commits.md`](../../../docs/padroes-commits.md).

## Exemplos

- `:books: docs: Atualização do README`
- `:bug: fix: Loop infinito na linha 50`
- `:sparkles: feat: Página de login`
- `:recycle: refactor: Passando para arrow functions`
