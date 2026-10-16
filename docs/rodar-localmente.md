# Rodar a API da Maria localmente (versão Python)

Guia para subir a API no seu computador e mandar um relato ao orquestrador, para ver qual `flowId` ele devolve. Não precisa de Postgres nem do Verde. Precisa de credencial AWS só para a classificação real.

Os comandos foram testados numa pasta limpa no Windows 10 (PowerShell 5.1), em 2026-10-16, com `uv` 0.13.1 e Python 3.12. Use os blocos **PowerShell** no Windows e **bash** no macOS ou no Linux.

> **O que já funciona:** `GET /health`, `GET /fluxos`, `POST /atendimentos` e `POST /atendimentos/orquestrador`.
> **O que ainda não funciona:** responder às perguntas de um fluxo (`POST /atendimentos/respostas`) e consultar um atendimento (`GET /atendimentos/:chatId`). Isso entra no próximo PR do módulo api (#246). Por enquanto, dá para ver o fluxo escolhido e a primeira pergunta dele, mas não continuar a conversa.

## 1. Requisitos

| Programa | Versão | Como conferir | Onde obter |
|---|---|---|---|
| Git | qualquer recente | `git --version` | https://git-scm.com |
| uv | 0.13 ou mais nova | `uv --version` | https://docs.astral.sh/uv/getting-started/installation/ |
| Python | 3.12 | `uv python list` | o `uv` instala sozinho no passo 2, se faltar |

## 2. Instalação

```bash
git clone https://github.com/dgd-dprj/maria-langgraph-pp.git
cd maria-langgraph-pp
git checkout migration
uv sync
```

O `uv sync` cria o ambiente em `.venv/` com as versões travadas no `uv.lock`. Se o Python 3.12 não estiver instalado, rode antes `uv python install 3.12`.

## 3. Configuração (`.env`)

A API lê as variáveis de um arquivo `.env` na raiz do projeto. Escolha um dos dois modos abaixo.

### Modo A: sem AWS (para conferir que subiu)

A classificação é simulada: todo relato vai para o fluxo indicado em `MOCK_CLASSIFICACAO_FLOWID`. Serve para conferir a instalação e o formato das respostas, mas **não classifica de verdade**.

PowerShell:

```powershell
Set-Content -Path .env -Encoding ascii -Value "API_KEY=troque-esta-chave`nAPP_ENV=test`nMOCK_CLASSIFICACAO_FLOWID=3df874f2-675a-4c43-9ec7-480f7c702f50"
```

bash:

```bash
printf 'API_KEY=troque-esta-chave\nAPP_ENV=test\nMOCK_CLASSIFICACAO_FLOWID=3df874f2-675a-4c43-9ec7-480f7c702f50\n' > .env
```

### Modo B: classificação real, com o Bedrock

A classificação usa o modelo de verdade. Precisa de uma credencial AWS com acesso ao Bedrock na região `us-east-1`. Ela pode ser um perfil configurado no AWS CLI (`AWS_PROFILE`) ou chaves de acesso. **Nunca grave chaves reais num arquivo que vá para o git.** O `.env` está no `.gitignore`.

PowerShell:

```powershell
Set-Content -Path .env -Encoding ascii -Value "API_KEY=troque-esta-chave`nAPP_ENV=development`nAWS_REGION=us-east-1`nAWS_PROFILE=nome-do-seu-perfil`nBEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0"
```

bash:

```bash
printf 'API_KEY=troque-esta-chave\nAPP_ENV=development\nAWS_REGION=us-east-1\nAWS_PROFILE=nome-do-seu-perfil\nBEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0\n' > .env
```

> O modo B **não foi testado** por quem escreveu este guia, por falta de acesso autorizado ao Bedrock. Foi testado o que acontece **sem** credencial (seção 6).

### Todas as variáveis

Nenhum valor desta tabela é real. Troque pelos seus.

| Variável | Obrigatória | Valor de exemplo | Efeito |
|---|---|---|---|
| `API_KEY` | **sim** | `troque-esta-chave` | Chave que as rotas exigem no cabeçalho `Authorization: Bearer <chave>`. Sem ela, a API **não sobe** (erro `API_KEY obrigatório`). Escolha qualquer texto |
| `APP_ENV` | não | `test` ou `development` | `test`: IA e embeddings simulados, `chatId` opcional. `development`: IA real. Ausente: comporta-se como produção (IA real, `chatId` obrigatório) |
| `MOCK_CLASSIFICACAO_FLOWID` | só no modo A | `3df874f2-675a-4c43-9ec7-480f7c702f50` | Com `APP_ENV=test`, o `flowId` que a classificação simulada devolve. Sem ela, todo relato vai para `outros` |
| `MOCK_CLASSIFICACAO_FLOWIDS` | não | `3df874f2-675a-4c43-9ec7-480f7c702f50,cabb2495-4e12-4f4a-9956-3d20649059bc` | Com `APP_ENV=test`, vários ids separados por vírgula: simula um relato ambíguo, e o orquestrador faz uma pergunta de desambiguação |
| `AWS_REGION` | modo B | `us-east-1` | Região do Bedrock |
| `AWS_PROFILE` | modo B (ou as chaves) | `nome-do-seu-perfil` | Perfil do AWS CLI com acesso ao Bedrock. Alternativa: `AWS_ACCESS_KEY_ID` e `AWS_SECRET_ACCESS_KEY` |
| `BEDROCK_MODEL_ID` | modo B | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Modelo da classificação (o mesmo de produção). Sem ela, o código usa um modelo antigo |
| `BEDROCK_EMBEDDING_MODEL_ID` | não | `amazon.titan-embed-text-v2:0` | Modelo de embedding da busca por similaridade. O valor de exemplo é o padrão |
| `ORQUESTRADOR_INCLUIR_PLANEJADOS` | não | `true` | Com `true` exato, os fluxos planejados entram no catálogo. Padrão: desligado, com 9 opções (2 fluxos da Maria e 7 tipos da Tykhe) |
| `DATABASE_URL` | não | `postgresql://usuario:senha@localhost:5432/maria` | Sem ela, tudo fica em memória (seção 6). Com ela, usa Postgres com a extensão pgvector |
| `VERDE_API_URL`, `VERDE_JWT_TOKEN`, `VERDE_CLIENT_ID` | não | (vazio) | Sem `VERDE_JWT_TOKEN`, o Verde é simulado. O orquestrador não precisa do Verde |

## 4. Subir o servidor

```bash
uv run python -m maria.main
```

O servidor ouve na porta **3001**, que é fixa no código. Cada linha de log sai em JSON. A linha `[checkpoint] DATABASE_URL ausente — usando MemorySaver (não persiste)` é esperada sem banco. Para parar, use `Ctrl+C`.

## 5. Conferir que subiu

Em outro terminal, com o servidor rodando.

**Health check** (sem autenticação):

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:3001/health
```

bash:

```bash
curl -s http://127.0.0.1:3001/health
```

Resposta esperada: `{"status":"ok"}` (no PowerShell aparece como `status : ok`).

**Mandar um relato ao orquestrador.** Use um `chatId` novo a cada relato, porque o mesmo `chatId` continua a conversa anterior.

PowerShell:

```powershell
$corpo = '{"chatId":"teste-1","mensagem":"meu filho está preso e preciso de ajuda"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:3001/atendimentos/orquestrador -ContentType "application/json; charset=utf-8" -Headers @{ Authorization = "Bearer troque-esta-chave" } -Body ([Text.Encoding]::UTF8.GetBytes($corpo)) | ConvertTo-Json -Depth 5
```

bash:

```bash
curl -s -X POST http://127.0.0.1:3001/atendimentos/orquestrador \
  -H "Authorization: Bearer troque-esta-chave" \
  -H "Content-Type: application/json" \
  -d '{"chatId":"teste-1","mensagem":"meu filho está preso e preciso de ajuda"}'
```

**Resposta esperada no modo A** (o `flowId` é o de pessoa presa, vindo do `MOCK_CLASSIFICACAO_FLOWID`):

```json
{"resposta":"Você tem o número do processo da pessoa que está presa?","tipoResposta":"sim_nao","opcoes":["Sim","Não"],"status":"em_andamento","metadados":{},"dadosColetados":{},"flowId":"3df874f2-675a-4c43-9ec7-480f7c702f50","_links":{"self":{"href":"/atendimentos/teste-1"},"responder":{"href":"/atendimentos/respostas","method":"POST"}}}
```

### Como ler a resposta

| O que veio | Significado |
|---|---|
| `status: "em_andamento"` **com** `flowId` | O relato foi para um fluxo da Maria, e a resposta já é a 1ª pergunta dele. `3df874f2-…` é pessoa presa, e `cabb2495-…` é violência doméstica (`GET /fluxos` lista os dois) |
| `status: "em_andamento"` **sem** `flowId` | O relato ficou ambíguo, e a `resposta` é uma pergunta de desambiguação. Responda no **mesmo** `chatId`, com `"resposta"` no lugar de `"mensagem"`: `{"chatId":"teste-1","resposta":"é sobre o meu filho"}` |
| `status: "redirecionado"` com `tipoCaso` | O relato é de um tipo que a Tykhe atende (`saude`, `novo-processo`, `andamento-processo`, `agendamentos`, `ajuda-app`, `sair`) ou não foi identificado (`outros`). Não há `flowId`, porque a Maria não cria atendimento |

## 6. O que acontece sem banco e sem credencial AWS

- **Sem `DATABASE_URL`:** o checkpoint das conversas e as tabelas ficam **em memória**. Nada persiste: ao reiniciar o servidor, os atendimentos somem, e um `chatId` já usado volta a estar livre.
- **Sem credencial AWS, com `APP_ENV=development`** (testado em 2026-10-16):
  - o servidor sobe normalmente;
  - todo relato responde `200` em cerca de 4 s, com `status: "redirecionado"` e `tipoCaso: "outros"`;
  - a classificação falha, e o orquestrador trata como "não identificado";
  - no log aparece uma linha de nível 50 com `NoCredentialsError: Unable to locate credentials`.

  **Se todo relato vier como `outros`, confira a credencial antes de qualquer outra coisa.**
- **Com `APP_ENV=test`:** nada chama a AWS, e a classificação usa os `MOCK_*`.

## 7. Documentação das rotas

Com o servidor rodando, `http://127.0.0.1:3001/docs` abre o Swagger UI, com as rotas e os formatos de corpo. O documento OpenAPI fica em `/docs/json`.

## 8. Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `RuntimeError: API_KEY obrigatório` na subida | Falta `API_KEY` no `.env`, ou o `.env` não está na pasta onde você rodou o comando |
| `401` com `{"error":"missing authorization header"}` | Faltou o cabeçalho `Authorization` |
| `401` com `{"error":"invalid authorization header"}` | A chave no cabeçalho não é a do `.env`, ou falta o prefixo `Bearer ` (com B maiúsculo) |
| `400` com `{"erro":"chatId obrigatório"}` | Fora de `APP_ENV=test`, todo pedido precisa de `chatId` |
| `400` com `{}` | O corpo não é JSON válido, ou um campo veio com tipo errado (por exemplo, `mensagem` como objeto) |
| A porta 3001 está ocupada | Outro processo usa a porta. Encerre-o; a porta é fixa no código |
| Todo relato vem como `outros` | Sem credencial AWS (seção 6), ou, no modo A, sem `MOCK_CLASSIFICACAO_FLOWID` |
