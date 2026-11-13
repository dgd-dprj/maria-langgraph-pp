# Endpoint interface do bedrock-runtime na VPC nova: a chamada ao Bedrock sai da VPC sem passar pela internet.
# A permissão (IAM) é global e fica para a etapa da aplicação.
resource "aws_security_group" "bedrock_endpoint" {
  count       = var.bedrock_endpoint ? 1 : 0
  name        = "${var.project}-${var.environment}-sp-bedrock-endpoint"
  description = "Interface VPC Endpoint do Bedrock - so aceita 443 das tasks da app"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTPS das tasks da app"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }

  tags = { Name = "${var.project}-${var.environment}-sp-bedrock-endpoint" }
}

resource "aws_vpc_endpoint" "bedrock_runtime" {
  count               = var.bedrock_endpoint ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.bedrock_endpoint[0].id]
  private_dns_enabled = true

  tags = { Name = "${var.project}-${var.environment}-sp-bedrock-runtime" }
}
