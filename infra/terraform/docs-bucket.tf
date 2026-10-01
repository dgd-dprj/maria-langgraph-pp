# Bucket só pra imagens usadas na documentação (docs/*.md, README) — GitHub
# renderiza <img src="https://...">  direto, precisa de leitura pública sem
# autenticação. Separado do bucket de tfstate (que é privado de propósito) —
# nunca reaproveitar aquele bucket pra isso.
#
# Público só pra LEITURA de objeto (s3:GetObject), nunca listagem
# (ListBucket) nem escrita — quem sabe a URL exata do arquivo consegue ver a
# imagem, mas não navega o bucket nem sobrescreve nada sem credencial AWS.
resource "aws_s3_bucket" "docs" {
  bucket = "${var.project}-docs-185327115563"
}

resource "aws_s3_bucket_public_access_block" "docs" {
  bucket = aws_s3_bucket.docs.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "docs_public_read" {
  bucket = aws_s3_bucket.docs.id
  # depends_on explícito: a policy só pode ser aplicada DEPOIS do public
  # access block permitir bucket policy pública (block_public_policy=false)
  # — sem essa ordem, o apply falha.
  depends_on = [aws_s3_bucket_public_access_block.docs]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadOnly"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.docs.arn}/*"
    }]
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

output "docs_bucket_name" {
  value       = aws_s3_bucket.docs.bucket
  description = "Bucket de imagens da documentação. Upload: aws s3 cp <arquivo> s3://<este-bucket>/<caminho> — URL pública: https://<este-bucket>.s3.amazonaws.com/<caminho>."
}
