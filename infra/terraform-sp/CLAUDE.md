# Infra do release em São Paulo (Terraform) — regras sempre válidas

Contexto: [`../../docs/infra-sa-east-1.md`](../../docs/infra-sa-east-1.md). Issue #458.

## Nunca

- `terraform apply` sem `-target` explícito e sem OK escrito do Ícaro, nesta conversa, para aquele alvo. O CI só faz `plan`.
- Alterar `infra/terraform/` (a Virgínia) ou escrever no state dele ou no do stack antigo (`aws-fargate-v2`): este root é **separado**, com state próprio.
- Apagar ou destruir recurso da Virgínia: a Virgínia só sai depois que São Paulo estiver validada (blue/green).
- Colocar valor real de segredo no `.tf` ou no state; o valor entra por `aws secretsmanager put-secret-value`.

## Sempre

- `terraform fmt -check`, `terraform validate` e `terraform plan -lock=false` antes de abrir PR; o resumo do plan vai no PR (contagem, sem valores sensíveis).
- Nomes com o sufixo `-sp` para não colidir com os recursos da Virgínia.
- `nat_count` tem padrão 1 e `tasks_in_public_subnets` padrão false: o NAT (EIP 18.228.145.80) foi criado em 2026-11-11 e as tasks ficam em subnet privada. O `plan` sem `-var` deve dar `No changes`; desligar o NAT ou voltar as tasks para a subnet pública é mudança com OK escrito.
