# Produção em São Paulo (#509): service, task, segredos e roles da produção, ao lado do release, no mesmo cluster, ALB e VPC.
# Nada aqui troca tráfego: o service nasce com 0 tasks (`prod_desired_count`), a regra do ALB só pega quem manda
# `X-Maria-Env: prod`, e a Tykhe continua na Virgínia até o corte (troca da origem do CloudFront, em outra etapa).
# Segredos e roles da produção NÃO são os do release; IAM é global, por isso os nomes levam `-sp`.

variable "prod_desired_count" {
  type        = number
  default     = 0
  description = "Tasks do service de produção. Começa em 0: os segredos de produção só são preenchidos depois do apply, e a imagem `latest` precisa estar no ECR de São Paulo."
}

variable "prod_image_tag" {
  type        = string
  default     = "latest"
  description = "Tag da imagem de produção no ECR de São Paulo (a mesma do prod da Virgínia, `image_tag` em infra/terraform/variables.tf)."
}

locals {
  prod = "${var.project}-prod"
}

# ── Segredos (valores preenchidos fora do Terraform, por put-secret-value) ────────────────────────────────────────────
# Mesmos nomes dos da Virgínia (segredo é regional). As 7 chaves de app e as 2 do e-mail são as que a task de produção
# da Virgínia já lê (infra/terraform/ecs.tf:47-51); o WhatsApp não é passado à produção por enquanto.
resource "aws_secretsmanager_secret" "app_prod" {
  name        = "${local.prod}/app"
  description = "Tokens/segredos do maria-langgraph-pp, produção em Sao Paulo (valores preenchidos fora do Terraform)."
}

