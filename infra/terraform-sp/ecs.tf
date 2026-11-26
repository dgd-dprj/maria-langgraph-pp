# Cluster, roles, task e service do release em São Paulo. A task role (Bedrock) vem de iam.tf.

# #482: o ambiente da Maria sai do `environment` do stack, com a regra do código (maria/fluxos/__init__.py):
# só "release" liga os fluxos em teste (plano de saúde e multi-fluxo); qualquer outro stack roda como produção.
# Assim um stack de produção em São Paulo nunca herda o "release" por esquecimento.
locals {
  maria_ambiente = var.environment == "release" ? "release" : "producao"
}
resource "aws_ecs_cluster" "main" {
  name = "${var.project}-sp"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}-${var.environment}-sp/api"
  retention_in_days = 30
}

# IAM é global: o nome leva o sufixo -sp para não colidir com a role de execução da Virgínia.
resource "aws_iam_role" "execution" {
  name               = "${var.project}-${var.environment}-sp-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "exec_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.app.arn,
      aws_secretsmanager_secret.email_nudecon.arn,
    ]
  }
}

resource "aws_iam_role_policy" "exec_secrets" {
  name   = "read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.exec_secrets.json
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-${var.environment}-sp-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.app_cpu
  memory                   = var.app_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${aws_ecr_repository.api.repository_url}:${var.app_image_tag}"
    essential    = true
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    environment = [
      { name = "PORT", value = tostring(var.container_port) },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "BEDROCK_MODEL_ID", value = var.bedrock_model_id },
      # Só "release" exato liga os fluxos em teste (maria/fluxos/__init__.py). Vem do environment (#482).
      { name = "MARIA_AMBIENTE", value = local.maria_ambiente },
    ]
    secrets = concat([
      for k in [
        "VERDE_API_URL", "VERDE_JWT_TOKEN", "VERDE_CLIENT_ID", "DATABASE_URL", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "API_KEY",
        "WHATSAPP_API_URL", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN",
      ] :
      { name = k, valueFrom = "${aws_secretsmanager_secret.app.arn}:${k}::" }
      ], [
      for k in ["EMAIL_NUDECON_URL", "EMAIL_NUDECON_API_KEY"] :
      { name = k, valueFrom = "${aws_secretsmanager_secret.email_nudecon.arn}:${k}::" }
    ])
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "api-release-sp"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.app_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.tasks_in_public_subnets ? aws_subnet.public[*].id : aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = var.tasks_in_public_subnets
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http]

  lifecycle {
    ignore_changes = [desired_count]
  }
}

output "ecr_repository_url" {
  value       = aws_ecr_repository.api.repository_url
  description = "URL do ECR de São Paulo (docker push da imagem do release)."
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.main.name
  description = "Cluster ECS de São Paulo."
}

output "ecs_service_name" {
  value       = aws_ecs_service.api.name
  description = "Service ECS do release em São Paulo."
}
