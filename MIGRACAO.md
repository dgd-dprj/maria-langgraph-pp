# Migração de TypeScript para Python

Este documento conta a mesma história da issue [#208](https://github.com/dgd-dprj/maria-langgraph-pp/issues/208), para quem abrir o repositório depois. A issue é a fonte das decisões; cada decisão nova entra lá como comentário e aqui.

## O que mudou e o que não mudou

O serviço foi reescrito de TypeScript (Node 22, Fastify, LangGraph JS, pnpm) para Python 3.12 (FastAPI, LangGraph Python, uv, ruff, mypy, pytest).

**A régua é comportamento idêntico ao de `develop` @ `4e695f2`**: mesmas perguntas, mesmos desfechos, mesmo contrato HTTP com a Tykhe e mesmos logs consumidos pelo Grafana. Funcionalidade nova, melhoria e mudança de contrato ficaram fora. O que valia melhorar está na seção [Melhorias registradas, fora do escopo](#melhorias-registradas-fora-do-escopo), sem implementar.

O código TypeScript não foi copiado nem convive com o Python. Ele continua em `develop` (e no histórico do git) como fonte de comportamento.

## Modelo de branch

- `migration` saiu de `develop` @ `4e695f2`. A fundação ([#209](https://github.com/dgd-dprj/maria-langgraph-pp/issues/209)) removeu todo o código de origem e o ferramental de Node.
- Cada módulo tem a sua issue, aberta imediatamente antes da sua branch `refactor/<issue>-<modulo>-python`, e volta para `migration` por pull request. Ninguém faz commit direto em `migration`. A fundação usa `refactor/209-fundacao-python`.
  - O modelo inicial previa `migration/<modulo>`, mas isso é impossível no git enquanto a branch `migration` existir: uma ref não pode ser arquivo e diretório ao mesmo tempo. O nome segue a convenção `tipo/numero-descricao` do repositório.
- `develop` e `main` não recebem nada até o último PR, que leva `migration` para `develop`.

## Estrutura

```
pyproject.toml · uv.lock · .python-version · Dockerfile · langgraph.json · MIGRACAO.md
src/maria/
  main.py  app.py
  fluxos/registro.py
  fluxos/{padrao,pessoa_presa,violencia_domestica}/{graph,state,api}.py
  orquestrador/{graph,state}.py
  subgrafos/{identificar_assistido,cadastro_pessoa,coletar_endereco}/{graph,state}.py
  ia/{classificar,classificar_fluxos,desambiguar,extrair,reescrever,sumarizar}.py · ia/CLAUDE.md
  integracoes/{verde,whatsapp}.py
  rotas/{atendimentos,fluxos,orquestrador,webhook_whatsapp}.py
  shared/{atendimentos_db,checkpointer,contexto,embeddings_fluxos,fluxos_planejados_db,
          logger,perguntas_db,tokens_acumulados,types}.py
tests/
  <espelho de src/maria>/test_<arquivo>.py      ← src/**/<x>.test.ts
  http/test_<arquivo>.py                       ← test/<arquivo>.test.ts
  integracao/test_<arquivo>.py                 ← test-integracao/<arquivo>.test.ts
  fixtures/contrato/                           ← gravadas de develop rodando de verdade
scripts/
  coletar_arvore_perguntas_verde.py · seed_fluxos_planejados.py · dados/fluxos_planejados.json
  logs-prod.sh · README.md
```

`src/<a>/<bB>/<cC>.ts` virou `src/maria/<a>/<b_b>/<c_c>.py`. As exceções são `server.ts` → `main.py` e `fluxos/index.ts` → `fluxos/registro.py`.

## Convenção de nomes

- **snake_case** em arquivos, pastas, funções e variáveis.
- **Continuam exatamente como antes**, porque são contrato:
  - canais de estado do grafo, em camelCase, sem exceção (os `api.ts` devolviam o estado direto para a Tykhe, e o compartilhamento com os subgrafos depende do nome);
  - campos do contrato HTTP;
  - campos dos logs (`fluxoId`, `motivoHandoff`, `duracaoMs`, `tipoErro`, `chamada`, `resultado`, `status`, `tokensGastos.total`…) e nomes de evento (`atendimento_finalizado`, `verde_chamada`…), que oito painéis do Grafana consultam pelo nome;
  - nomes de coluna e valores literais usados nos painéis.
- Negócio em português, infraestrutura em inglês (`logger.py`, `types.py`).

## Ordem de migração

| # | Módulo | Issue | Estado |
|---|---|---|---|
| 1 | `fundacao` | #209 | em revisão |
| 2 | `persistencia` | — | spec escrita |
| 3 | `integracoes` | — | spec escrita |
| 4 | `ia` | — | spec escrita |
| 5 | `subgrafos` | — | — |
| 6 | `fluxos` | — | — |
| 7 | `orquestrador` | — | — |
| 8 | `api` | — | — |
| 9 | `scripts` | — | — |
| 10 | `documentacao` | — | — |
| 11 | `corte` | — | — |

## Decisões registradas

### Ambiente e ferramental

- **`NODE_ENV` virou `APP_ENV`**, com os valores `test`, `development` e `production`. Ela governa contrato, e não só mocks: o `chatId` só é opcional em `test`. O código continua lendo a variável a cada requisição. Muda no `ENV` do Dockerfile, na configuração do pytest (`tests/conftest.py`) e no código.
- **Python 3.12** fixado em três lugares: `pyproject.toml` (`requires-python`), `.python-version` (lido pelo uv e pelo CI) e a imagem base do Dockerfile.
- **ruff** entrou como ferramental novo (develop não tinha linter). **mypy** em modo strict no código; nos testes, sem exigir anotação.
- **Suítes de teste:** a padrão (`uv run pytest`) não usa banco nem serviço externo, como o `pnpm test`. O marcador `postgres` roda contra Postgres real com pgvector, na segunda etapa do CI. O marcador `integracao` chama Bedrock e Verde de verdade e fica fora do CI.
- **CI só em PR para `migration`** durante a migração. Os gatilhos de `develop` e `main` voltam no último PR. Em `pull_request`, o GitHub roda o workflow do commit de merge, então o próprio PR da fundação já roda o `ci.yml` novo.
- **O CI constrói a imagem Docker** e confere o `/health` do container em todo PR para `migration`. Os deploys, que constroem a imagem, só disparam em `develop` e `main`; sem esse job, uma imagem quebrada só apareceria no merge final.
- **`publish-grafana.yml`:** o primeiro passo do job falha se a referência não for `develop` ou `main`. É a única alteração nesse workflow.
- **Hook de typecheck** (`.claude/hooks/typecheck-after-edit.mjs`): continua em Node, reage a `.py` e roda `uv run mypy`. Precisa do `uv` no `PATH`; sem ele, o hook falha a cada edição.
- **Windows (só desenvolvimento local):** a suíte usa o `WindowsSelectorEventLoopPolicy`, porque o psycopg assíncrono não funciona com o loop padrão do Windows (`tests/conftest.py`). O CI e a imagem são Linux.

### Peças compartilhadas (fundação)

- **Logger** (`shared/logger.py`): structlog com o envelope de linha do pino, na mesma ordem das linhas gravadas em develop: `level` (numérico), `time` (ms), `pid`, `hostname`, campos de negócio, `msg`. Campo `None` é omitido, como o `undefined` do JS. `err=` é serializado como o `err` do pino (`{type, message, stack}`). A saída é sempre UTF-8, como no pino, independentemente da codificação local: no Windows, com a saída redirecionada, o Python usaria cp1252 e corromperia "—" e "ã". O logging da biblioteca padrão (uvicorn) passa pelo mesmo envelope, para nenhuma linha de texto puro chegar ao `scripts/logs-prod.sh`.
- **Contexto** (`shared/contexto.py`): `get_config()` do LangGraph Python lança exceção fora de um run, enquanto o `getConfig()` do JS devolvia `undefined`. A exceção é absorvida para manter o contrato de nunca lançar.
- **Canal `tokensGastos`** (`shared/tokens_acumulados.py`): verificado contra o LangGraph instalado, um canal com reducer começa em `Tipo()`, e com `TypedDict` isso dá `{}`. Em develop, o default é `{input: 0, output: 0, total: 0}`. O canal usa uma subclasse de `dict` cujo construtor devolve esse valor, e o serializador do checkpointer a grava e lê como `dict` comum.
- **Checkpointer em schema próprio** (`shared/checkpointer.py`). O `setup()` do langgraph-checkpoint-postgres cria tabelas sem schema, com os mesmos nomes das tabelas do JS em `public` (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`), e as serializações são incompatíveis. Toda conexão do pool fixa `search_path` só no schema do Python. Os testes `postgres` provam que nada em `public` é tocado.
- **Ordem de inicialização:** o `setup()` do checkpointer e o schema de negócio rodam no lifespan, nessa ordem. O uvicorn só abre o socket depois do lifespan. `tests/test_app.py` prova a sequência com o uvicorn de verdade: enquanto a inicialização está bloqueada, a conexão é recusada. Se a inicialização falhar, o processo sai com código 3, e o ECS recria a task.
- **Pools Postgres** com `min_size=0`, `max_size=10`, `open=False` e `await pool.open()`, reproduzindo a abertura preguiçosa do `pg.Pool` contra o RDS Proxy compartilhado.

### Contrato HTTP

- Status, content-type e corpo de toda resposta, inclusive de erro, idênticos às fixtures de `tests/fixtures/contrato/`. Elas foram gravadas com a aplicação TypeScript de develop @ `4e695f2` rodando de verdade: 50 casos e as linhas de log de cada uma das 5 instâncias. A receita está anexada à #209. A comparação byte a byte acontece no módulo `api`.
- **Identificadores da máquina de captura trocados nas linhas de log, antes do primeiro commit.** O valor dessas fixtures está nos nomes de campo e na ordem do envelope, e não nos valores de ambiente. O `hostname` virou `maquina-de-captura` (166 linhas). O IP de rede interna nas linhas "Server listening" virou `192.0.2.10`, da faixa reservada para documentação (RFC 5737; 5 linhas). Os caminhos locais nos `stack` de erro, com o usuário e a pasta temporária, viraram o prefixo `C:\captura\develop-ts\` (39 linhas). A ordem das chaves não mudou, e um teste impede que esses dados voltem. A chave de API já tinha sido mascarada na captura (`Bearer <API_KEY>`).
- Os sete formatos de corpo de erro de develop são reproduzidos, inclusive o 400 de validação com corpo `{}`, que é o mais contraintuitivo (tabela na #208). O 500 vaza a mensagem interna (#210) e o 400 não dá motivo (#211): os dois são tratados depois da migração.

### Especificações dos módulos (decisões já tomadas, antes das issues)

- **persistencia:** `TIMESTAMPTZ` em microssegundo, sem truncar, porque nenhum timestamp atravessa a fronteira HTTP. O embedding falso dos testes reproduz a soma por code unit UTF-16 de develop.
- **integracoes:**
  - Nos três POST ao Verde, a leitura do corpo fica fora do retry, como em develop: um timeout lendo o corpo nunca reenvia. Nos seis GET, o retry da leitura é aceito como divergência.
  - Cabeçalhos implícitos do `fetch` igualados: `user-agent: node` (provisório, capturado com Node 24), `accept-language: *` e `sec-fetch-mode: cors`.
  - Timeout total de 30 s por tentativa: o padrão de 5 s do httpx reabriria a #196.
  - `follow_redirects=True`, `trust_env=False`, booleano na query string como `true`/`false`, escape igual ao `encodeURIComponent`.
- **ia:**
  - A saída estruturada **não** é validada, como em develop: o `z.enum` só descrevia a saída no prompt, e o `ChatBedrockConverse` do JS nunca validou. Um teste fixa isso, com comentário apontando para [#212](https://github.com/dgd-dprj/maria-langgraph-pp/issues/212), onde o defeito será corrigido depois da migração.
  - Retry medido em develop e reproduzido: 429 e 5xx dão 9 requisições; o boto3 fica em modo `standard` com 3 tentativas.

## Achados durante a migração

- **Logger em cp1252 no Windows (encontrado e corrigido na fundação).** Só apareceu porque a instalação da imagem foi reproduzida localmente e a saída do servidor foi redirecionada para arquivo. Com a saída redirecionada, o Python no Windows escreve na codificação ANSI local (cp1252), e "—", "ã" e os demais caracteres acentuados saíam como bytes inválidos em UTF-8. O pino sempre escreve UTF-8. A correção grava os bytes em UTF-8 independentemente da codificação local, e `tests/shared/test_logger.py` fixa isso no nível dos bytes.
  - **Alcance:** desenvolvimento local e qualquer captura de log feita no Windows. **Em produção, o defeito não se manifestaria:** a imagem `python:3.12-slim` define `LANG=C.UTF-8`, e o Python 3.7+ força UTF-8 em locale C no Linux (PEP 538/540). O que está em jogo é o mesmo que estaria em produção: uma linha de log com acentuação corrompida deixa de casar com termos acentuados no Logs Insights e no `scripts/logs-prod.sh`. Por isso a correção não depende do ambiente.

## Divergências aceitas

| Onde | develop | Python | Por que é aceita |
|---|---|---|---|
| Timeout do Bedrock | Sem timeout de requisição | 60 s de leitura do botocore | **Valor herdado do botocore, não escolhido.** 60 s é muito para quem espera no WhatsApp, mas ajustar seria mudança de produto disfarçada de migração |
| Retry da leitura do corpo nos GET ao Verde | Timeout lendo o corpo vira 500 | É retentado | Retentar leitura é inofensivo |
| Backoff do retry da IA | p-retry | tenacity | Mesmo número de tentativas; só a latência muda |
| `err.type` em erro do Bedrock | Nome da exceção do SDK | `ClientError` (a tradução usa o código AWS) | Nenhum painel nem alerta consulta `err.*` |

## Melhorias registradas, fora do escopo

- **Validação da saída estruturada da IA:** [#212](https://github.com/dgd-dprj/maria-langgraph-pp/issues/212), em dois passos (primeiro só medir, depois validar).
- **Mensagem interna no 500:** [#210](https://github.com/dgd-dprj/maria-langgraph-pp/issues/210). **Motivo no 400 de validação:** [#211](https://github.com/dgd-dprj/maria-langgraph-pp/issues/211).
- **Dupla contagem de tokens em subgrafo**, caracterizada e confirmada em develop (semente 150 termina em 300). É reproduzida como está; corrigir fica para depois do merge.
- **Retry de POST ao Verde:** develop reenvia os POST em 5xx e em timeout antes dos cabeçalhos. O `POST /encaminhamento/encaminhar` não tem proteção contra duplicidade (o Swagger do Verde não documenta chave de idempotência). Não retentar o encaminhamento depois de enviado, ou consultar antes de reenviar.
- **Consolidar os cinco pools Postgres** em um.
- **Consolidar as instâncias do `ChatBedrockConverse`**: hoje uma por módulo de IA.
- **Alerta do token do Verde:** o `verificar-token-verde.yml` falha todo dia por causa do token de release, e com isso deixou de alertar. Separar prod e release em execuções distintas.

## Decisões em aberto

1. **Major do Postgres de produção. Valor provisório: 16**, na imagem `pgvector/pgvector:pg16` do CI. A conferir com `SELECT version()` no RDS (do stack antigo). Se for outra, o ajuste é uma linha no `ci.yml`.
2. **Nome do schema do checkpointer. Valor provisório: `checkpoint_py`** (`SCHEMA_CHECKPOINT` em `shared/checkpointer.py`). O schema separado foi aprovado na #208, mas o nome não tinha sido definido.
3. **Threads `orquestrador:*` no corte:** decididas na issue do corte.
4. **Token do Verde em release:** pré-requisito do corte (detalhes na #208).

## Resultado do `langgraph.json` com fábrica

**Funciona.** Testado em 2026-10-09 com LangGraph CLI 0.4.33 (langgraph-api 0.15.4), no Windows (`langgraph dev` precisou do pacote `colorama` ali). Uma fábrica assíncrona (`async def criar_grafo(config)`) é registrada como assistant, e um run devolve o estado. O `langgraph.json` aponta para `criar_grafo` nos dois fluxos, mas esses arquivos só existem a partir do módulo `fluxos`: até lá, o Studio local não sobe.

## Pendências operacionais

- **Remover o worktree de captura.** As fixtures de contrato e a caracterização da dupla contagem foram gravadas num worktree destacado de `develop` @ `4e695f2`, registrado no git local de quem fez a captura (`git worktree list`). Ele é removido com `git worktree remove <caminho>` depois que as fixtures estiverem no primeiro commit de `migration` (feito na fundação) e o teste de caracterização (`caracterizacao-tokens-subgrafo.test.ts`, já copiado para fora do worktree) tiver sido traduzido no módulo `subgrafos`.
- **Build da imagem Docker** não pôde ser rodado na máquina da fundação: o Docker Desktop não inicia porque a virtualização está desativada ali (WSL2). A verificação passou para o job `imagem` do CI. Localmente, só foi possível simular a instalação da imagem (`uv sync --frozen --no-dev --no-editable` num diretório limpo, sem o código-fonte solto): o servidor subiu com `APP_ENV=production` e o `/health` respondeu 200.
