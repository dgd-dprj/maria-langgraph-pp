# Padrões de commits

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

## Tipos

| Tipo | Uso | Emoji padrão |
|---|---|---|
| `feat` | novo recurso (MINOR) | ✨ `:sparkles:` |
| `fix` | correção de bug (PATCH) | 🐛 `:bug:` |
| `docs` | documentação (sem código) | 📚 `:books:` |
| `test` | testes (criar/alterar/excluir) | 🧪 `:test_tube:` |
| `build` | build e dependências | 📦 `:package:` |
| `perf` | performance | ⚡ `:zap:` |
| `style` | formatação, lint (sem lógica) | 👌 `:ok_hand:` |
| `refactor` | refatoração sem mudar funcionalidade | ♻️ `:recycle:` |
| `chore` | tarefas de build/config/pacotes | 🔧 `:wrench:` |
| `ci` | integração contínua | 🧱 `:bricks:` |
| `raw` | arquivos de config, dados, parâmetros | 🗃️ `:card_file_box:` |
| `cleanup` | remover código morto/comentado | 🧹 `:broom:` |
| `remove` | excluir arquivos/funcionalidades obsoletas | 🗑️ `:wastebasket:` |

## Emojis por contexto (substituem o padrão quando mais específicos)

| Contexto | Emoji |
|---|---|
| Commit inicial | 🎉 `:tada:` |
| Estilização de interface | 💄 `:lipstick:` (tipo `feat`) |
| Responsividade | 📱 `:iphone:` |
| Animações/transições | 💫 `:dizzy:` |
| Acessibilidade | ♿ `:wheelchair:` |
| Comentários no código | 💡 `:bulb:` (tipo `docs`) |
| Texto/copy | 📝 `:pencil:` |
| Tipagem | 🏷️ `:label:` |
| Tratamento de erros | 🥅 `:goal_net:` |
| Segurança | 🔒️ `:lock:` |
| SEO | 🔍️ `:mag:` |
| Deploy | 🚀 `:rocket:` |
| Em progresso | 🚧 `:construction:` |
| Mover/renomear | 🚚 `:truck:` (tipo `chore`) |
| Adicionar dependência | ➕ `:heavy_plus_sign:` (tipo `build`) |
| Remover dependência | ➖ `:heavy_minus_sign:` (tipo `build`) |
| Atualizar submódulo | ⬆️ `:arrow_up:` |
| Reverter mudanças | 💥 `:boom:` (tipo `fix`) |
| Tag de versão | 🔖 `:bookmark:` |
| Teste de aprovação | ✔️ `:heavy_check_mark:` (tipo `test`) |

## Exemplos

- `:tada: Commit inicial`
- `:books: docs: Atualização do README`
- `:bug: fix: Loop infinito na linha 50`
- `:sparkles: feat: Página de login`
- `:lipstick: feat: Estilização CSS do formulário`
- `:recycle: refactor: Passando para arrow functions`
- `:broom: cleanup: Eliminando código comentado na validação de formulário`

Referência completa: [Conventional Commits](https://www.conventionalcommits.org/pt-br).
