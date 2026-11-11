output "vpc_id" {
  value       = aws_vpc.main.id
  description = "VPC do release em São Paulo."
}

output "private_subnet_ids" {
  value       = aws_subnet.private[*].id
  description = "Subnets privadas (tasks, RDS e Proxy)."
}

output "public_subnet_ids" {
  value       = aws_subnet.public[*].id
  description = "Subnets públicas (ALB e NAT)."
}

output "db_subnet_group_name" {
  value       = aws_db_subnet_group.main.name
  description = "Grupo de subnets do banco."
}

output "tasks_security_group_id" {
  value       = aws_security_group.tasks.id
  description = "SG das tasks ECS."
}

output "rds_proxy_security_group_id" {
  value       = aws_security_group.rds_proxy.id
  description = "SG do RDS Proxy."
}

output "rds_security_group_id" {
  value       = aws_security_group.rds.id
  description = "SG do RDS."
}
