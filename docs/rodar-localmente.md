# Rodar a API da Maria localmente (versão Python)

Guia para subir a API no seu computador e mandar um relato ao orquestrador, para ver qual `flowId` ele devolve. Não precisa de Postgres nem do Verde. Precisa de credencial AWS só para a classificação real.

> **Leia antes de começar: no modo B, se todo relato voltar como `outros`, o orquestrador não está classificando mal: ele nem chegou a chamar o modelo.** Quando a chamada ao Bedrock falha (credencial, permissão, componente faltando), a API responde `200` como se o assunto não tivesse sido identificado, e a única pista é uma linha de nível 50 no log (seção 6). É um defeito registrado na #248. Confira o log antes de tirar qualquer conclusão sobre a classificação.
>
> **Comece pelo modo A.** Se ele funcionar, a instalação está certa. O modo B foi testado em 2026-10-19 com uma credencial criada por `aws login` (resultado na seção 9).

Os comandos foram testados numa pasta limpa no Windows 10, em 2026-10-16 (os da seção 5.1, em 2026-10-19), com `uv` 0.13.1 e Python 3.12: os blocos PowerShell no PowerShell 5.1, e os blocos bash no Git Bash. Use os blocos **PowerShell** no Windows e **bash** no macOS ou no Linux. No macOS e no Linux, os blocos bash não foram testados.

> **O que funciona:** `GET /health`, `GET /fluxos`, `POST /atendimentos`, `POST /atendimentos/orquestrador`, responder às perguntas de um fluxo (`POST /atendimentos/respostas`, seção 5.1) e consultar um atendimento (`GET /atendimentos/:chatId`). O bridge do WhatsApp (`/webhook/whatsapp`) também está na API, mas precisa das credenciais da Meta e não é coberto por este guia.

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

> Lembrete: o modo B **não foi testado** (veja o aviso no topo).

### Todas as variáveis

Nenhum valor desta tabela é real. Troque pelos seus.