resource "aws_secretsmanager_secret_version" "app_prod" {
  secret_id = aws_secretsmanager_secret.app_prod.id
  secret_string = jsonencode({
    VERDE_API_URL     = "PREENCHER"
    VERDE_JWT_TOKEN   = "PREENCHER"
    VERDE_CLIENT_ID   = "PREENCHER"
    DATABASE_URL      = "PREENCHER" # host = endpoint do RDS Proxy de Sao Paulo, banco maria_langgraph_pp
    LANGSMITH_API_KEY = "PREENCHER"
    LANGSMITH_PROJECT = "maria-langgraph-pp"
    API_KEY           = "PREENCHER" # chave que a Tykhe manda em Authorization: Bearer <API_KEY>
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "email_nudecon_prod" {
  name        = "${local.prod}/email-nudecon"
  description = "URL e chave da funcao Lambda de e-mail do NUDECON (a Lambda continua em us-east-1), producao em Sao Paulo."
}

resource "aws_secretsmanager_secret_version" "email_nudecon_prod" {
  secret_id = aws_secretsmanager_secret.email_nudecon_prod.id
  secret_string = jsonencode({
    EMAIL_NUDECON_URL     = "PREENCHER"
    EMAIL_NUDECON_API_KEY = "PREENCHER"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ── Roles ────────────────────────────────────────────────────────────────────────────────────────────────────────────
resource "aws_iam_role" "execution_prod" {
  name               = "${local.prod}-sp-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_prod" {
  role       = aws_iam_role.execution_prod.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "exec_secrets_prod" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.app_prod.arn,
      aws_secretsmanager_secret.email_nudecon_prod.arn,
    ]
  }
}

resource "aws_iam_role_policy" "exec_secrets_prod" {
  name   = "read-secrets"
  role   = aws_iam_role.execution_prod.id
  policy = data.aws_iam_policy_document.exec_secrets_prod.json
}

# Task role própria da produção, com o mesmo escopo de Bedrock do release (iam.tf: só os modelos de var.bedrock_model_arns).
resource "aws_iam_role" "task_prod" {
  name               = "${local.prod}-sp-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task_prod" {
  name   = "app-permissions"
  role   = aws_iam_role.task_prod.id
  policy = data.aws_iam_policy_document.task.json
}

# ── Task definition e service ────────────────────────────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "api_prod" {
  name              = "/ecs/${local.prod}-sp/api"
  retention_in_days = 30
}

resource "aws_ecs_task_definition" "api_prod" {
  family                   = "${local.prod}-sp-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.app_cpu
  memory                   = var.app_memory
  execution_role_arn       = aws_iam_role.execution_prod.arn
  task_role_arn            = aws_iam_role.task_prod.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${aws_ecr_repository.api.repository_url}:${var.prod_image_tag}"
    essential    = true
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    environment = [
      { name = "PORT", value = tostring(var.container_port) },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "BEDROCK_MODEL_ID", value = var.bedrock_model_id },
      # Fixo em "producao" (e não derivado do environment deste stack, que é "release"): só "release" exato liga os
      # fluxos em teste (maria/fluxos/__init__.py), e a produção nunca pode herdá-lo. Um teste confere este valor.
      { name = "MARIA_AMBIENTE", value = "producao" },
    ]
    secrets = concat([
      for k in ["VERDE_API_URL", "VERDE_JWT_TOKEN", "VERDE_CLIENT_ID", "DATABASE_URL", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "API_KEY"] :
      { name = k, valueFrom = "${aws_secretsmanager_secret.app_prod.arn}:${k}::" }
      ], [
      for k in ["EMAIL_NUDECON_URL", "EMAIL_NUDECON_API_KEY"] :
      { name = k, valueFrom = "${aws_secretsmanager_secret.email_nudecon_prod.arn}:${k}::" }
    ])
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api_prod.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_lb_target_group" "api_prod" {
  name        = "${local.prod}-sp"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # Fargate awsvpc

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# O listener continua mandando tudo ao release (padrão); a produção só entra com o cabeçalho `X-Maria-Env: prod`,
# que a distribuição do CloudFront de produção vai mandar na origem no corte. Mesmo desenho que a Virgínia já usou.
resource "aws_lb_listener_rule" "api_prod" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_prod.arn
  }

  condition {
    http_header {
      http_header_name = "X-Maria-Env"
      values           = ["prod"]
    }
  }
}

resource "aws_ecs_service" "api_prod" {
  name            = "api-prod-sp"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api_prod.arn
  desired_count   = var.prod_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.tasks_in_public_subnets ? aws_subnet.public[*].id : aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = var.tasks_in_public_subnets
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api_prod.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener_rule.api_prod]

  lifecycle {
    ignore_changes = [desired_count]
  }
}

output "ecs_service_name_prod" {
  value       = aws_ecs_service.api_prod.name
  description = "Service ECS da produção em São Paulo."
}

output "secret_app_prod_arn" {
  value       = aws_secretsmanager_secret.app_prod.arn
  description = "Segredo da aplicação (produção, São Paulo): o Ícaro preenche por put-secret-value."
}

output "secret_email_nudecon_prod_arn" {
  value       = aws_secretsmanager_secret.email_nudecon_prod.arn
  description = "Segredo do e-mail do NUDECON (produção, São Paulo)."
}

# ── CloudFront da produção (#509) ────────────────────────────────────────────────────────────────────────────────────
# Distribuição NOVA, só da produção em São Paulo (a do release, em cloudfront.tf, não muda). A origem é o ALB de São Paulo e
# manda `X-Maria-Env: prod`, que a regra de prioridade 10 do ALB usa para chegar ao target group de produção. O corte é
# trocar, na Tykhe, a URL da produção da Virgínia por a desta distribuição (`api_https_url_prod_sp`); nada na Virgínia muda.
resource "aws_cloudfront_distribution" "api_prod_sp" {
  enabled     = true
  comment     = "HTTPS pro maria-langgraph-pp, producao em Sao Paulo (Tykhe)"
  price_class = "PriceClass_100"

  origin {
    domain_name = aws_lb.main.dns_name
    origin_id   = "alb-api-prod-sp"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
    custom_header {
      name  = "X-Maria-Env"
      value = "prod"
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb-api-prod-sp"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewer
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

output "api_https_url_prod_sp" {
  value       = "https://${aws_cloudfront_distribution.api_prod_sp.domain_name}"
  description = "URL HTTPS da produção em São Paulo: é a que vai na Tykhe no corte."
}
