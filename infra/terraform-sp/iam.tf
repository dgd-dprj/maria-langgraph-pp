# Task role das tasks ECS em São Paulo: só Bedrock (mesmo escopo do stack da Virgínia), mas restrita aos modelos de var.bedrock_model_arns.
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task" {
  name               = "${var.project}-${var.environment}-sp-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "task" {
  statement {
    sid = "InvocarModelosNoBedrock"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = var.bedrock_model_arns
  }

  # Na primeira chamada a um modelo, o Bedrock assina o produto no Marketplace em nome da role.
  statement {
    sid = "HabilitarModeloNaPrimeiraChamada"
    actions = [
      "aws-marketplace:ViewSubscriptions",
      "aws-marketplace:Subscribe",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:CalledViaLast"
      values   = ["bedrock.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "app-permissions"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# A Maria relê o VERDE_JWT_TOKEN deste segredo ao receber 401 (verde.py: recarregar_token_verde), sem reinício. Só leitura, só o segredo do app.
data "aws_iam_policy_document" "ler_token_verde" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
}

resource "aws_iam_role_policy" "ler_token_verde" {
  name   = "ler-token-verde"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.ler_token_verde.json
}
