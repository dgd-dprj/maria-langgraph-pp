# ALB do release em São Paulo. O corte do CloudFront (trocar a origem para este ALB) é uma etapa à parte.
resource "aws_security_group" "alb" {
  name        = "${var.project}-${var.environment}-sp-alb"
  description = "ALB do release em Sao Paulo"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-${var.environment}-sp-alb" }
}

# Lista de prefixos gerenciada do CloudFront (origin-facing): só o CloudFront alcança o ALB, e não a internet inteira.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  count = var.alb_only_from_cloudfront ? 1 : 0
  name  = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_vpc_security_group_ingress_rule" "alb_cloudfront" {
  count             = var.alb_only_from_cloudfront ? 1 : 0
  security_group_id = aws_security_group.alb.id
  description       = "HTTP vindo do CloudFront"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront[0].id
}

resource "aws_vpc_security_group_ingress_rule" "alb_internet" {
  count             = var.alb_only_from_cloudfront ? 0 : 1
  security_group_id = aws_security_group.alb.id
  description       = "HTTP da internet (so para teste direto pelo endereco do ALB)"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "alb_para_tasks" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Das conexoes do ALB para as tasks"
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
  referenced_security_group_id = aws_security_group.tasks.id
}

# As tasks aceitam a porta da aplicação só do ALB (o SG das tasks, da etapa 1, não tem nenhuma entrada).
resource "aws_vpc_security_group_ingress_rule" "tasks_do_alb" {
  security_group_id            = aws_security_group.tasks.id
  description                  = "Porta da aplicacao, so do ALB"
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_lb" "main" {
  name               = "${var.project}-sp-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project}-release-sp"
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

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "DNS do ALB de São Paulo (o corte do CloudFront aponta para cá)."
}
