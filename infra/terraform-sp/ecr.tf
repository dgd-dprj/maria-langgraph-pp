# Repositório de imagens do release em São Paulo (ECR é regional: o da Virgínia não vale aqui). Começa vazio.
resource "aws_ecr_repository" "api" {
  name                 = var.project
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Política de São Paulo (#384, #544): latest e release nunca expiram; as 30 imagens sha- mais novas e as 10 sem tag mais novas ficam para rollback.
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy     = file("${path.module}/ecr-lifecycle.json")
}
