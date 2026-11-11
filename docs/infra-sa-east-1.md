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

VPC (`10.30.0.0/16`, variável `vpc_cidr`; outro CIDR que o da Virgínia, `10.20.0.0/16`, para permitir peering entre as regiões durante a migração), 2 subnets públicas e 2 privadas em 2 AZs, IGW, NAT (variável `nat_count`, 0 ou 1; **padrão 1**: a rede foi aplicada sem NAT em 2026-11-11 e o NAT foi criado depois, no mesmo dia), route tables, grupo de subnets do banco, security groups (tasks, Proxy e RDS: 5432 só da tasks para o Proxy e só do Proxy para o RDS; nenhuma entrada aberta à internet) e o endpoint de VPC do `bedrock-runtime` (443 só das tasks). Não cria IAM (é global), RDS, Proxy, ECS nem ALB: vêm nas próximas etapas.

## Como usar

```bash
cd infra/terraform-sp
terraform init
terraform fmt -check
terraform validate
terraform plan -lock=false     # só leitura; o resumo vai no PR
```

**`apply` é sempre manual, com `-target` explícito e só com OK escrito do Ícaro, na conversa, para aquele alvo.** O CI só faz `plan`. Depois do apply, fica a lista exata do que foi criado, para o PR e para a issue.

## NAT: ligado ou desligado

A rede foi aplicada **sem NAT** (18 recursos). As tasks precisam de saída para o Verde, a Tykhe, a Meta e a Lambda de e-mail. Decisão de 2026-11-11: **NAT ligado** (`nat_count = 1`, ~US$ 0,093/h mais US$ 0,093/GB em `sa-east-1`) e **tasks em subnet privada** (`tasks_in_public_subnets = false`, sem IP público). O NAT (`nat-02426cb2130abd20b`) foi criado com 3 recursos (EIP, NAT e a rota) e a task foi movida em seguida (1 mudança no service).

**IP fixo de saída para o Verde: `18.228.145.80`.** É o IP que o time do Verde precisa liberar, se filtrar por IP. Sem NAT (tasks em subnet pública), o IP de saída muda a cada deploy. Como os padrões das variáveis agora acompanham o state, o `plan` sem `-var` deve dar `No changes`.

## Etapa 2: o RDS e o Proxy (`rds.tf` e `proxy.tf`)

Código e `plan` só (nada aplicado). O RDS é **restaurado** da cópia do snapshot `maria-chat-prod-pg-copia-sp-20261111` (em `sa-east-1`, criptografada com `alias/aws/rds`); o Terraform **não** gerencia a senha (a do snapshot é mantida; nada de senha em `.tf`, state ou log).

| Recurso | Nome | Observação |
|---|---|---|
| RDS | `maria-chat-sp-pg` | `db.t3.small`, Postgres 16.13, gp3 20 GB (até 100), single-AZ (`db_multi_az`), privado, `deletion_protection`, backup 7 dias, janelas como na origem, `default.postgres16`, sem Performance Insights, snapshot final `maria-chat-sp-pg-final` |
| Segredo | `maria-chat-sp/db` | criado **vazio**; formato `{"username":"...","password":"..."}` |
| Role e policy do Proxy | `maria-chat-sp-rds-proxy` | lê **só** esse segredo (IAM é global; sufixo `-sp`) |
| Proxy, grupo de destino e destino | `maria-chat-sp-proxy` | atrás de `create_proxy` (padrão `true` desde que o Proxy foi aplicado): PostgreSQL, TLS obrigatório, `idle_client_timeout` 1800, subnets privadas |

`plan` (somente leitura, em cima do state aplicado da etapa 1): **4 a criar** (RDS, segredo, role e policy) com `create_proxy = false`; **7 a criar** com `create_proxy = true` (acrescenta o Proxy, o grupo de destino e o destino). 0 a alterar e 0 a destruir.

