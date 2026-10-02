# Permite o GitHub Actions deste repo assumir um IAM role SEM chave fixa
# guardada como secret — token OIDC de curta duração, emitido pelo próprio
# GitHub a cada run. Decisão 2026-09-04, junto da esteira CI/CD que separa
# deploy de produção (push em main) e homolog/release (push em develop).
#
# Escopo do role é restrito ao repo + branches main/develop — só essas 2
# branches disparam deploy (ver .github/workflows/deploy-*.yml), PR de
# feature branch nunca tem permissão de assumir o role.

data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

data "aws_iam_policy_document" "github_actions_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      # GitHub inclui IDs numéricos imutáveis no sub (owner@id/repo@id), não
      # só o nome — achado ao vivo 2026-09-04 decodificando o token real (ver
      # passo de debug removido de deploy-release.yml). O id do REPO não muda
      # se o repo for renomeado OU transferido pra outro owner — só o id do
      # OWNER muda numa transferência. Repo transferido 2026-10-02 de
      # icaroeduardo-lab (id 276099947) pra org dgd-dprj (id 337067883);
      # repo@1347683221 é o mesmo de sempre, confirmado via
      # `gh api repos/dgd-dprj/maria-langgraph-pp --jq .id` depois do transfer.
      values = [
        "repo:dgd-dprj@337067883/maria-langgraph-pp@1347683221:ref:refs/heads/main",
        "repo:dgd-dprj@337067883/maria-langgraph-pp@1347683221:ref:refs/heads/develop",
      ]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json
}

# Só o necessário pro pipeline: build+push de imagem no ECR deste projeto e
# forçar novo deployment nos 2 services ECS (api / api-release). NÃO inclui
# permissão de Terraform/infra — mudança de infra continua manual (ver
# comentário grande em release.tf sobre a mesma decisão pro banco/secret).
data "aws_iam_policy_document" "github_actions_deploy" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
    ]
    resources = [aws_ecr_repository.api.arn]
  }
  statement {
    sid = "EcsDeploy"
    actions = [
      "ecs:UpdateService",
      "ecs:DescribeServices",
    ]
    resources = [
      aws_ecs_service.api.id,
      aws_ecs_service.api_release.id,
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name   = "deploy"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_deploy.json
}

# Issue #113 — leitura dos secrets de app, pro workflow agendado
# (.github/workflows/verificar-token-verde.yml) checar a validade do
# VERDE_JWT_TOKEN sem precisar de credencial fixa nova.
#
# Issue #122 — ampliado pros 2 secrets do Grafana: terraform-drift.yml
# roda `terraform plan` de verdade, que precisa REFRESH de todo
# aws_secretsmanager_secret_version que este state gerencia (mesmo com
# `lifecycle.ignore_changes = [secret_string]` — o refresh lê o valor
# atual ANTES de decidir ignorar o diff). ReadOnlyAccess exclui
# secretsmanager:GetSecretValue de propósito (dado sensível) — sem esse
# statement, terraform-drift.yml falha com AccessDenied nos 2 secrets
# do Grafana (achado ao vivo 2026-09-21). Continua restrito aos 4
# secrets deste projeto, nunca um wildcard pra conta toda.
data "aws_iam_policy_document" "github_actions_read_app_secrets" {
  statement {
    sid     = "ReadAppSecretsForTokenCheckAndTerraformRefresh"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.app.arn,
      aws_secretsmanager_secret.app_release.arn,
      aws_secretsmanager_secret.grafana.arn,
      aws_secretsmanager_secret.grafana_postgres_readonly.arn,
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_read_app_secrets" {
  name   = "read-app-secrets-token-check"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_read_app_secrets.json
}

# Issue #187 — verificar-token-verde.yml passou de só ALERTAR pra também
# RENOVAR o VERDE_JWT_TOKEN de verdade (POST /autenticacao/token/refresh na
# Verde, grava o token novo aqui). Restrito aos 2 secrets de app (nunca
# Grafana/outros) — mesmo racional de least-privilege do statement de
# leitura acima, escopo mínimo só pro que esse workflow específico precisa
# escrever.
data "aws_iam_policy_document" "github_actions_write_verde_token" {
  statement {
    sid     = "WriteVerdeTokenSecret"
    actions = ["secretsmanager:PutSecretValue"]
    resources = [
      aws_secretsmanager_secret.app.arn,
      aws_secretsmanager_secret.app_release.arn,
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_write_verde_token" {
  name   = "write-verde-token-secret"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_write_verde_token.json
}

# Issue #122 — ReadOnlyAccess (gerenciada pela AWS) pro workflow de drift
# (.github/workflows/terraform-drift.yml) rodar `terraform plan` de
# verdade — precisa descrever recursos de várias APIs (IAM, ECS, RDS,
# CloudFront, etc.), mas SÓ leitura. A policy de deploy acima continua a
# única fonte de permissão de ESCRITA desta role — isso aqui nunca dá
# ecs:UpdateService/iam:PutRolePolicy/etc, só Get/Describe/List.
resource "aws_iam_role_policy_attachment" "github_actions_read_only" {
  role       = aws_iam_role.github_actions.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# Achado ao vivo (2026-09-21) rodando terraform-drift.yml pela 1ª vez:
# ReadOnlyAccess não basta pro `terraform plan` sozinho — o backend S3
# trava o state via DynamoDB (dynamodb_table em backend.tf) antes de
# QUALQUER operação, mesmo plan sem apply, e GetItem/PutItem/DeleteItem
# nessa tabela conta como "escrita" pra AWS, fora do ReadOnlyAccess.
# Statement propositalmente restrito à ÚNICA tabela de lock (não ao S3
# do state em si, que seria escrita de verdade) — na pior hipótese essa
# role só consegue travar/destravar um lock, nunca alterar o conteúdo
# real do .tfstate. Nome da tabela é o mesmo literal já usado em
# backend.tf (esse lock não é gerenciado por nenhum Terraform — recurso
# de bootstrap do stack antigo).
data "aws_iam_policy_document" "github_actions_terraform_lock" {
  statement {
    sid       = "TerraformStateLock"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = ["arn:aws:dynamodb:us-east-1:185327115563:table/maria-tf-lock"]
  }
}

resource "aws_iam_role_policy" "github_actions_terraform_lock" {
  name   = "terraform-state-lock"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_terraform_lock.json
}

output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions.arn
  description = "Role ARN pra configurar como variável AWS_ROLE_ARN no GitHub (Settings → Secrets and variables → Actions)."
}
