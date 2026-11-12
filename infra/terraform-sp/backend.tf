# State PRÓPRIO deste stack, no mesmo bucket e lock dos outros stacks (que continuam em us-east-1: o state pode ficar
# numa região e gerir recursos de outra). Key diferente: nunca lê nem escreve o state de infra/terraform nem o do stack antigo.
terraform {
  backend "s3" {
    bucket         = "maria-tfstate-185327115563"
    key            = "maria-langgraph-pp/sa-east-1-release/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "maria-tf-lock"
    encrypt        = true
  }
}