**Aplicado em 2026-11-11:** o RDS `maria-chat-sp-pg` (4 recursos, `available` em 9 min 21 s) e o Proxy (3 recursos; o alvo ficou `AVAILABLE` depois de o segredo ter a chave `username` em minúsculas: com `Username`, o Proxy dá `AUTH_FAILURE: Proxy does not have any registered credentials`). A senha mestre foi trocada (RDS → Modify) e gravada no segredo. Os bancos de produção do snapshot **continuam no RDS novo**, à espera da limpeza (com OK escrito).

### Ordem de aplicação (cada passo só com OK escrito do Ícaro, na conversa)
1. **RDS, segredo e role** (`-target` nos 4 recursos). O RDS leva alguns minutos para restaurar.
2. **O Ícaro preenche o segredo** `maria-chat-sp/db` com `put-secret-value` (usuário e senha do RDS, o mesmo par do segredo da Virgínia; nunca em texto, log ou commit).
3. **`create_proxy = true`** (agora o padrão) só depois de o segredo ter valor (o Proxy autentica com ele): plan novo e apply do plan salvo.
4. **Limpar os bancos de produção** do RDS novo e **trocar a senha mestre** (ver abaixo), também com OK escrito.

### Cuidados com o snapshot
- Ele contém **todos os bancos da instância de origem, inclusive os de produção**: tratar como dado de produção (criptografado, sem compartilhar, sem restaurar em ambiente público).
- É uma foto de **2026-11-11 09:57 UTC**. Antes do corte (blue/green), é preciso um **novo snapshot ou dump** para trazer o que entrou depois.
- O release só usa o banco `maria_langgraph_pp_release`. Os outros bancos (produção) devem ser **apagados do RDS novo** por ação manual, nunca por Terraform.
- O RDS restaurado herda a **senha mestre da Virgínia**: depois de validar, trocar a senha (e o segredo) para que o ambiente de São Paulo não compartilhe credencial com a produção.

### Como validar o banco depois de restaurar
Conectar por uma task ECS temporária ou por um ponto dentro da VPC (o RDS é privado) e conferir, sem ler dados pessoais:
- `\l`: existe `maria_langgraph_pp_release` (e quais outros precisam ser apagados);
- `\dx` no banco do release: a extensão **`vector`** (pgvector) está instalada;
- `\dn`: o schema `checkpoint_py` do LangGraph;
- contagens de linhas das tabelas `atendimentos`, `assuntos_pendentes`, `perguntas`, `assuntos_verde`, `flow_assuntos`, `fluxos_planejados` e `fluxo_embeddings` (só números, nunca o conteúdo).

### Custo (Price List de `sa-east-1`, publicado em 2026-10-29; estimativa)
RDS `db.t3.small` Postgres single-AZ: US$ 0,076/h (~US$ 55/mês); gp3: US$ 0,219/GB-mês (20 GB: ~US$ 4,4/mês); RDS Proxy: US$ 0,030 por vCPU-h do RDS associado (2 vCPUs: ~US$ 0,06/h, ~US$ 44/mês); snapshot manual: US$ 0,095/GB-mês (20 GB: ~US$ 1,9/mês); segredo no Secrets Manager: ~US$ 0,40/mês (**não verificado** em `sa-east-1`). Total: ~US$ 0,082/h só com o RDS (~US$ 60/mês) e ~US$ 0,14/h com o Proxy (~US$ 104/mês).

## Etapa 3: a aplicação (`ecr.tf`, `ecs.tf`, `alb.tf`, `app-secrets.tf`, `app-variables.tf`)

Código e `plan` só (nada aplicado). Cria o ECR vazio, o cluster ECS `maria-langgraph-pp-sp`, as roles de execução e a task (a task role de Bedrock vem do `iam.tf`), a task definition do release, o service `api-release-sp`, o ALB `maria-langgraph-pp-sp-alb` com o target group e o listener, os security groups do ALB e da regra das tasks, e os dois segredos do release (`maria-langgraph-pp-release/app` e `maria-langgraph-pp-release/email-nudecon`, com valores `PREENCHER`: os reais entram por `put-secret-value` ou pelo console). **Não** mexe no CloudFront: o corte é uma etapa à parte.

