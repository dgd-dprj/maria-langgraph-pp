# Security groups. Nenhuma regra de entrada aberta à internet: tasks (sem entrada) → Proxy (5432) → RDS (5432).
# O SG das tasks fica definido aqui (as tasks entram na etapa seguinte) para o Proxy e o endpoint do Bedrock aceitá-lo.
resource "aws_security_group" "tasks" {
  name        = "${var.project}-${var.environment}-sp-tasks"
  description = "Tasks ECS do release em Sao Paulo"
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-${var.environment}-sp-tasks" }
}

resource "aws_security_group" "rds_proxy" {
  name        = "${var.project}-${var.environment}-sp-rds-proxy"
  description = "RDS Proxy - aceita conexoes das tasks Fargate"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres das tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-${var.environment}-sp-rds-proxy" }
}

resource "aws_security_group" "rds" {
  name        = "${var.project}-${var.environment}-sp-rds"
  description = "RDS - acesso so via RDS Proxy"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres do Proxy"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.rds_proxy.id]
  }

  tags = { Name = "${var.project}-${var.environment}-sp-rds" }
}
