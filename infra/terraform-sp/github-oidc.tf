# Permissões da role do GitHub Actions (OIDC) para o release em São Paulo (#463). A role é a mesma
# da Virgínia (IAM é global, `infra/terraform/github-oidc.tf`); aqui só entra uma política própria,
# por referência ao nome, para não depender de nenhum recurso do state da Virgínia. Aplicar por
# `-target=aws_iam_role_policy.github_actions_deploy_sp`, com OK escrito.
data "aws_iam_role" "github_actions" {
  name = "${var.project}-github-actions"
}

data "aws_iam_policy_document" "github_actions_deploy_sp" {
  statement {
    sid       = "EcrAuthSp"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrPushSp"
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
    sid       = "EcsDeploySp"
    actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = [aws_ecs_service.api.id]
  }
  # deploy-release.yml confere o token do Verde (leitura) e verificar-token-verde.yml o renova (escrita).
  statement {
    sid       = "LerSegredoDoVerdeSp"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    sid       = "GravarTokenDoVerdeSp"
    actions   = ["secretsmanager:PutSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy_sp" {
  name   = "deploy-sp"
  role   = data.aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_deploy_sp.json
}