- `plan` em cima do state aplicado (rede, RDS e Proxy): **22 a criar, 0 a alterar, 0 a destruir**, sem NAT (estado de então).
- **O service começa com `app_desired_count = 0`**: o ECR novo está vazio, e as tasks só sobem depois do push da imagem (tag `release`) e do preenchimento dos segredos.
- **NAT e subnet privada (aplicado em 2026-11-11):** `nat_count = 1` e `tasks_in_public_subnets = false` (padrões). As tasks saem pelo EIP `18.228.145.80`. Com `tasks_in_public_subnets = true` elas ficariam nas subnets públicas com IP público (sem NAT), e o IP de saída mudaria a cada deploy.
- **ALB só do CloudFront:** `alb_only_from_cloudfront = true` limita a entrada do ALB à lista de prefixos gerenciada do CloudFront (na Virgínia o ALB aceita HTTP de qualquer lugar e roteia por header). Para testar direto pelo endereço do ALB antes do corte, aplicar com `-var alb_only_from_cloudfront=false` e voltar depois.
- **Modelo de IA:** o padrão de `bedrock_model_id` (`qwen.qwen3-vl-235b-a22b`) acompanha o escopo da task role (modelos Qwen in-region). A task de São Paulo já sobe com `BEDROCK_MODEL_ID` = esse modelo e `AWS_REGION` = `sa-east-1`. Para o Qwen, os prompts de triagem recebem um sufixo (`src/maria/ia/ajuste_qwen.py`, #465; ver `docs/ia.md`). Trocar de modelo exige ajustar `bedrock_model_arns` e rodar a suíte de integração de IA.
- **Dependências entre PRs:** esta etapa usa a task role (#460), o RDS e o Proxy (#461) e a rede (#459). Mergear nessa ordem.

Ordem de aplicação (cada passo só com OK escrito do Ícaro): 1) ECR, segredos e roles; 2) o Ícaro preenche os segredos (a `DATABASE_URL` com o endpoint do Proxy, banco `maria_langgraph_pp_release`, `sslmode=require`); 3) ALB, target group, cluster, task e service (com `app_desired_count = 0`); 4) push da imagem `release` para o ECR de São Paulo; 5) `app_desired_count = 1` e teste de ponta a ponta pelo endereço do ALB.

## Blue/green do release

1. **Rede e base** em `sa-east-1` (este root).
2. **Banco:** restaurar o RDS a partir da cópia do snapshot (`maria-chat-prod-pg-copia-sp-20261111`, criptografada com `alias/aws/rds`), criar o Proxy e os segredos (valores à mão, por `put-secret-value`) e **apagar do RDS novo** os bancos de produção (o release só usa `maria_langgraph_pp_release`). O snapshot contém todos os bancos da instância: é dado de produção.
3. **Aplicação:** ECR na região nova, ECS, ALB e target group. O ALB só aceita entrada do CloudFront, então o teste de ponta a ponta usa a distribuição própria de São Paulo (`cloudfront.tf`, saída `api_https_url_release_sp`), sem abrir o ALB e sem tocar na distribuição da Virgínia.
4. **Bedrock:** `AWS_REGION` e `BEDROCK_MODEL_ID` na região nova. O Haiku 4.5 só roda em São Paulo por perfil `global.` (processa em qualquer região); para manter a inferência no Brasil, só os modelos de outros fornecedores (por exemplo, Qwen3 VL 235B), com qualidade menor na suíte da Maria. A escolha é decisão à parte.
5. **Corte:** trocar a origem do CloudFront do release (a distribuição antiga, da Virgínia) para o ALB novo. O domínio não muda, então a Tykhe não muda; voltar a origem desfaz o corte. A distribuição de teste de São Paulo (`cloudfront.tf`) deixa de ser necessária depois do corte e pode ser removida. Ela não usa o header `X-Maria-Env`: o listener do ALB de São Paulo encaminha tudo ao target group por padrão, sem regra por header.
6. **Observar** alguns dias e só então desligar o release da Virgínia, com um snapshot final.

Fora do escopo desta etapa: produção, Lambda `maria-email-nudecon`, DynamoDB de idempotência e SES (a função é única e funciona a partir de `sa-east-1`).
