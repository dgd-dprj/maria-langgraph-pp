data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ── Execution role — puxa imagem, manda logs, lê o secret da app ──────────────
resource "aws_iam_role" "execution" {
  name               = "${var.project}-ecs-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "exec_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    # 2 secrets — ambiente atual (Verde homolog) + release (infra/terraform/release.tf,
    # Verde produção) — mesmo execution role compartilhado pelos 2 (ver comentário
    # grande no topo de release.tf).
    resources = [
      aws_secretsmanager_secret.app.arn,
      aws_secretsmanager_secret.app_release.arn,
      aws_secretsmanager_secret.email_nudecon.arn,
      aws_secretsmanager_secret.email_nudecon_release.arn,
    ]
  }
}

resource "aws_iam_role_policy" "exec_secrets" {
  name   = "read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.exec_secrets.json
}

# ── Task role — permissões em runtime. Só Bedrock (reescrita de pergunta via
# ChatBedrockConverse) — sem S3/SQS/Transcribe/Comprehend/Textract, este app
# não usa nada disso (diferente do task role do stack antigo).
resource "aws_iam_role" "task" {
  name               = "${var.project}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "task" {
  statement {
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "app-permissions"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}
