# Infra (Terraform) — regras sempre válidas

Contexto completo: [`../../docs/arquitetura.md`](../../docs/arquitetura.md) (seção Infra).

## Nunca

- `terraform apply` sem `-target` explícito, a menos que o usuário peça claramente o escopo inteiro nesta sessão.
- Escrever no state antigo (`data.terraform_remote_state.old`) — este repo só **lê** VPC/subnets/RDS de lá.
- Colocar valor real de segredo (token, senha) no `.tf`/state — o `.tf` só cria o secret vazio (`"PREENCHER"`), valor real vai via `aws secretsmanager put-secret-value` fora do Terraform.

## Sempre

- Confirmar com o usuário antes de aplicar qualquer mudança que afete IAM, Secrets Manager ou algo que já esteja em produção.
- Rodar `terraform plan` antes de `apply` e mostrar o plano pro usuário revisar.
