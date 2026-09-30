resource "aws_ecs_cluster" "main" {
  name = var.project
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}/api"
  retention_in_days = 30
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential    = true
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    environment = [
      { name = "PORT", value = tostring(var.container_port) },
      { name = "AWS_REGION", value = var.aws_region },
      # Issue #200 — achado ao vivo 2026-09-30: o modelo default do código
      # (anthropic.claude-3-haiku-20240307-v1:0) foi desativado pela AWS
      # (ResourceNotFoundException, "reached the end of its life"). Sem
      # isso, TODA chamada de ia/ falha e degrada silenciosamente pro
      # fallback sem IA (orquestrador cai em handoff_humano sempre). Não é
      # segredo (só um id de modelo), environment var normal. Profile de
      # inferência cross-region, não o model id direto (confirmado via
      # `aws bedrock get-foundation-model`/`list-inference-profiles`) —
      # mesmo fix já validado em release.tf e local.
      { name = "BEDROCK_MODEL_ID", value = "us.anthropic.claude-haiku-4-5-20251001-v1:0" },
    ]
    secrets = [
      for k in ["VERDE_API_URL", "VERDE_JWT_TOKEN", "VERDE_CLIENT_ID", "DATABASE_URL", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "API_KEY"] :
      { name = k, valueFrom = "${aws_secretsmanager_secret.app.arn}:${k}::" }
    ]
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
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.terraform_remote_state.old.outputs.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http, aws_security_group_rule.proxy_from_tasks]

  lifecycle {
    ignore_changes = [desired_count]
  }
}