| Variável | Obrigatória | Valor de exemplo | Efeito |
|---|---|---|---|
| `API_KEY` | **sim** | `troque-esta-chave` | Chave que as rotas exigem no cabeçalho `Authorization: Bearer <chave>`. Sem ela, a API **não sobe** (erro `API_KEY obrigatório`). Escolha qualquer texto |
| `APP_ENV` | não | `test` ou `development` | Só `test` muda o comportamento: IA e embeddings simulados, `chatId` opcional. Qualquer outro valor, inclusive `development` e ausente, é o comportamento de produção: IA real e `chatId` obrigatório. O `development` do modo B é só um rótulo |
| `MOCK_CLASSIFICACAO_FLOWID` | só no modo A | `3df874f2-675a-4c43-9ec7-480f7c702f50` | Com `APP_ENV=test`, o `flowId` que a classificação simulada devolve. Sem ela, todo relato vai para `outros` |
| `MOCK_CLASSIFICACAO_FLOWIDS` | não | `3df874f2-675a-4c43-9ec7-480f7c702f50,cabb2495-4e12-4f4a-9956-3d20649059bc` | Com `APP_ENV=test`, vários ids separados por vírgula: simula um relato ambíguo, e o orquestrador faz uma pergunta de desambiguação |
| `AWS_REGION` | modo B | `us-east-1` | Região do Bedrock |
| `AWS_PROFILE` | modo B (ou as chaves) | `nome-do-seu-perfil` | Perfil do AWS CLI com acesso ao Bedrock. Alternativa: `AWS_ACCESS_KEY_ID` e `AWS_SECRET_ACCESS_KEY` |
| `BEDROCK_MODEL_ID` | modo B | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Modelo da classificação (o mesmo de produção). Sem ela, o código usa um modelo antigo |
| `BEDROCK_EMBEDDING_MODEL_ID` | não | `amazon.titan-embed-text-v2:0` | Modelo de embedding da busca por similaridade. O valor de exemplo é o padrão |
| `ORQUESTRADOR_INCLUIR_PLANEJADOS` | não | `true` | Com `true` exato, os fluxos planejados entram no catálogo. Padrão: desligado, com 9 opções (2 fluxos da Maria e 7 tipos da Tykhe) |
| `TTL_INATIVIDADE_HORAS` | não | `24` | Horas sem resposta depois das quais a API pergunta se a pessoa quer continuar (#166). Com `0`, pergunta sempre; útil para testar |
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

### 5.1 Responder às perguntas e consultar o atendimento

Quando a resposta traz um `flowId`, o atendimento continua por `POST /atendimentos/respostas`, sempre com o **mesmo** `chatId`. Nas perguntas `sim_nao`, responda `"true"` ou `"false"` (a Tykhe também manda "Sim" e "Não", e a API aceita os dois).

PowerShell:

```powershell
$corpo = '{"chatId":"teste-1","resposta":"false"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:3001/atendimentos/respostas -ContentType "application/json; charset=utf-8" -Headers @{ Authorization = "Bearer troque-esta-chave" } -Body ([Text.Encoding]::UTF8.GetBytes($corpo)) | ConvertTo-Json -Depth 5
```

bash:

```bash
curl -s -X POST http://127.0.0.1:3001/atendimentos/respostas \
  -H "Authorization: Bearer troque-esta-chave" \
  -H "Content-Type: application/json" \
  -d '{"chatId":"teste-1","resposta":"false"}'
```

**Resposta esperada no modo A**, depois da 1ª pergunta de pessoa presa ("Você tem o número do processo…?"), respondendo `false`:

```json
{"resposta":"Qual o RG da pessoa presa? Informe apenas os números.","tipoResposta":"texto","status":"em_andamento","flowId":"3df874f2-675a-4c43-9ec7-480f7c702f50","metadados":{"temProcesso":false},"dadosColetados":{},"_links":{"self":{"href":"/atendimentos/teste-1"},"responder":{"href":"/atendimentos/respostas","method":"POST"}}}
```

Para ver em que pé está um atendimento, sem avançar nada:

PowerShell:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:3001/atendimentos/teste-1 -Headers @{ Authorization = "Bearer troque-esta-chave" } | ConvertTo-Json -Depth 5
```

bash:

```bash
curl -s http://127.0.0.1:3001/atendimentos/teste-1 -H "Authorization: Bearer troque-esta-chave"
```

| Código | Significado |
|---|---|
| `200` com `status: "em_andamento"` | A resposta foi aceita, e `resposta` é a próxima pergunta |
| `200` com `status: "concluido"` ou `"handoff_humano"` | O atendimento terminou. `metadados` traz o que foi coletado, e `tokensGastos` o total gasto com IA |
| `404` com `{"erro":"atendimento não encontrado"}` | Esse `chatId` nunca foi criado (ou o servidor foi reiniciado sem banco, seção 6) |
| `409` com `"atendimento já foi concluído — nada esperando resposta"` | O atendimento já terminou. Para recomeçar, use um `chatId` novo |
| `200` com "Já faz um tempo desde sua última mensagem. Quer continuar de onde você parou?" | Passou o tempo de inatividade (`TTL_INATIVIDADE_HORAS`, 24 h por padrão). Responda `true` para continuar de onde parou, ou `false` para encerrar |

## 6. O que acontece sem banco e sem credencial AWS

- **Sem `DATABASE_URL`:** o checkpoint das conversas e as tabelas ficam **em memória**. Nada persiste: ao reiniciar o servidor, os atendimentos somem, e um `chatId` já usado volta a estar livre.
- **Sem credencial AWS, com `APP_ENV=development`** (testado em 2026-10-16):
  - o servidor sobe normalmente;
  - todo relato responde `200` em cerca de 4 s, com `status: "redirecionado"` e `tipoCaso: "outros"`;
  - a classificação falha, e o orquestrador trata como "não identificado";
  - no log aparece uma linha de nível 50 com `NoCredentialsError: Unable to locate credentials`.

  **Se todo relato vier como `outros`, confira a credencial antes de qualquer outra coisa.**
- **Com `AWS_PROFILE` de um perfil que não existe** (por exemplo, `nome-do-seu-perfil` copiado sem trocar; testado em 2026-10-16): o comportamento é o mesmo do item anterior, e o log mostra `The config profile (nome-do-seu-perfil) could not be found`. Para listar os perfis configurados, use `aws configure list-profiles`.
- **Com credencial criada por `aws login`, num ambiente instalado antes de 2026-10-19** (testado em 2026-10-19): o comportamento é o mesmo dos itens anteriores, embora a credencial funcione na AWS CLI. O log mostra `Using the login credential provider requires an additional dependency. You will need to pip install "botocore[crt]"`. O `uv sync` atual já instala esse componente; num ambiente antigo, rode `uv sync` de novo.
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
| `400` com `{}` só quando o relato tem acento, usando `curl` no Git Bash do Windows | O Git Bash entrega o texto ao `curl` em Latin-1, e a API (como a de develop) recusa corpo que não é UTF-8. No Windows, use o bloco PowerShell |
| `ImportError` ou `ModuleNotFoundError` de um módulo do `langsmith` ou de outra dependência, na subida, no Windows | O caminho da pasta é longo demais: o Windows sem suporte a caminhos longos limita o caminho a 260 caracteres, e o `uv sync` deixa de instalar o arquivo sem avisar. Clone numa pasta de caminho curto (por exemplo, `C:\projetos`), apague a `.venv` e rode `uv sync` de novo |
| A porta 3001 está ocupada | Outro processo usa a porta. Encerre-o; a porta é fixa no código |
| **Todo relato vem como `outros`, com `tokensGastos` zerado** | **O modelo não foi chamado; não é classificação ruim** (#248). Procure no log a linha de nível 50 `[classificar] falha ao classificar`: ela diz a causa. As mais comuns são: sem credencial AWS, perfil inexistente, credencial de `aws login` sem o componente `botocore[crt]` (rode `uv sync` de novo) ou falta de permissão no Bedrock (seção 6). No modo A, a causa é faltar `MOCK_CLASSIFICACAO_FLOWID` |

## 9. Teste do modo B (2026-10-19)

Executado a partir de um clone limpo da `migration` (`23b63e3`), no Windows, com uma credencial criada por `aws login` e o `.env` do modo B. Os relatos foram inventados, sem dado de pessoa real. Os números servem de referência para quem for testar; o modelo pode variar a pergunta de desambiguação entre execuções.

| Relato (resumo) | Retorno | Candidatos que sobraram (das 9 opções) | Primeira pergunta ou mensagem | Tokens | Tempo |
|---|---|---|---|---|---|
| Irmão preso, sem notícia do processo | `flowId` de pessoa presa | 1 | "Você tem o número do processo da pessoa que está presa?" | 1.880 | 3,7 s |
| Marido agride e ameaçou de morte | `flowId` de violência doméstica | 1 | "Você é a vítima de violência doméstica?" | 1.877 | 1,5 s |
| Remédio caro que o SUS não fornece | `redirecionado`, `tipoCaso: saude` | 1 | "Entendi. Vou te encaminhar para o atendimento de questões de saúde." | 1.854 | 1,1 s |
| Ex preso por agressão, e a família dele ameaça (ambíguo) | pergunta de desambiguação, sem `flowId` | 2 (violência doméstica e pessoa presa) | "Você quer informações sobre a prisão dele ou precisa de proteção contra as ameaças…?" | cerca de 3.000 | 3,4 s |
| O mesmo, respondendo "quero me proteger, quem foi agredida fui eu" | `flowId` de violência doméstica | 1 | "Você é a vítima de violência doméstica?" | +1.290 | 1,5 s |
| Demitido sem receber rescisão e FGTS (assunto trabalhista, fora das 9 opções) | `redirecionado`, `tipoCaso: novo-processo` | 1 | "Entendi. Vou te encaminhar para o atendimento de abertura de um novo caso." | 1.855 | não medido |

**Como ler:** nos casos claros, sobrou um candidato só. No ambíguo, sobraram dois, e o orquestrador perguntou em vez de escolher sozinho. O relato trabalhista não caiu em `outros`: foi para `novo-processo` da Tykhe, embora a Defensoria não atue em causas trabalhistas. Isso é efeito da redução do catálogo para 9 opções (#242), e não do teste.
