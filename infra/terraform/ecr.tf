resource "aws_ecr_repository" "api" {
  name                 = var.project
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Issue #384 — a produção puxa a tag `latest` e o release puxa a `release`,
# as duas mutáveis: cada deploy move a tag para a imagem nova, e a anterior
# fica sem tag. A regra antiga ("10 últimas, de qualquer tag") apagou a
# `latest` depois de 10 pushes em develop, e a produção só seguiu de pé por
# já estar rodando. Agora só imagem sem tag expira (as 10 mais novas ficam
# para rollback). Política em JSON para o teste ler (tests/test_ecr.py).
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy     = file("${path.module}/ecr-lifecycle.json")
}
