# Grupo de subnets do banco (as 2 privadas, em 2 AZs). O RDS e o Proxy entram numa etapa seguinte.
resource "aws_db_subnet_group" "main" {
  name        = "${var.project}-${var.environment}-sp-db"
  description = "Subnets privadas do banco do release em Sao Paulo"
  subnet_ids  = aws_subnet.private[*].id

  tags = { Name = "${var.project}-${var.environment}-sp-db" }
}
