<!-- claude-projects-attribution: {"github_login":"icaroalbar"} -->
_Requested by **Icaro**_

Refs #458 (não fecha)

## Por quê
Com o banco ligado (DATABASE_URL corrigido em 2026-11-11), a task de São Paulo passou a indexar os fluxos por embeddings na subida e recebeu **70 `AccessDeniedException` em ~2 min** (nível error, `Error raised by inference endpoint`). A app usa `amazon.titan-embed-text-v2:0` (`src/maria/shared/embeddings_fluxos.py:49`, `BEDROCK_EMBEDDING_MODEL_ID`, 1024 dimensões) e a task role só autorizava `foundation-model/qwen.*` (#460). Só há duas chamadas ao Bedrock no código: o chat (`_estruturado.py:103`) e os embeddings. O Titan Embed Text v2 está disponível on-demand em `sa-east-1`. Causa por inferência; não confirmada por simulação de política.

## O que muda
- `infra/terraform-sp/variables.tf`: `bedrock_model_arns` ganha `arn:aws:bedrock:sa-east-1::foundation-model/amazon.titan-embed-text-v2:0`.
- `docs/infra-sa-east-1.md`: nota dos embeddings.

## Como testar
- `terraform fmt -check` e `terraform validate` (`-backend=false`): ok.
- `terraform plan` (somente leitura, state aplicado; com `-var nat_count=1 -var tasks_in_public_subnets=false` enquanto o #467 não for mesclado): **0 a criar, 1 a mudar, 0 a destruir** = só `aws_iam_role_policy.task` (o `Resource` do Bedrock vira lista com o `qwen.*` e o Titan).
- Apply só com OK escrito do Icaro. A role vale no próximo request, sem reiniciar a task. Depois, conferir nos logs que o `AccessDeniedException` some.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
