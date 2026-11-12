# Etapa 2 (blue/green): o RDS do release em São Paulo, restaurado da CÓPIA do snapshot do RDS da Virgínia.
# Só cria uma instância NOVA; não toca no RDS da Virgínia. O snapshot contém TODOS os databases da instância de origem
# (inclusive os de produção): o release só usa `maria_langgraph_pp_release`, e os outros são apagados por ação manual
# (com OK escrito do Ícaro), nunca por Terraform. Ver docs/infra-sa-east-1.md.

variable "snapshot_identifier" {
  type        = string
  default     = "maria-chat-prod-pg-copia-sp-20261111"
  description = "Cópia, em sa-east-1, do snapshot automático do RDS da Virgínia (criptografada com alias/aws/rds). Contém TODOS os databases da instância."
}

variable "db_instance_class" {
  type        = string
  default     = "db.t3.small"
  description = "Classe do RDS. A mesma da Virgínia: o release usa ~2 GB e ~4% de CPU."
}

variable "db_multi_az" {
  type        = bool
  default     = false
  description = "Multi-AZ do RDS. A origem (Virgínia) é single-AZ; o release é de teste."
}

variable "create_proxy" {
  type        = bool
  default     = true
  description = "Cria o RDS Proxy. Padrão true: o Proxy foi aplicado em 2026-11-11 (com false, o plan proporia destruí-lo). Em um ambiente novo, só depois de o segredo de autenticação (usuário e senha do RDS) ter valor: ver docs/infra-sa-east-1.md."
}

resource "aws_db_instance" "main" {
  identifier = "maria-chat-sp-pg"

  # Restauro do snapshot: engine, usuário mestre, senha e bancos vêm dele (nada de senha no Terraform).
  snapshot_identifier = var.snapshot_identifier
  engine              = "postgres"
  engine_version      = "16.13"
  instance_class      = var.db_instance_class

  storage_type          = "gp3"
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_encrypted     = true # herda a chave do snapshot (alias/aws/rds de sa-east-1)

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = var.db_multi_az
  port                   = 5432

  parameter_group_name       = "default.postgres16"
  auto_minor_version_upgrade = true
  backup_retention_period    = 7
  backup_window              = "09:48-10:18"
  maintenance_window         = "wed:05:00-wed:05:30"
  copy_tags_to_snapshot      = false

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "maria-chat-sp-pg-final"
  apply_immediately         = false

  lifecycle {
    # O snapshot só vale no restauro; depois, mudar a variável não pode trocar o banco.
    ignore_changes = [snapshot_identifier]
  }

  tags = { Name = "maria-chat-sp-pg" }
}

output "rds_identifier" {
  value       = aws_db_instance.main.identifier
  description = "Identificador do RDS do release em São Paulo."
}

output "rds_endpoint" {
  value       = aws_db_instance.main.address
  description = "Endereço do RDS (a aplicação usa o do Proxy, não este)."
}
