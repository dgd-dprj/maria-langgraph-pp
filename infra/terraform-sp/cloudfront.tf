# CloudFront própria do release em São Paulo (HTTPS na frente do ALB de SP, que só aceita entrada vinda do CloudFront).
# É uma distribuição NOVA, só para testar a aplicação de SP de ponta a ponta com URL HTTPS. A distribuição do release da
# Virgínia (infra/terraform/release.tf) continua apontando para o ALB de lá; o corte é trocar a origem dela, à parte.
resource "aws_cloudfront_distribution" "api_release_sp" {
  enabled     = true
  comment     = "HTTPS pro maria-langgraph-pp, release em Sao Paulo (green, antes do corte)"
  price_class = "PriceClass_100"

  origin {
    domain_name = aws_lb.main.dns_name
    origin_id   = "alb-api-release-sp"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb-api-release-sp"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewer
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

output "api_https_url_release_sp" {
  value       = "https://${aws_cloudfront_distribution.api_release_sp.domain_name}"
  description = "URL HTTPS do release em São Paulo, para testar antes do corte."
}
