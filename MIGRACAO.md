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
| 1 | `fundacao` | #209 | mergeada (PR #213) |
| 2 | `persistencia` | #216 | mergeada (PR #218) |
| 3 | `integracoes` | #219 | em tradução |
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
- **Nível fixo das bibliotecas que carregam conteúdo do atendimento** (`BIBLIOTECAS_COM_NIVEL_FIXO` em `shared/logger.py`): `botocore`, `boto3`, `urllib3`, `s3transfer`, `httpx`, `httpcore` e `psycopg` ficam em WARNING com nível próprio, e não herdado. Em DEBUG, o botocore registra o corpo da chamada ao Bedrock (o prompt com o relato do cidadão, inclusive de vítimas de violência doméstica, e o texto dos embeddings), e o httpx registra a URL com `?cpf=`. Ninguém liga DEBUG em produção hoje, mas alguém pode ligar para depurar um incidente; com o nível fixo, baixar o nível raiz não libera essas bibliotecas. São três barreiras independentes: nível raiz em WARNING, nível fixo dessas bibliotecas e o filtro INFO do logger structlog. O teste simula o DEBUG global e falha se o nível fixo for removido.
- **Contexto** (`shared/contexto.py`): `get_config()` do LangGraph Python lança exceção fora de um run, enquanto o `getConfig()` do JS devolvia `undefined`. A exceção é absorvida para manter o contrato de nunca lançar.
- **Canal `tokensGastos`** (`shared/tokens_acumulados.py`): verificado contra o LangGraph instalado, um canal com reducer começa em `Tipo()`, e com `TypedDict` isso dá `{}`. Em develop, o default é `{input: 0, output: 0, total: 0}`. O canal usa uma subclasse de `dict` cujo construtor devolve esse valor, e o serializador do checkpointer a grava e lê como `dict` comum.
- **Checkpointer em schema próprio** (`shared/checkpointer.py`). O `setup()` do langgraph-checkpoint-postgres cria tabelas sem schema, com os mesmos nomes das tabelas do JS em `public` (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`), e as serializações são incompatíveis. Toda conexão do pool fixa `search_path` só no schema do Python. Os testes `postgres` provam que nada em `public` é tocado.
- **Ordem de inicialização:** o `setup()` do checkpointer e o schema de negócio rodam no lifespan, nessa ordem. O uvicorn só abre o socket depois do lifespan. `tests/test_app.py` prova a sequência com o uvicorn de verdade: enquanto a inicialização está bloqueada, a conexão é recusada. Se a inicialização falhar, o processo sai com código 3, e o ECS recria a task.
- **Pools Postgres criados num único lugar** (`shared/pool.py`, função `criar_pool`), que todo pool do serviço usa: o checkpointer desde a fundação e as quatro stores a partir do módulo persistencia. Os parâmetros reproduzem o `pg` (pg-pool 3.14) de develop, e não os padrões do psycopg_pool:

  | | develop (`pg`) | padrão do psycopg_pool | usado |
  |---|---|---|---|
  | conexões ao iniciar | nenhuma | 4 | `min_size=0` |
  | máximo | 10 | `min_size` | `max_size=10` |
  | conexão ociosa fecha em | 10 s | 600 s | `max_idle=10.0` |
  | espera por conexão | pool cheio: sem limite; banco fora: erro devolvido a quem pediu | 30 s nos dois casos, depois `PoolTimeout` | `timeout=120.0` (provisório; ver achado abaixo) |
  | idade máxima da conexão | nenhuma | 3600 s | `max_lifetime=math.inf` |
  | transação por consulta | sim (cada `pool.query`) | não (transação implícita) | `autocommit=True` |
  | prepared statements | só statements sem nome | prepara depois de 5 execuções | `prepare_threshold=None` (desligado) |

  **Correção de um erro da fundação.** O checkpointer da fundação passava `prepare_threshold=0` com o comentário "evita prepared statements". No psycopg é o contrário: `0` prepara **toda** consulta já na primeira execução, e só `None` desliga. Prepared statements fazem o RDS Proxy fixar a sessão (pinning), o que tira a multiplexação do proxy compartilhado com o stack antigo. Corrigido no módulo persistencia: os parâmetros de conexão agora são fixos em `shared/pool.py` para todos os pools, e um teste impede a volta do `0`.

  O pool é criado fechado e aberto explicitamente (`await pool.open()`). Sem esses valores, cada pool seguraria conexões ociosas por 10 minutos no RDS Proxy compartilhado com o stack antigo, e o `timeout` do psycopg_pool precisou de tratamento à parte (achado abaixo). O valor do `timeout` leva comentário no código explicando os dois casos, para não ser "corrigido" numa revisão.
- **Tipos que admitem `null`:** `shared/types.py` tipa como `int | None` seis campos que o Verde pode devolver como `null` e que develop preserva (`DadosApenado.idPessoa`, `DadosProcesso.id`, `DadosPessoa.idPessoa`, `Plantao.id`, `ResultadoEncaminhamento.id`, `ResultadoCadastroPessoa.idPessoa`). Em TypeScript eram `number` e recebiam `null` em execução.

### Contrato HTTP

- Status, content-type e corpo de toda resposta, inclusive de erro, idênticos às fixtures de `tests/fixtures/contrato/`. Elas foram gravadas com a aplicação TypeScript de develop @ `4e695f2` rodando de verdade: 50 casos e as linhas de log de cada uma das 5 instâncias. A receita está anexada à #209. A comparação byte a byte acontece no módulo `api`.
- **Fixtures que refletem a store em memória, e não a de produção.** A captura rodou sem `DATABASE_URL`, como os testes de develop. Onde as duas stores divergem, a fixture registra o comportamento da memória:
  - **`ttl-confirmacao-200`**: depois de confirmar "quer continuar?", a store em memória devolve a resposta pendente, e a fixture mostra o fluxo avançando com ela. **Em produção, a store Postgres devolve `NULL`, e a resposta da pessoa é descartada** ([#217](https://github.com/dgd-dprj/maria-langgraph-pp/issues/217)). A fixture é contrato da store em memória; não serve de prova do comportamento de produção nesse caminho.
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

- **Tempos do pool Postgres (encontrado e corrigido antes do merge da fundação).** A primeira versão da fundação fixava só `min_size` e `max_size`, e herdava do psycopg_pool a ociosidade de 600 s, a espera de 30 s e a reciclagem de 3600 s, onde develop tem 10 s, espera sem limite e nenhuma reciclagem. Apareceu na releitura da spec de persistencia contra a fundação. Corrigido com `shared/pool.py` (ver Decisões registradas).
- **Logs de biblioteca em INFO: dado pessoal que nenhum código nosso escrevia (encontrado e corrigido antes do merge da fundação).** A ponte do logging padrão deixava passar o INFO de qualquer biblioteca. O httpx registra em INFO cada requisição com a URL completa, e `verde.ts:291` monta a consulta de pessoa como `/pessoa?cpf=…`. A partir do módulo integracoes, **todo CPF consultado iria para o CloudWatch de produção**, violando a regra escrita do repositório (nunca registrar dado sensível em log), sem que ninguém fizesse nada errado: a biblioteca registra sozinha e a ponte deixava passar. O psycopg_pool, pelo mesmo caminho, registraria cada conexão entregue. A ponte agora deixa passar só WARNING ou mais para bibliotecas, e mantém INFO só para o uvicorn (linhas de inicialização). Teste: `tests/shared/test_logger.py`.
  - **A lição vale mais que a correção.** As revisões da migração olhavam o que o nosso código registra, nunca o que as bibliotecas registram por conta própria. **Regra a partir daqui: toda dependência nova entra com a pergunta "o que ela registra por padrão, em que logger e em que nível?"**, respondida no PR que a introduz. Com o filtro atual, um INFO de biblioteca já não sai; um WARNING ou ERROR sai, e precisa ser conferido também. A mesma pergunta vale para as exceções que o nosso código registra em `err`: algumas carregam a URL na mensagem (no httpx, o `HTTPStatusError` do `raise_for_status`), e a URL do Verde pode ter `?cpf=`.

- **Parâmetro com o mesmo nome e semântica diferente entre bibliotecas: o `timeout` do pool (encontrado e corrigido no módulo persistencia).** A fundação usou `timeout=math.inf`, aprovado com um raciocínio **correto sobre o pool cheio** (o `pg` espera sem limite, e o padrão de 30 s transformaria espera em erro) e **errado sobre a falha de conexão**, porque o psycopg_pool junta os dois casos num parâmetro só. O que separou os dois foi ler o pg-pool 3.14 de develop, e não o psycopg_pool. **É o tipo de erro que se repete nesta migração:** a tradução de parâmetro de uma biblioteca para a outra deve conferir a semântica nos dois lados, caso a caso, e não pelo nome. O mesmo aconteceu com o `prepare_threshold=0` (acima).

  | Caso | `pg` (pg-pool 3.14, develop) | psycopg_pool com `timeout=inf` |
  |---|---|---|
  | Pool cheio, banco no ar | espera sem limite na fila (`connectionTimeoutMillis` = 0) | espera sem limite: **igual** |
  | Banco fora do ar | a conexão é aberta no contexto de quem pediu (`newClient`), e o erro de conexão vai direto para quem pediu (`pendingItem.callback(err)`), sem nova tentativa | a conexão é aberta em segundo plano, com novas tentativas por até `reconnect_timeout` (300 s), e quem pediu **não é avisado**: espera para sempre |

  Medido com uma porta sem servidor: conexão direta falha em 2,1 s; o pool com `timeout=inf` ainda esperava depois de 20 s (o teste cortou); com `timeout=30`, `PoolTimeout` em 30 s. Com `inf`, uma falha de conexão deixa a requisição pendurada, sem erro e sem resposta ao cidadão, e a única pista são warnings em segundo plano ("error connecting in 'pool-N'"). Com a instabilidade já registrada na #196, esse caminho tem chance real de ocorrer. **O `inf` reproduz o `pg` só no primeiro caso e introduz comportamento novo no segundo.**

  **Decisão: `timeout=120.0`, provisório** (decisão em aberto na #208). É o padrão da AWS para o `ConnectionBorrowTimeout` do RDS Proxy, a melhor aproximação disponível do prazo em que o `pg` erraria em produção, onde a conexão passa pelo proxy. **Não é a resposta exata:** o `ConnectionBorrowTimeout` governa o empréstimo quando as conexões do proxy estão todas ocupadas, que não é exatamente o caso de banco indisponível; e a configuração real do proxy, que é do stack antigo, não foi conferida (o valor fica no grupo de destinos, `describe-db-proxy-target-groups`). O custo da escolha: com o pool cheio por mais de 120 s, o psycopg_pool erra onde o `pg` esperaria. Isso exige 10 consultas presas ao mesmo tempo no mesmo pool, o que com consultas de milissegundos é cenário teórico; o caso do banco fora é real. Um teste impede a volta do `inf`.

## Regra de tradução de estado (vale para subgrafos, fluxos e orquestrador)

**Onde develop devolve, como atualização de estado, um objeto com uma chave cujo valor é `undefined`, o Python escreve a chave com `None`. Nunca omite.**

- **develop:** o LangGraph JS 1.4.12 grava o `undefined` no canal. O `_getUpdates` (`graph/state.js`) usa `Object.entries`, que mantém a chave, e o `LastValue.update` guarda o valor.
- **Python:** no LangGraph 1.2.14, omitir a chave mantém o valor anterior, e `None` sobrescreve. Verificado com um grafo de dois nós: o primeiro grava `tokens: 18`; o segundo omite `tokens`, e o estado final continua com 18; com `tokens: None`, o estado final fica com `None`.
- **Por que importa:** é diferença silenciosa. Omitir deixaria no estado o valor do passo anterior (o texto da pergunta anterior, os tokens dela) e o sistema exibiria a pergunta errada, sem erro nenhum.
- **Onde aparece:** o `prepararPergunta` (achado T1 do ia) é devolvido direto pelos nós "preparar" de todos os fluxos. Também `{ ...preparado, rg: undefined }` em `pessoaPresa/graph.ts:222`, e qualquer `return { campo: algo?.x }` de nó.
- **A distinção que a tradução precisa fazer:** chave **ausente** no objeto JS (não escrita, como `...(x !== undefined ? {x} : {})`) continua ausente; chave **presente com `undefined`** vira `None`. Os auxiliares de `shared/_js.py` já separam os dois casos: `AUSENTE` é o undefined que não vira chave, `None` é o null.
- **Como testar:** cada nó traduzido que devolve chave com `undefined` em develop tem um teste que roda dois passos e confere que o valor do primeiro não sobrevive ao segundo.
- **Limite da regra (aprovado em 2026-10-14): `None` nas chaves do canal; chave ausente dentro de objetos aninhados.** O que decide é como o JS chega ao JSON e ao checkpoint. No canal, o `undefined` é gravado e a chave permanece. Dentro de um objeto que vira JSON, ele desaparece. São dois comportamentos do mesmo valor, e tratá-los igual erraria em um dos dois.
  - **Onde apareceu:** o `endereco` do subgrafo `coletarEndereco`, enviado inteiro no POST `/pessoa`. O `JSON.stringify` remove as chaves `undefined` (o `complemento` quase sempre é). Gravar `None` faria o Verde receber `"complemento": null`.
  - **Em código:** dentro de objeto aninhado, a chave com `undefined` não é escrita (`AUSENTE` com `_js.definir`).
  - **Como testar:** o objeto é conferido no ponto em que vira JSON. No subgrafos, é o corpo do POST, passando pelo `cadastrar_pessoa` real com o transporte falso.

## Divergências aceitas

| Onde | develop | Python | Por que é aceita |
|---|---|---|---|
| Timeout do Bedrock | Sem timeout de requisição | 60 s de leitura do botocore | **Valor herdado do botocore, não escolhido.** 60 s é muito para quem espera no WhatsApp, mas ajustar seria mudança de produto disfarçada de migração |
| Retry da leitura do corpo nos GET ao Verde | Timeout lendo o corpo vira 500 | É retentado | Retentar leitura é inofensivo |
| Backoff do retry da IA | p-retry | tenacity | Mesmo número de tentativas; só a latência muda |
| Resposta Converse sem `usage` | `viaIA: true`, sem tokens | `KeyError` no `langchain-aws`: 3 tentativas e fallback | **Aceita (2026-10-14).** O caminho só existe se a AWS violar o próprio contrato (`usage` é obrigatório na resposta Converse), e reproduzir develop exigiria interceptar a resposta dentro da biblioteca: código frágil para um cenário que não deveria acontecer. O teste 5b é a proteção |
| Espera entre tentativas do SDK (Bedrock) | 100 ms de base (500 ms no throttling), com teto de 20 s | botocore: 1 s de base, com teto de 20 s | Mesmo número de requisições. Medido nos embeddings (#222), separando o tempo por camada: o SDK Python espera cerca de **40 s a mais por mensagem** (75 s contra 37 s no 429; 40 s contra 4 s no 500). **Correção de 2026-10-14:** esta linha dizia "14,7 min contra 12,6"; a diferença entre os totais vem quase toda do sorteio das esperas dos callers, que varia dezenas de segundos entre execuções. A referência para corrigir a #222 é a faixa medida, de 12,5 a 14,7 min |
| `err.type` em erro do Bedrock | Nome da exceção do SDK | `ClientError` (a tradução usa o código AWS) | Nenhum painel nem alerta consulta `err.*` |
| Linha de log em falha de embedding | `console.error({ error: e })` cru no stderr, fora do pino, uma vez por chamada ao SDK (49 por consulta com o Bedrock fora, #222) | O `langchain_aws` registra em ERROR "Error raised by inference endpoint", com traceback, também uma vez por chamada ao SDK | **Corrigido em 2026-10-13:** este registro dizia que develop não tinha linha nenhuma, e tinha. A diferença é só de formato (envelope JSON contra objeto cru). A ponte deixa passar ERROR de propósito. A linha carrega a mensagem do Bedrock, que é a rota 2 da #220. O INFO de cada chamada ("Successfully invoked model…", só metadados) é barrado pelo nível fixo |

## Módulo persistencia (#216)

- **Quatro stores traduzidas** (`atendimentos_db`, `perguntas_db`, `fluxos_planejados_db`, `embeddings_fluxos`), com o SQL **textualmente igual** ao de develop, salvo a sintaxe de parâmetro: 34 instruções conferidas por script, byte a byte, depois de normalizar `$n`, `%s` e `%(nome)s`. Onde develop reutiliza o mesmo `$n`, a tradução usa parâmetros nomeados.
- **Divergências entre a store em memória e a Postgres, mantidas porque develop é assim:**
  1. `concluir` em memória grava só `statusFinal`; o Postgres grava também `destino`, `motivo_handoff`, `tokens_*` e `concluido_em`.
  2. `resolver_confirmacao_ttl_continuar` devolve a resposta pendente em memória e `None` no Postgres: **defeito de produção, [#217](https://github.com/dgd-dprj/maria-langgraph-pp/issues/217)**, fixado por teste com comentário apontando para a issue.
  3. `listar_perguntas_por_flow` ordena por `ordem` no Postgres e mantém a ordem de inserção em memória.
  4. `listar_fluxos_planejados` ordena por `id` no Postgres (`ORDER BY id`) e mantém a ordem de inserção em memória. Encontrada na tradução; não estava na spec.
- **`fechar_*()` em cada store**, chamado no `finally` do lifespan (`FINALIZADORES` em `app.py`): o pytest-asyncio cria um event loop por teste, e um pool memoizado de outro loop quebraria. Em develop, os pools nunca eram fechados.
- **Embeddings:** um cliente `BedrockEmbeddings` por chamada, com o ambiente lido na hora, como develop. A troca de `\n` por espaço é feita antes da biblioteca, porque o `langchain-aws` Python troca `os.linesep`, que no Windows é `\r\n`. O corpo enviado é `{"inputText": ...}`, sem `dimensions` nem normalização, igual ao JS. O embedding falso de teste soma code units UTF-16, conferido contra um vetor calculado com o `charCodeAt` do JS.
- **Logs de dependência (regra deste documento) para `langchain-aws`:** o próprio `langchain_aws` registra INFO de metadados a cada chamada e ERROR com traceback em falha; `boto3`/`botocore` registram em DEBUG o corpo da requisição, com o texto do embedding; `urllib3` e `s3transfer` vêm junto. Todos ficam com nível fixo em WARNING (`BIBLIOTECAS_COM_NIVEL_FIXO`). O ERROR do `langchain_aws` passa e está nas divergências aceitas.

## Módulo integracoes (#219)

- **Conexões simultâneas ao Verde sem limite (`max_connections=None`): limite ausente que ninguém escolheu.** O `fetch` de develop usa o pool global do undici, sem limite de conexões por origem, e a tradução reproduz isso no lugar do padrão de 100 do httpx. Nem em develop nem aqui alguém decidiu esse valor. O Verde é sistema da Defensoria com capacidade desconhecida, e o teto prático de chamadas simultâneas hoje vem do número de atendimentos simultâneos, não da biblioteca. **Aceito por fidelidade, não por desenho.** Se o Verde precisar de proteção, isso é decisão de produto, a tomar depois da migração.
- **Prazo de conexão de 10 s, como o undici** (terceiro caso do padrão "parâmetro com nome familiar e semântica diferente", comentário 12 da #208). O `fetch` aborta a abertura da conexão em 10 s (`connectTimeout` do undici), bem antes do `AbortSignal` de 30 s. Medido no Node 24.21: 10,8 s. A tradução usa `httpx.Timeout(connect=10.0)`. Sem isso, com as 3 tentativas, um Verde que não aceita conexão levaria 90 s para virar falha de infra, contra cerca de 30 s em develop.

- **Achados da tradução, além do que a spec previa** (spec e #219 atualizadas antes do PR):
  1. `dados` como objeto, ou item `null` na lista de órgãos e de plantões, gera `TypeError` e 500 em develop (`verde.ts:479`, `:517`). A tradução lança nos mesmos casos.
  2. O 1º item `null` de `messages` ou `statuses` do WhatsApp lança `TypeError` em develop (`whatsapp.ts:81`, `:115`). A spec dizia que a extração nunca lançava.
  3. No corpo enviado ao Verde, `undefined` é chave ausente e `None` é `null`: **nada é removido antes de serializar**. A spec mandava remover `None` recursivamente, o que mudaria o envio de um `null` vindo do próprio Verde. Os módulos de cima devem representar o `undefined` de develop como chave ausente no estado, e não como `None`.
- **Semântica de JS num auxiliar único** (`shared/_js.py`; nasceu em `integracoes/` e foi movido para `shared/` antes do ia, que precisa da mesma semântica): `prop` (`o.k`, que lança em null), `opt` (`o?.k`), `coalesce` (`??`), `verdadeiro` (`{}` e `[]` são verdadeiros), `texto_template` (`${v}`: `true`, `null`, `undefined`) e `json_parse`/`json_stringify` com as regras do JSON de JS.
- **Verificação por mutação:** a tradução ingênua de cada divergência (redirect, prazo de conexão, `True` na query, escape, POST com o corpo lido dentro do retry, remoção recursiva de `None`) foi aplicada no código, e o teste correspondente falhou em todos os casos.
- **Corpo da resposta do Verde no log (comportamento de develop, reproduzido; em avaliação).** Em develop, o encaminhamento e o cadastro registram o corpo da resposta do Verde no sucesso e na falha (`verde.ts:645`, `:651`, `:718`, `:725`; `campo corpo`). No sucesso, pelo formato documentado, ele não tem dado pessoal. Na falha, é `{codigo, mensagem}` escrito pelo Verde, e **não foi verificado se alguma mensagem de erro do cadastro repete o CPF ou o nome enviados**. Apontado pela revisão automática de segurança dos commits. Reproduzido como em develop; a medição nos logs reais (sucesso e falha) e a decisão estão na [#220](https://github.com/dgd-dprj/maria-langgraph-pp/issues/220). **É a segunda rota de dado pessoal para o log encontrada na migração:** a primeira foi uma biblioteca registrando sozinha (achado "Logs de biblioteca em INFO", resolvido com `BIBLIOTECAS_COM_NIVEL_FIXO`); esta é o nosso código registrando a resposta de um terceiro, e o filtro de nível não a cobre, porque a linha sai pelo logger da aplicação. Para essa rota, a proteção só pode estar no que se decide registrar.

## Correção do persistencia antes do ia: retry do Bedrock (2026-10-13)

A releitura da spec do ia encontrou uma divergência **já mergeada** na `migration` (persistencia, `b2e7d7f`). Ela foi corrigida antes da tradução do ia, no primeiro commit da branch do módulo.

- **develop:** o `BedrockEmbeddings` do JS empilha três camadas de retry: dois `AsyncCaller` com 6 retentativas cada (`embeddings.js:108` e `:73`) e o SDK com 3 tentativas. Com o Bedrock falso falhando sempre, foram 49 requisições (400), 147 (429) e 99 (500), com cerca de 13 minutos até desistir. Ninguém escolheu esses números: é defeito de produção, [#222](https://github.com/dgd-dprj/maria-langgraph-pp/issues/222).
- **`migration` antes da correção:** nenhum caller, e o boto3 em modo `legacy` (5 tentativas): falha em segundos. **Diverge de develop**, e a régua é develop.
- **Correção:** `shared/bedrock.py` (`CONFIG_BOTOCORE`, `cota_como_sdk_js`, `chamar_como_async_caller`), usado pelo persistencia agora e pelo ia na tradução. O teste `tests/shared/test_bedrock.py` fixa 49, 147 e 99 contra um Bedrock falso local.

**Dois casos novos do padrão "parâmetro com nome familiar e semântica diferente"** (o quarto e o quinto foram encontrados juntos; o sexto, na medição):
- **Quarto, "retry":** no JS, retry existe em três camadas, e no Python, em uma só. O `BedrockEmbeddings` Python não tem caller.
- **Quinto, `max_attempts`:** no botocore, `max_attempts` conta as **retentativas**, e `max_attempts: 3` dá 4 requisições. O total de tentativas fica em `total_max_attempts`. A spec do ia prescrevia `max_attempts: 3`. **O erro estava na spec**, e o teste que conta requisições pegou.
- **Sexto, cota de retentativas:** os dois SDKs têm uma cota de 500 fichas por cliente. O SDK JS cobra 10 por retentativa de 5xx; o botocore cobra 5 e reserva o 10 para timeout. Com 500 persistente, isso dá 99 requisições contra 147. A tradução troca a cota do cliente pela do JS (`cota_como_sdk_js`).

No mesmo preparo, também aprovado na releitura:
- `_js.py` sai de `integracoes/` e vai para `shared/`;
- `langsmith` entra em `BIBLIOTECAS_COM_NIVEL_FIXO`, porque já vem instalado, como dependência transitiva do `langchain-core`, na versão 0.14.7;
- `botocore-stubs` entra só no grupo `dev`, para o mypy strict.

A lição repete a do `timeout` do pool: **contar o efeito (requisições, tempo) contra develop pega o que a leitura do nome não pega.** Os três casos só apareceram porque o teste conta requisições num servidor falso.

**O padrão já contaminou a nossa própria especificação.** O `max_attempts: 3` não foi erro de tradução: estava escrito na spec do ia, revisada e aprovada. A spec descreve a configuração, e a configuração tem o mesmo problema de nome que a biblioteca. **Contar requisições vale mais que confiar na configuração**, inclusive na que nós mesmos escrevemos. Regra para os próximos módulos: todo parâmetro de retry, prazo ou limite traduzido tem um teste que mede o efeito (requisições contadas num servidor falso, tempo medido) contra o número de develop, e não um teste que só confere o valor passado à biblioteca.

## Módulo ia (#223)

- **Seis funções em `src/maria/ia/`**, sobre um núcleo comum (`_estruturado.py`) que reproduz o `withStructuredOutput(schema, {includeRaw: true}).withRetry({stopAfterAttempt: 3})` do `@langchain/aws` 1.4.4. A saída **não é validada** (#212): os `args` da ferramenta passam como vieram, e a falha de parse vira `parsed: None` sem disparar retry.
- **Requisição Converse idêntica à de develop**, conferida por teste contra as 7 fixtures capturadas de develop (`tests/fixtures/ia/`), incluindo a ordem das chaves. Duas diferenças do `langchain-aws` 1.8.2 foram neutralizadas:
  1. ele manda `"inferenceConfig": {}` quando não há temperatura nem `maxTokens`, e develop não manda a chave. A subclasse `_ConverseComoDevelop` remove o dicionário vazio;
  2. o `bind_tools` reordena o `toolSpec`. O `toolConfig` vai pronto via `bind(tool_config=...)`, que o `langchain-aws` usa sem reformatar.
- **Achados da tradução, além do que a spec previa** (spec e #223 atualizadas antes do PR):
  1. **`undefined` gravado no estado** (virou regra geral: ver "Regra de tradução de estado"). O `prepararPergunta` é devolvido direto como atualização de estado, e o LangGraph JS grava `undefined` no canal (`Object.entries` mantém a chave; o `LastValue` guarda o valor). Em Python, `perguntaAtualTokensTotal` e `perguntaAtualTexto` vão **com `None`**, e não omitidos: omitir manteria o valor da pergunta anterior. As demais funções são desestruturadas pelos chamadores, e as chaves ausentes continuam ausentes, como diz a spec. **Regra para os módulos `fluxos` e `orquestrador`:** onde develop devolve um objeto com chave `undefined` como atualização de estado, o Python escreve `None`.
  2. **`extrair` com resposta sem ferramenta não cai no fallback.** Espalhar `null` em JS não lança erro: o resultado é `{viaIA: true, ...tokens}`. Os campos próprios (`viaIA`, `tokens*`) sobrescrevem os do modelo. Os dois comportamentos foram confirmados em develop com o Bedrock falso.
  3. **Resposta sem `usage`: divergência aceita (2026-10-14).** develop devolve `viaIA: true` sem tokens; o `langchain-aws` Python lança `KeyError('usage')`, a chamada é retentada 3 vezes e cai no fallback. O caminho só existe se o Bedrock violar o contrato: `usage` é obrigatório na resposta Converse (`ConverseResponse.required` no modelo de serviço do botocore). O teste 5b fixa o comportamento do Python. Reproduzir develop exigiria interceptar a resposta dentro do `langchain-aws`.
  4. **`err.message`** dos logs de falha é a mensagem do Bedrock (`response["Error"]["Message"]`), como o `e.message` do SDK JS, e não o `str(ClientError)` do botocore. O `err.type` é o código AWS (decisão pendente 1 da spec, valor provisório).
- **Verificação por mutação: 10 de 10 pegas**: validação estrita, cliente sem `Config`, `max_attempts`, `usage_metadata` com `getattr`, parse sem `include_raw`, modelo fora da cota do SDK JS, `inferenceConfig` vazio mantido, `bind_tools`, `prepararPergunta` omitindo a chave e `extrair` caindo no fallback. A primeira versão da última mutação estava mal escrita: acrescentava uma chave a todo `parsed` e fazia falhar o teste errado. Foi corrigida antes de aceitar o resultado.
- **Logs de dependência (regra deste documento):** nenhuma dependência nova de runtime. O `langchain_aws` registra em DEBUG a mensagem e o system prompt enviados ao Bedrock (`bedrock_converse.py`, "input message to bedrock"); fica barrado pelo nível fixo em WARNING. O `langsmith` e o seu cliente HTTP (`httpx2`, `httpcore2`) também estão no nível fixo.

## Módulo subgrafos (#233)

- Spec com duas medições feitas antes da tradução:
  - a soma de tokens composta (#230);
  - o `endereco` que vira JSON (o limite da regra de estado).
- Diferenças de texto entre JS e Python tratadas por funções únicas em `shared/`:
  - o `trim()` do JS remove U+FEFF e não remove `\x1c` a `\x1f`, o oposto do `strip()`;
  - o `\D` sem a flag `u` só reconhece `0-9` ASCII;
  - o complemento não usa NFD.

## Técnica a repetir nos próximos módulos: verificação por mutação

Um teste que passa prova que o código faz o esperado no caso testado. Não prova que o teste **pegaria** a tradução errada. Para cada divergência que a spec do módulo trata (o lugar onde a tradução ingênua muda o comportamento), aplique no código a versão ingênua, rode o teste correspondente e confirme que ele **falha**. Depois, restaure o código.

- Usado no módulo integracoes: redirect, prazo de conexão, `True` na query string, escape de URL, POST com o corpo lido dentro do retry (encaminhamento e apenado) e remoção recursiva de `None`. Os sete testes falharam com a mutação.
- **Se a mutação passar, examine a mutação antes do teste.** No integracoes, a primeira versão da mutação de `None` removia só no primeiro nível, e o `null` do teste estava aninhado. A mutação estava errada, não o teste. Corrigir o teste para "pegar" uma mutação mal escrita seria enfraquecê-lo.
- O script é descartável (não entra no repositório), mas a lista de mutações e o resultado vão para a issue ou para o PR do módulo.

## Melhorias registradas, fora do escopo

- **Validação da saída estruturada da IA:** [#212](https://github.com/dgd-dprj/maria-langgraph-pp/issues/212), em dois passos (primeiro só medir, depois validar).
- **Mensagem interna no 500:** [#210](https://github.com/dgd-dprj/maria-langgraph-pp/issues/210). **Motivo no 400 de validação:** [#211](https://github.com/dgd-dprj/maria-langgraph-pp/issues/211).
- **Contagem de tokens em subgrafo: [#230](https://github.com/dgd-dprj/maria-langgraph-pp/issues/230).** A soma se compõe. Com a semente 150, o resultado é 300 com um subgrafo (2×), 450 com o aninhado (3×) e 900 com identificação seguida de cadastro (6×), medido em develop e no LangGraph Python. O custo registrado de violência doméstica com cadastro é 6× o real, e o fator muda de fluxo para fluxo. A tradução reproduz o comportamento; a correção vem depois, na base em Python.
- **Endereço do cadastro não chega à Tykhe: [#231](https://github.com/dgd-dprj/maria-langgraph-pp/issues/231).** O encaminhamento não é afetado.
- **Falha de infra no CEP vira "não encontrado": [#232](https://github.com/dgd-dprj/maria-langgraph-pp/issues/232).** É o mesmo mecanismo da #196.
- **Subgrafos (achados A4 a A6 da spec):**
  - "Confirma que seus dados são: você?" quando o Verde não traz o nome;
  - nenhuma validação de CPF, data de nascimento, CEP ou UF;
  - `respostaEhSim` copiada em 4 arquivos, enquanto o complemento normaliza sem NFD.
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
