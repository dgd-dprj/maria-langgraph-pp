# Infra da Maria em São Paulo (`sa-east-1`) — homologação primeiro

Issue #458. A infraestrutura da Maria está na Virgínia (`us-east-1`). Esta página descreve o root Terraform **novo e separado** (`infra/terraform-sp/`) que cria o ambiente de homologação (`release`) em São Paulo, e a regra de como migrar.

## Por que um root novo

O Terraform atual (`infra/terraform/`) divide cluster, ALB, roles, security groups e ECR entre produção e release, e lê a VPC e o RDS do stack antigo (`aws-fargate-v2`). Mudar só `aws_region` nele faria o `plan` procurar o state antigo em São Paulo e proporia substituir a produção. Por isso o ambiente de São Paulo é um root à parte, com state próprio, que **nunca** toca nos recursos nem nos states da Virgínia.

| | Virgínia (blue) | São Paulo (green) |
|---|---|---|
| Código | `infra/terraform/` | `infra/terraform-sp/` |
| State | `maria-langgraph-pp/terraform.tfstate` | `maria-langgraph-pp/sa-east-1-release/terraform.tfstate` |
| Bucket e lock | `maria-tfstate-185327115563`, `maria-tf-lock` (ambos em `us-east-1`) | os mesmos (o state pode ficar numa região e gerir recursos de outra) |
| Região dos recursos | `us-east-1` | `sa-east-1` |
| Nomes | sem sufixo | com `-sp` |

## O que o root novo cria (etapa 1: rede e base)

VPC (`10.30.0.0/16`, variável `vpc_cidr`; outro CIDR que o da Virgínia, `10.20.0.0/16`, para permitir peering entre as regiões durante a migração), 2 subnets públicas e 2 privadas em 2 AZs, IGW, NAT (variável `nat_count`, 0 ou 1), route tables, grupo de subnets do banco, security groups (tasks, Proxy e RDS: 5432 só da tasks para o Proxy e só do Proxy para o RDS; nenhuma entrada aberta à internet) e o endpoint de VPC do `bedrock-runtime` (443 só das tasks). Não cria IAM (é global), RDS, Proxy, ECS nem ALB: vêm nas próximas etapas.

## Como usar

```bash
cd infra/terraform-sp
terraform init
terraform fmt -check
terraform validate
terraform plan -lock=false     # só leitura; o resumo vai no PR
```

**`apply` é sempre manual, com `-target` explícito e só com OK escrito do Ícaro, na conversa, para aquele alvo.** O CI só faz `plan`. Depois do apply, fica a lista exata do que foi criado, para o PR e para a issue.

## Blue/green do release

1. **Rede e base** em `sa-east-1` (este root).
2. **Banco:** restaurar o RDS a partir da cópia do snapshot (`maria-chat-prod-pg-copia-sp-20261111`, criptografada com `alias/aws/rds`), criar o Proxy e os segredos (valores à mão, por `put-secret-value`) e **apagar do RDS novo** os bancos de produção (o release só usa `maria_langgraph_pp_release`). O snapshot contém todos os bancos da instância: é dado de produção.
3. **Aplicação:** ECR na região nova, ECS, ALB e target group; teste de ponta a ponta pelo endereço direto do ALB novo.
4. **Bedrock:** `AWS_REGION` e `BEDROCK_MODEL_ID` na região nova. O Haiku 4.5 só roda em São Paulo por perfil `global.` (processa em qualquer região); para manter a inferência no Brasil, só os modelos de outros fornecedores (por exemplo, Qwen3 VL 235B), com qualidade menor na suíte da Maria. A escolha é decisão à parte.
5. **Corte:** trocar a origem do CloudFront do release para o ALB novo. O domínio não muda, então a Tykhe não muda; voltar a origem desfaz o corte.
6. **Observar** alguns dias e só então desligar o release da Virgínia, com um snapshot final.

Fora do escopo desta etapa: produção, Lambda `maria-email-nudecon`, DynamoDB de idempotência e SES (a função é única e funciona a partir de `sa-east-1`).
