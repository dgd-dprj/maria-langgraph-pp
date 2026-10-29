# Maria

Ponte entre a **Tykhe** (chatbot) e o **Verde** (sistema da Defensoria Pública do RJ). A pessoa conta o que precisa; a Maria identifica o tipo de atendimento, conduz as perguntas do fluxo e devolve à Tykhe o resultado ou o encaminhamento.

Cada fluxo de atendimento é um grafo de estados do [LangGraph](https://langchain-ai.github.io/langgraph/) (Python), com pausa e retomada nativas: a cada pergunta, o grafo para (`interrupt`) e continua quando a resposta chega, com o estado guardado num checkpoint do Postgres.

Vai contribuir? Ver [`CONTRIBUTING.md`](CONTRIBUTING.md) (fluxo de issue, branch, commit e PR).

**Branches e ambientes:** `develop` faz o papel de **staging**. Cada merge nela sobe no ambiente de homologação, que a infraestrutura chama de `release`, e é onde a equipe valida. `main` é a **produção**. Detalhes em [`CONTRIBUTING.md`](CONTRIBUTING.md#branches-e-ambientes). **Corrigido em 2026-10-26:** hoje a equipe testa na `main` (produção), pela Tykhe, e ninguém usa o release.

> **Migração.** Até outubro de 2026 a Maria foi escrita em TypeScript (Fastify e LangGraph JS). A tradução para Python reproduziu o comportamento da versão TypeScript, inclusive os defeitos conhecidos, que foram registrados em issues para corrigir depois. O registro completo, com cada decisão, está em [`MIGRACAO.md`](MIGRACAO.md) e em [`docs/migracao/`](docs/migracao/).

## Rodando local

Para subir a API com um Postgres local, use `docker compose up --build` e confira com `curl -s http://127.0.0.1:3001/health` (seção 6.1 do guia abaixo).

O guia completo, testado numa pasta limpa, está em [`docs/rodar-localmente.md`](docs/rodar-localmente.md): instalação, os dois modos (sem AWS e com o Bedrock real), como chamar o orquestrador e responder às perguntas, e problemas comuns.

O mínimo (Python 3.12 e [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
printf 'API_KEY=troque-esta-chave\nAPP_ENV=test\n' > .env   # modo de teste: IA e Verde simulados, sem banco
uv run python -m maria.main                                   # http://localhost:3001
```

No PowerShell, a segunda linha é `Set-Content -Path .env -Encoding ascii -Value "API_KEY=troque-esta-chave`nAPP_ENV=test"`.

Nesse modo, o orquestrador manda todo relato para `outros`; para simular uma classificação, acrescente `MOCK_CLASSIFICACAO_FLOWID` (ver o guia).

`GET /docs` abre o Swagger UI com o contrato HTTP completo.

## Variáveis de ambiente

Todas ficam no `.env` (carregado no boot) ou no ambiente. Sem `DATABASE_URL`, tudo fica em memória; sem `VERDE_JWT_TOKEN`, o Verde é simulado; sem as variáveis `WHATSAPP_*`, o envio para o WhatsApp é simulado.

| Variável | Padrão | Efeito |
|---|---|---|
| `API_KEY` | **obrigatória** | Chave que as rotas exigem em `Authorization: Bearer <chave>`. Sem ela, a API não sobe |
| `APP_ENV` | ausente | **Só o valor `test` muda o comportamento:** IA e embeddings simulados (nunca chama o Bedrock) e `chatId` opcional, gerado se faltar. **Qualquer outro valor, inclusive `development` e ausente, é o comportamento de produção:** IA real e `chatId` obrigatório |
| `DATABASE_URL` | ausente | Postgres com a extensão pgvector. Sem ela, checkpoints, atendimentos, perguntas, fluxos planejados e embeddings ficam em memória |
| `AWS_REGION` | `us-east-1` | Região do Bedrock |
| `AWS_PROFILE` | ausente | Perfil do AWS CLI usado pelo SDK para chamar o Bedrock |
| `AWS_ACCESS_KEY_ID` | ausente | Alternativa ao perfil, junto com `AWS_SECRET_ACCESS_KEY` (lidas pelo SDK) |
| `AWS_SECRET_ACCESS_KEY` | ausente | Ver `AWS_ACCESS_KEY_ID` |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-haiku-20240307-v1:0` | Modelo das chamadas de IA. Produção usa `us.anthropic.claude-haiku-4-5-20251001-v1:0` (o padrão do código é antigo) |
| `BEDROCK_EMBEDDING_MODEL_ID` | `amazon.titan-embed-text-v2:0` | Modelo de embedding da busca por similaridade |
| `ORQUESTRADOR_INCLUIR_PLANEJADOS` | ausente | Com `true` exato, os fluxos planejados entram no catálogo do orquestrador. Sem ela, são 9 opções: 2 fluxos da Maria e 7 tipos da Tykhe (#242) |
| `TTL_INATIVIDADE_HORAS` | `24` | Horas sem resposta depois das quais a API pergunta se a pessoa quer continuar (#166). Com `0`, pergunta sempre |
| `EXTRACAO_LIVRE_IA` | ausente | Com `true`, liga a extração de dados por IA no fluxo pessoa presa (desligada por padrão) |
| `REESCREVER_IA` | ausente | Com `true`, liga a reescrita do texto das perguntas por IA. Desligada por padrão desde 2026-08-31, depois de reescritas com fraseado estranho em produção |
| `VERDE_API_URL` | homologação do Verde | Endereço da API do Verde |
| `VERDE_JWT_TOKEN` | ausente | Token do Verde. Sem ele, todas as chamadas ao Verde são simuladas |
| `VERDE_CLIENT_ID` | ausente | Enviado ao Verde no cabeçalho `x-client-id` |
| `WHATSAPP_API_URL` | `https://graph.facebook.com/v21.0` | API da Meta para o bridge do WhatsApp ([`docs/bridge-whatsapp.md`](docs/bridge-whatsapp.md)) |
| `WHATSAPP_PHONE_NUMBER_ID` | ausente | Número do WhatsApp na Meta. Sem ele (ou sem o token), o envio é simulado e só registrado no log |
| `WHATSAPP_ACCESS_TOKEN` | ausente | Token da Meta para enviar mensagens |
| `WHATSAPP_VERIFY_TOKEN` | ausente | Token da verificação do webhook (`GET /webhook/whatsapp`). Sem ele, a verificação sempre devolve 403 |
| `MOCK_CLASSIFICACAO_FLOWID` | ausente | Com `APP_ENV=test`, o fluxo que a classificação simulada escolhe. Sem ela, o relato vai para `outros` |
| `MOCK_CLASSIFICACAO_FLOWIDS` | ausente | Com `APP_ENV=test`, vários ids separados por vírgula: simula um relato ambíguo (desambiguação) |
| `MOCK_CLASSIFICACAO_PARENTESCO` | `Outro` | Com `APP_ENV=test`, o parentesco que a IA simulada devolve no fluxo pessoa presa |
| `MOCK_SUMARIZACAO_RESUMO` | ausente | Com `APP_ENV=test`, o resumo que a sumarização simulada devolve |
| `MOCK_CEP_INCOMPLETO` | ausente | No Verde simulado, com `true`, o CEP volta só com a UF, sem cidade nem logradouro (para testar o pedido de endereço completo) |
| `MOCK_PLANTAO_VIGENTE` | ausente | No Verde simulado, com `true`, há plantão vigente |
| `MOCK_ENCAMINHAMENTO_FALHA` | ausente | No Verde simulado, com `true`, o encaminhamento falha |
| `MOCK_CADASTRO_FALHA` | ausente | No Verde simulado, com `true`, o cadastro da pessoa falha |

Um teste ([`tests/test_documentacao.py`](tests/test_documentacao.py)) confere que esta tabela tem todas as variáveis que o código lê.

## Testes e verificação

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

O Windows PowerShell 5.1 não tem `&&`: rode os quatro comandos um por vez.

A suíte padrão não precisa de banco nem de rede (`APP_ENV=test`, Verde e Bedrock simulados). Dois marcadores ficam de fora dela: `postgres` (contra um Postgres real com pgvector; roda na segunda etapa do CI) e `integracao` (chama o Bedrock e o Verde de verdade; só manual). Detalhes em [`docs/testes.md`](docs/testes.md).

## Estrutura

```
src/maria/
  main.py, app.py     # entrada (uvicorn) e montagem da aplicação, com a ordem de inicialização
  api/                # rotas HTTP; o pipeline reproduz a ordem e os erros do Fastify da versão anterior
  orquestrador/       # classificação do relato e desambiguação
  fluxos/<nome>/      # 1 fluxo = 1 grafo LangGraph (graph.py, state.py, api.py)
  subgrafos/          # trechos reaproveitados entre fluxos (identificar_assistido, cadastro_pessoa, coletar_endereco)
  ia/                 # chamadas ao Bedrock (classificar, desambiguar, extrair, reescrever, sumarizar)
  integracoes/        # Verde, WhatsApp e o cliente HTTP
  shared/             # persistência (Postgres), checkpointer, logger, utilitários
tests/                # espelha src/maria/; fixtures de contrato em tests/fixtures/
scripts/              # utilitários de manutenção, fora da imagem (ver scripts/README.md)
infra/terraform/      # infraestrutura AWS
infra/grafana/        # painéis e alertas versionados
```

Ferramentas fora do Python: o **Node.js** só é preciso para os hooks do Claude Code (`.claude/hooks/`), para o `scripts/logs-prod.sh` (`pino-pretty`) e para gerar diagramas (`mermaid-cli`). Nada da aplicação depende dele.

## Documentação

- [`docs/arquitetura.md`](docs/arquitetura.md): visão geral, decisões de infraestrutura e o porquê de cada uma, persistência, observabilidade.
- [`docs/fluxo-orquestrador.md`](docs/fluxo-orquestrador.md): como o relato livre vira um fluxo, um encaminhamento à Tykhe ou uma pergunta de desambiguação.
- [`docs/fluxo-pessoa-presa.md`](docs/fluxo-pessoa-presa.md), [`docs/fluxo-violencia-domestica.md`](docs/fluxo-violencia-domestica.md) e [`docs/fluxo-plano-saude.md`](docs/fluxo-plano-saude.md): regras de negócio de cada fluxo.
- [`docs/contrato-tykhe.md`](docs/contrato-tykhe.md): o que a API expõe para a Tykhe e o formato das respostas.
- [`docs/integracao-verde.md`](docs/integracao-verde.md): cada endpoint do Verde usado, o formato real das respostas e os defeitos encontrados ao vivo.
- [`docs/ia.md`](docs/ia.md): cada chamada de IA, o padrão comum de retentativa, simulação e flags.
- [`docs/bridge-whatsapp.md`](docs/bridge-whatsapp.md): o bridge do WhatsApp (só no ambiente de release).
- [`docs/guia-teste-homologacao.md`](docs/guia-teste-homologacao.md): o roteiro para a equipe testar no release, pelo WhatsApp e pela Tykhe, com o que já foi conferido e onde focar. **Corrigido em 2026-10-26:** a equipe está testando na produção, e não no release (ver o aviso no topo do guia).
- [`docs/testes.md`](docs/testes.md): como os testes são organizados e rodados, e o que roda no CI.
- [`docs/novo-fluxo.md`](docs/novo-fluxo.md): passo a passo para criar um fluxo novo.
- [`scripts/README.md`](scripts/README.md): os scripts de manutenção e quando rodar cada um.
- [`docs/padroes-issues.md`](docs/padroes-issues.md), [`docs/padroes-branch.md`](docs/padroes-branch.md), [`docs/padroes-commits.md`](docs/padroes-commits.md), [`docs/padroes-pull-request.md`](docs/padroes-pull-request.md): convenções de contribuição.
- [`docs/harness.md`](docs/harness.md): agentes, skills, hooks e comandos do Claude Code neste repositório.
