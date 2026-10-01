# Interface VPC Endpoint pro Bedrock (issue #141) — autorizado mesmo com
# custo fixo (~US$14,60/mês, 2 AZs) superando a economia esperada no NAT
# Gateway pro volume de tráfego atual (decisão de arquitetura, não custo).
# Tráfego das tasks pro Bedrock passa a ficar 100% dentro da VPC, sem sair
# pela rota pública (NAT → Internet Gateway).
resource "aws_security_group" "bedrock_endpoint" {
  name        = "${var.project}-bedrock-endpoint"
  description = "Interface VPC Endpoint do Bedrock - so aceita 443 das tasks da app"
  vpc_id      = data.terraform_remote_state.old.outputs.vpc_id

  ingress {
    description     = "HTTPS das tasks da app"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-bedrock-endpoint" }
}

resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = data.terraform_remote_state.old.outputs.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = data.terraform_remote_state.old.outputs.private_subnet_ids
  security_group_ids  = [aws_security_group.bedrock_endpoint.id]
  private_dns_enabled = true

  tags = { Name = "${var.project}-bedrock-runtime" }
}
