---
description: Abre o PR de release develop→main seguindo o padrão do repo (merge commit, nunca squash).
---

Abra o PR de release `develop` → `main` deste repositório. Siga [`docs/padroes-pull-request.md`](../../docs/padroes-pull-request.md) e [`docs/padroes-branch.md`](../../docs/padroes-branch.md).

Passos:

1. `git fetch origin` e confirme que `develop` está atualizada localmente.
2. Liste os commits/PRs que estão em `develop` e ainda não em `main` (`git log main..develop --oneline`, ou `gh pr list --base main --head develop` se já existir um aberto — não crie duplicado).
3. Se não houver nada novo em `develop` além de `main`, avise e não abra PR.
4. Abra o PR via `gh pr create --base main --head develop`, com:
   - Título: `:rocket: release: <resumo curto do que está entrando>` (pt-BR).
   - Corpo: lista os PRs/mudanças incluídas desde o último release (uma linha por PR, com número), sem o template de "Como testar" de PR normal (release agrupa vários já testados individualmente).
5. **Lembre no corpo do PR**: merge deste PR precisa ser **merge commit**, nunca squash — squash aqui reescreve commits já compartilhados e gera conflito no próximo release.
6. Não faça o merge sozinho — devolva o link do PR pro usuário decidir quando mergear.
