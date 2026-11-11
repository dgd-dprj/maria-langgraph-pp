# RDS Proxy do release em São Paulo (a aplicação só fala com o Proxy). O Proxy autentica com um segredo (usuário e senha do RDS)
# que o Terraform cria VAZIO: o valor entra por `put-secret-value` (manual, com OK escrito do Ícaro), nunca por .tf ou state.
# Por isso o Proxy fica atrás de `create_proxy` (padrão false): primeiro o RDS e o segredo, depois o valor, depois o Proxy.

resource "aws_secretsmanager_secret" "db" {
  name        = "maria-chat-sp/db"
  description = "Usuario e senha do RDS do release em Sao Paulo, usados pelo RDS Proxy (valor preenchido fora do Terraform)."
}

data "aws_iam_policy_document" "proxy_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["rds.amazonaws.com"]
    }
  }
}

# IAM é global: o nome leva o sufixo -sp para não colidir com a role do Proxy da Virgínia (maria-chat-prod-rds-proxy).
resource "aws_iam_role" "rds_proxy" {
  name               = "maria-chat-sp-rds-proxy"
  assume_role_policy = data.aws_iam_policy_document.proxy_assume.json
}

data "aws_iam_policy_document" "proxy_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.db.arn]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "rds_proxy" {
  name   = "read-db-secret"
  role   = aws_iam_role.rds_proxy.id
  policy = data.aws_iam_policy_document.proxy_secret.json
}

resource "aws_db_proxy" "main" {
  count                  = var.create_proxy ? 1 : 0
  name                   = "maria-chat-sp-proxy"
  engine_family          = "POSTGRESQL"
  require_tls            = true
  idle_client_timeout    = 1800
  debug_logging          = false
  role_arn               = aws_iam_role.rds_proxy.arn
  vpc_subnet_ids         = aws_subnet.private[*].id
  vpc_security_group_ids = [aws_security_group.rds_proxy.id]

  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "DISABLED"
    secret_arn  = aws_secretsmanager_secret.db.arn
  }

  tags = { Name = "maria-chat-sp-proxy" }

  depends_on = [aws_iam_role_policy.rds_proxy]
}

resource "aws_db_proxy_default_target_group" "main" {
  count         = var.create_proxy ? 1 : 0
  db_proxy_name = aws_db_proxy.main[0].name

  connection_pool_config {
    max_connections_percent      = 90
    max_idle_connections_percent = 50
    connection_borrow_timeout    = 120
  }

  lifecycle {
    replace_triggered_by = [aws_db_proxy.main[0].id]
  }
}

resource "aws_db_proxy_target" "main" {
  count                  = var.create_proxy ? 1 : 0
  db_proxy_name          = aws_db_proxy.main[0].name
  target_group_name      = aws_db_proxy_default_target_group.main[0].name
  db_instance_identifier = aws_db_instance.main.identifier

  lifecycle {
    replace_triggered_by = [aws_db_proxy.main[0].id]
  }
}

output "db_secret_arn" {
  value       = aws_secretsmanager_secret.db.arn
  description = "Segredo (vazio no Terraform) com o usuário e a senha do RDS, lido pelo Proxy."
}

output "rds_proxy_endpoint" {
  value       = var.create_proxy ? aws_db_proxy.main[0].endpoint : null
  description = "Endpoint do RDS Proxy (vai no DATABASE_URL da aplicação)."
}
