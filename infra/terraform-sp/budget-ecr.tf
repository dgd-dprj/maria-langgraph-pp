# Alerta de custo do ECR de São Paulo (#544): e-mail quando o gasto do mês chegar a US$ 20.
# A expiração das imagens sha- ficou adiada: decide-se quando o alerta disparar.
# Sem e-mail em var.alerta_custo_ecr_emails o orçamento não é criado.
resource "aws_budgets_budget" "ecr" {
  count = length(var.alerta_custo_ecr_emails) > 0 ? 1 : 0

  name         = "${var.project}-ecr-mensal"
  budget_type  = "COST"
  limit_amount = tostring(var.alerta_custo_ecr_limite_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "Service"
    values = ["Amazon EC2 Container Registry (ECR)"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alerta_custo_ecr_emails
  }
}
