variable "project" {
  type        = string
  default     = "maria-langgraph-pp"
  description = "Nome do projeto (tag e prefixo de recursos)."
}

variable "environment" {
  type        = string
  default     = "release"
  description = "Ambiente deste stack. Só o release migra primeiro (blue/green)."
}

variable "aws_region" {
  type        = string
  default     = "sa-east-1"
  description = "Região AWS deste stack (São Paulo)."
}

variable "vpc_cidr" {
  type        = string
  default     = "10.30.0.0/16"
  description = "CIDR da VPC nova. Diferente do 10.20.0.0/16 da Virgínia, para permitir peering entre as regiões durante a migração."
}

variable "azs" {
  type        = list(string)
  default     = ["sa-east-1a", "sa-east-1c"]
  description = "Duas zonas de disponibilidade (o RDS e o Proxy exigem subnets em 2 AZs)."
}

variable "nat_count" {
  type        = number
  default     = 1
  description = "NAT gateways (0 ou 1). 1 dá saída à internet às subnets privadas (Verde, Tykhe, Meta); 0 não cria NAT (sem custo de ~US$ 0,045/h, mas as tasks ficam sem internet)."

  validation {
    condition     = contains([0, 1], var.nat_count)
    error_message = "nat_count deve ser 0 ou 1."
  }
}

variable "bedrock_endpoint" {
  type        = bool
  default     = true
  description = "Cria o VPC endpoint interface do bedrock-runtime nesta região (a chamada ao Bedrock sai da VPC sem passar pela internet)."
}

variable "bedrock_model_arns" {
  type = list(string)
  default = [
    "arn:aws:bedrock:sa-east-1::foundation-model/qwen.*",
  ]
  description = "ARNs que a task role pode invocar no Bedrock. O padrão cobre os modelos Qwen in-region (dados no Brasil). Para um perfil global (ex.: Claude Haiku), acrescente o inference-profile e o foundation-model das outras regiões."
}
