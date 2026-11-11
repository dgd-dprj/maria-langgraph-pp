# Etapa 3 (blue/green): a aplicação do release em São Paulo (ECR, ECS, ALB). O corte do CloudFront fica para depois.

variable "container_port" {
  type        = number
  default     = 3001
  description = "Porta do container."
}

variable "app_cpu" {
  type        = number
  default     = 256
  description = "CPU da task (unidades). O release usa ~1% de CPU."
}

variable "app_memory" {
  type        = number
  default     = 512
  description = "Memória da task (MiB). O release usa ~21%."
}

variable "app_desired_count" {
  type        = number
  default     = 0
  description = "Tasks do service. Começa em 0: o ECR novo está vazio, e as tasks só sobem depois do push da imagem e do preenchimento dos segredos."
}

variable "app_image_tag" {
  type        = string
  default     = "release"
  description = "Tag da imagem no ECR de São Paulo (a mesma tag do release da Virgínia)."
}

variable "bedrock_model_id" {
  type        = string
  default     = "qwen.qwen3-vl-235b-a22b"
  description = "BEDROCK_MODEL_ID da aplicação. O padrão acompanha o escopo da task role (bedrock_model_arns: modelos Qwen in-region). Trocar o modelo exige ajustar bedrock_model_arns e rodar a suíte de integração de IA: o Haiku 4.5 só roda em São Paulo por perfil global."
}

variable "tasks_in_public_subnets" {
  type        = bool
  default     = false
  description = "false: tasks nas subnets privadas, saindo pelo NAT (IP fixo de saída; exige nat_count = 1 para puxar a imagem e falar com o Verde, a Tykhe e a Meta). true: subnets públicas com IP público (sem NAT; o IP de saída muda a cada deploy; o security group continua sem entrada que não seja do ALB)."
}

variable "alb_only_from_cloudfront" {
  type        = bool
  default     = true
  description = "true: o ALB só aceita entrada vinda do CloudFront (lista de prefixos gerenciada), e não da internet inteira."
}
