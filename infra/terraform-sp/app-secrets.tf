# Segredos do release em São Paulo, no MESMO nome dos da Virgínia (os segredos são regionais). Criados com valores
# "PREENCHER": os valores reais entram por `put-secret-value` (ou pelo console), nunca por .tf ou state.
resource "aws_secretsmanager_secret" "app" {
  name        = "${var.project}-${var.environment}/app"
  description = "Tokens/segredos do maria-langgraph-pp, ambiente release em Sao Paulo (valores preenchidos fora do Terraform)."
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    VERDE_API_URL            = "PREENCHER"
    VERDE_JWT_TOKEN          = "PREENCHER"
    VERDE_CLIENT_ID          = "PREENCHER"
    DATABASE_URL             = "PREENCHER" # host = endpoint do RDS Proxy de Sao Paulo, banco maria_langgraph_pp_release
    LANGSMITH_API_KEY        = "PREENCHER"
    LANGSMITH_PROJECT        = "maria-langgraph-pp-release"
    API_KEY                  = "PREENCHER"
    WHATSAPP_API_URL         = "PREENCHER"
    WHATSAPP_PHONE_NUMBER_ID = "PREENCHER"
    WHATSAPP_ACCESS_TOKEN    = "PREENCHER"
    WHATSAPP_VERIFY_TOKEN    = "PREENCHER"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "email_nudecon" {
  name        = "${var.project}-${var.environment}/email-nudecon"
  description = "URL e chave da funcao Lambda de e-mail do NUDECON (a Lambda continua em us-east-1), release em Sao Paulo."
}

resource "aws_secretsmanager_secret_version" "email_nudecon" {
  secret_id = aws_secretsmanager_secret.email_nudecon.id
  secret_string = jsonencode({
    EMAIL_NUDECON_URL     = "PREENCHER"
    EMAIL_NUDECON_API_KEY = "PREENCHER"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
