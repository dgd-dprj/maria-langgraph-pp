# Repositório de imagens do release em São Paulo (ECR é regional: o da Virgínia não vale aqui). Começa vazio.
resource "aws_ecr_repository" "api" {
  name                 = var.project
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Mesma política da Virgínia (#384): só imagem sem tag expira; as 10 mais novas ficam para rollback.
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy     = file("${path.module}/ecr-lifecycle.json")
}
