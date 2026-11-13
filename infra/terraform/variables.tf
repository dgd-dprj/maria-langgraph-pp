variable "project" {
  type        = string
  default     = "maria-langgraph-pp"
  description = "Nome do projeto (tag e prefixo de recursos)."
}

variable "environment" {
  type        = string
  default     = "prod"
  description = "Ambiente (prod | staging)."
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "Região AWS — mesma do stack antigo (mesma VPC/RDS)."
}

variable "container_port" {
  type        = number
  default     = 3001
  description = "Porta do container Fastify."
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Tag da imagem no ECR — ambiente prod (deploy em push pra main)."
}

variable "image_tag_release" {
  type        = string
  default     = "release"
  description = "Tag da imagem no ECR — ambiente release (deploy em push pra develop). Separada de image_tag pra um deploy não disparar o outro ambiente à toa."
}

variable "api_cpu" {
  type        = number
  default     = 256
  description = "CPU da task (unidades) — 1 fluxo só, tráfego baixo."
}

variable "api_memory" {
  type        = number
  default     = 512
  description = "Memória da task (MiB)."
}

variable "desired_count" {
  type        = number
  default     = 1
  description = "Tasks desejadas — fixo por enquanto, sem autoscaling."
}

# ── Referência ao state do stack antigo (VPC/subnets/RDS compartilhados) ──────
variable "old_state_bucket" {
  type        = string
  default     = "maria-tfstate-185327115563"
  description = "Bucket S3 do state do maria-ia-back-end (fonte da VPC/RDS)."
}

variable "old_state_key" {
  type        = string
  default     = "aws-fargate-v2/terraform.tfstate"
  description = "Key do state do maria-ia-back-end."
}
