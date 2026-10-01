# Segundo ambiente ("release") pra testar via WhatsApp com o Verde de
# produção, em paralelo ao ambiente atual (que aponta pro Verde de
# homologação — ver secrets.tf, VERDE_API_URL de lá). Decisão 2026-09-04:
# reaproveita cluster/IAM/security groups/ALB/ECR (já compartilhados por
# projeto, sem sufixo de ambiente — variable "environment" em variables.tf
# já previa isso, só nunca tinha sido usado) — só duplica o que precisa
# ficar ISOLADO de verdade: secret, task/service ECS, target group,
# distribuição CloudFront própria, banco Postgres próprio.
#
# Roteamento: SEM domínio próprio, então não dá pra rotear por path (o app
# não tem prefixo /release nas rotas) nem por subdomínio de verdade. Em vez
# disso, a distribuição CloudFront deste ambiente injeta um header
# (X-Maria-Env: release) em toda requisição que manda pro ALB — o ALB tem
# uma regra de listener que olha esse header pra decidir qual target group.
# O ALB continua sendo o MESMO dos dois ambientes (não expõe rota nova pra
# internet, só mais um listener rule).

# ── Secret ───────────────────────────────────────────────────────────────
# Mesmo padrão de secrets.tf: valores reais preenchidos FORA do Terraform
# (aws secretsmanager put-secret-value). VERDE_* começam iguais ao ambiente
# atual (mesma credencial de homolog) até a credencial de produção do Verde
# chegar — troca só nesse secret, sem mexer no outro ambiente.
resource "aws_secretsmanager_secret" "app_release" {
  name        = "${var.project}-release/app"
  description = "Tokens/segredos do maria-langgraph-pp — ambiente release (Verde produção, quando a credencial chegar)."
}

resource "aws_secretsmanager_secret_version" "app_release" {
  secret_id = aws_secretsmanager_secret.app_release.id
  secret_string = jsonencode({
    VERDE_API_URL     = "PREENCHER"
    VERDE_JWT_TOKEN   = "PREENCHER"
    VERDE_CLIENT_ID   = "PREENCHER"
    DATABASE_URL      = "PREENCHER" # aponta pro MESMO RDS Proxy, banco maria_langgraph_pp_release (isolado do outro ambiente)
    LANGSMITH_API_KEY = "PREENCHER"
    LANGSMITH_PROJECT = "maria-langgraph-pp-release"
    API_KEY           = "PREENCHER" # chave própria deste ambiente, diferente da do outro
    # Issue #198 — bridge WhatsApp (Meta Cloud API), testado só no ambiente
    # release por enquanto (número de teste da Meta, sem credencial própria
    # ainda). WHATSAPP_VERIFY_TOKEN é segredo NOSSO (não vem da Meta) —
    # mesmo valor cadastrado na configuração do webhook no app da Meta.
    WHATSAPP_API_URL         = "PREENCHER"
    WHATSAPP_PHONE_NUMBER_ID = "PREENCHER"
    WHATSAPP_ACCESS_TOKEN    = "PREENCHER"
    WHATSAPP_VERIFY_TOKEN    = "PREENCHER"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ── ECS (task + service) ────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "api_release" {
  name              = "/ecs/${var.project}-release/api"
  retention_in_days = 30
}

resource "aws_ecs_task_definition" "api_release" {
  family                   = "${var.project}-release-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${aws_ecr_repository.api.repository_url}:${var.image_tag_release}"
    essential    = true
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    environment = [
      { name = "PORT", value = tostring(var.container_port) },
      { name = "AWS_REGION", value = var.aws_region },
      # Achado ao vivo 2026-09-28/30: o modelo default do código
      # (anthropic.claude-3-haiku-20240307-v1:0) foi desativado pela AWS
      # (ResourceNotFoundException, "reached the end of its life") — sem
      # isso, TODA classificação do orquestrador falha silenciosamente e
      # cai em handoff_humano. Não é segredo (é só um id de modelo),
      # environment var normal, não secrets. Profile de inferência
      # cross-region, não o model id direto (confirmado via
      # `aws bedrock get-foundation-model`/`list-inference-profiles`).
      { name = "BEDROCK_MODEL_ID", value = "us.anthropic.claude-haiku-4-5-20251001-v1:0" },
    ]
    secrets = [
      for k in [
        "VERDE_API_URL", "VERDE_JWT_TOKEN", "VERDE_CLIENT_ID", "DATABASE_URL", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "API_KEY",
        "WHATSAPP_API_URL", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN",
      ] :
      { name = k, valueFrom = "${aws_secretsmanager_secret.app_release.arn}:${k}::" }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api_release.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_lb_target_group" "api_release" {
  name        = "${var.project}-api-release"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = data.terraform_remote_state.old.outputs.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_ecs_service" "api_release" {
  name            = "api-release"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api_release.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.terraform_remote_state.old.outputs.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api_release.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http, aws_security_group_rule.proxy_from_tasks]

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ── Roteamento: regra no MESMO listener do ALB, por header ────────────────
resource "aws_lb_listener_rule" "release" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_release.arn
  }

  condition {
    http_header {
      http_header_name = "X-Maria-Env"
      values           = ["release"]
    }
  }
}

# ── CloudFront própria (injeta o header acima em toda request) ────────────
resource "aws_cloudfront_distribution" "api_release" {
  enabled     = true
  comment     = "HTTPS pro maria-langgraph-pp (Tykhe) — ambiente release"
  price_class = "PriceClass_100"

  origin {
    domain_name = aws_lb.main.dns_name
    origin_id   = "alb-api-release"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
    custom_header {
      name  = "X-Maria-Env"
      value = "release"
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb-api-release"
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

output "api_https_url_release" {
  value       = "https://${aws_cloudfront_distribution.api_release.domain_name}"
  description = "URL HTTPS do ambiente release — passar pra Tykhe quando for testar contra Verde produção."
}
