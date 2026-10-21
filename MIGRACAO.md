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
  - **O servidor também, a partir da #260 (decisão de 2026-10-20, melhoria sobre develop).** O uvicorn 0.54 escolhe o `ProactorEventLoop` no Windows por conta própria e ignora a política global, então `uv run python -m maria.main` com `DATABASE_URL` não subia no Windows. Ninguém conseguia rodar o ambiente completo, com banco, em Windows; os guias rodam sem banco e não pegavam isso. O `main.py` passa `loop="asyncio:SelectorEventLoop"` no Windows e `"auto"` nos outros sistemas. **Produção não muda.** Develop não tem o problema, porque o Node não tem esse loop: por isso é melhoria, fora da régua por decisão.
- **Sem permissão de `CREATE` no banco, a subida diz o que falta (#260, decisão de 2026-10-20, melhoria sobre develop).** O `CREATE SCHEMA checkpoint_py` é o primeiro comando de um deploy num banco novo. Sem `CREATE`, a task sai com código 3 e o ECS a recria em laço, e o erro ficava no fim de um traceback. Agora sai antes uma linha `[checkpoint]` de nível error, com `schema`, `banco`, `usuario`, `permissao` e o `GRANT` sugerido, **nunca a URL**, que contém a senha. O código de saída continua 3. Develop sobe com o mesmo requisito: o `setup()` do JS executa `CREATE SCHEMA IF NOT EXISTS "public"` em toda subida e morre sem `CREATE` (executado em 2026-10-20, Postgres 16 e 12).

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

- **`undefined` × `null` (2026-10-14, #208):** Python não tem dois vazios.
  - **Critério:** num canal que **nunca foi escrito**, a chave não aparece no estado Python. Verificado no LangGraph 1.2.14, no pai e no subgrafo. Disso saem três casos:
    - canal em que develop nunca grava `undefined`: a **ausência da chave** é o `undefined`, e `None` é o `null`; os guardas usam a presença da chave;
    - canal em que develop grava `undefined` e o `null` não entra: `None` é o `undefined`;
    - canal em que develop grava `undefined` **e** o `null` entra: **conflito**, decidido caso a caso na spec do módulo.
  - **Portas de entrada do `null`:** só três, a Tykhe (`dadosConhecidos`, #240), o Verde e o modelo (#212).
  - **Regra de fechamento:** onde a tabela diz que o `null` não entra, ela diz **por quê** e **o que mudaria** se ele passasse a entrar. Tabela sem justificativa envelhece mal.
  - **Lição do `idPessoa`:** a regra do objeto aninhado não estava errada; estava **incompleta**. Foi escrita olhando o `endereco`, onde o `null` não entra, e aplicada à resposta do Verde, onde entra. A regra completa: dentro de objeto aninhado, `undefined` vira chave ausente e `null` continua `null`. A correção do `cadastro_pessoa` e do bypass do CPF (código mergeado em `80de7bb`) está em `d5e5965`.

## As respostas gravadas são evidência, não teste de regressão (decidido em 2026-10-20)

**Não edite nada em `tests/fixtures/contrato/`.** Nem quando um teste falhar por causa de uma mudança legítima de contrato.

- **O que elas são:** respostas HTTP e linhas de log gravadas com a versão TypeScript rodando de verdade (as 50 da #209, gravadas em develop @ `4e695f2`, e as das conferências do `api`). Elas **provam que o Python devolve o que o TypeScript devolvia**. É evidência da tradução, e tem valor só enquanto for exatamente o que o servidor real devolveu.
- **Por que não editar:** a versão TypeScript não existe mais para regravar. Uma fixture editada à mão deixa de ser observação e passa a ser opinião. Depois de três edições, ninguém sabe mais o que veio do servidor real e o que foi escrito. A evidência some sem aviso.
- **O contrato atual é conferido por testes escritos:** asserções explícitas sobre status, corpo e campos, como as de `tests/api/test_app.py`. Uma mudança de contrato muda o teste escrito, e o PR diz por quê.
- **Quando uma mudança legítima quebra a conferência contra a fixture** (o primeiro caso conhecido é um fluxo novo mudando `GET /fluxos`, achado C7 da spec 09): o caso sai da conferência, sem tocar na fixture, e o comportamento novo ganha um teste escrito. O mecanismo para tirar o caso da conferência (por exemplo, uma lista de casos aposentados, com o motivo e o PR de cada um) é definido no primeiro PR que precisar dele. A fixture continua no repositório, intacta.

## Divergências aceitas

| Onde | develop | Python | Por que é aceita |
|---|---|---|---|
| Timeout do Bedrock | Sem timeout de requisição | 60 s de leitura do botocore | **Valor herdado do botocore, não escolhido.** 60 s é muito para quem espera no WhatsApp, mas ajustar seria mudança de produto disfarçada de migração |
| Retry da leitura do corpo nos GET ao Verde | Timeout lendo o corpo vira 500 | É retentado | Retentar leitura é inofensivo |
| Backoff do retry da IA | p-retry | tenacity | Mesmo número de tentativas; só a latência muda |
| `rg` com `null` vindo da Tykhe (fluxos, #241) | `rg !== undefined`: pula a primeira pergunta; `""` falha no formato e ele pergunta "O RG deve conter apenas números…" | `None`: faz a pergunta normal do RG | **Colapso de `undefined` e `null` em `None` num canal que recebe escrita externa:** develop grava `undefined` em `rg` (`prepararPerguntaRgInvalido`) e a Tykhe pode mandar `null`. Só acontece se a Tykhe mandar `rg: null`; a #240 vai restringir os campos. **Se o `null` passar a entrar,** muda só o texto da primeira pergunta do RG. **Correção de 2026-10-14:** esta linha dizia que develop "consulta `""`" no Verde; a conferência diferencial mostrou que não consulta |
| `encaminhamentoId` com `"id": null` vindo do Verde (fluxos, #241) | conclui com "Protocolo: null." | `falha_encaminhamento` | Mesmo colapso: develop grava `undefined` (sucesso sem `dados.id`) e o Verde poderia mandar `null`. A Swagger declara `id` inteiro, e não há registro de `null`. **Ir para falha evita mostrar um protocolo inválido à pessoa atendida**, o mesmo problema da #238. **Se o `null` passar a entrar,** o desfecho é falha em vez de concluído |
| `resumo: null` vindo do modelo na sumarização (orquestrador, #244, spec 06 D-1) | (lido) guarda `null` em `resumoRelato`; o teste `=== undefined` falha e a classificação recebe `"null\n<última resposta>"`, sem o histórico anterior | `None` = `undefined`: trata como "ainda não sumarizou" e manda o histórico bruto | **Aceita (2026-10-16).** Mesmo colapso de `undefined` e `null` do `rg` e do `id`: develop grava `undefined` no canal (sumarização sem a chave) e o `null` entra pelo modelo (#212). O caminho exige que o modelo viole o schema (`resumo` é string obrigatória). O Python fica com o histórico, e develop o perde. **A confirmar na conferência diferencial**, como todo item (lido) |
| Contador com texto vindo da Tykhe (`tentativasCpf`, `tentativasRg`, `tentativasProcesso`; fluxos, #241, spec 05 D-1) | `(t ?? 0) + 1` concatena: `"x"` vira `"x1"`, a pergunta sai "tentativa x1 de 3", `"x1" >= 3` é falso e o atendimento segue com contagem sem sentido | `TypeError` no `+ 1`: **a rota responde 500** | **Aceita (2026-10-16).** **O Python falha mais cedo e mais alto que develop:** onde develop segue o atendimento com texto no lugar do número, o Python para na hora com 500. **Quem investigar um 500 vindo da Tykhe com `TypeError` num `tentativas*` está diante deste caso:** a Tykhe mandou texto, objeto ou lista num contador em `dadosConhecidos`. Motivos: a concatenação é acidente de tipagem fraca, não comportamento desenhado; o caminho exige que a Tykhe, cliente autenticado e não entrada de cidadão, viole o próprio contrato num campo numérico; e a falha visível é melhor que o atendimento seguindo com contagem sem sentido. Reproduzir o `+` e o `>=` do JS nos três contadores, incluindo o `identificar_assistido` mergeado, espalharia coerção frouxa pelo Python. A #240 elimina o caso na origem. `null`, número e booleano dão o mesmo resultado nos dois |
| `dadosConhecidos.tokensGastos` fora do formato `{input, output, total}` numéricos, vindo da Tykhe (api, #246, spec 07 D-5) | (executado) aceita e zera ou corrompe a contagem **em silêncio**: o `NaN` da soma vira `null` no checkpoint JSON e depois `0`; `"0x0"` vira `0` pelo `Number()`. O atendimento conclui com 200 | `TypeError` na criação do atendimento: **a rota responde 500** | **Aceita (2026-10-17), no molde do D-1 do fluxos. O Python falha mais cedo e mais alto que develop:** onde develop segue com a contagem de tokens corrompida, o Python para na criação com 500. **Quem investigar um 500 vindo da Tykhe com `TypeError` na soma de tokens está diante deste caso:** a Tykhe mandou `tokensGastos` com texto, lista, booleano ou objeto incompleto. Motivos: contagem corrompida em silêncio é pior que 500 visível; a Tykhe é cliente autenticado violando o próprio contrato; a #240 elimina o caso na origem. Com `null`, os dois lados já davam 500 (#210). São 17 cenários da conferência |
| Resposta Converse sem `usage` | `viaIA: true`, sem tokens | `KeyError` no `langchain-aws`: 3 tentativas e fallback | **Aceita (2026-10-14).** O caminho só existe se a AWS violar o próprio contrato (`usage` é obrigatório na resposta Converse), e reproduzir develop exigiria interceptar a resposta dentro da biblioteca: código frágil para um cenário que não deveria acontecer. O teste 5b é a proteção |
| Espera entre tentativas do SDK (Bedrock) | 100 ms de base (500 ms no throttling), com teto de 20 s | botocore: 1 s de base, com teto de 20 s | Mesmo número de requisições. Medido nos embeddings (#222), separando o tempo por camada: o SDK Python espera cerca de **40 s a mais por mensagem** (75 s contra 37 s no 429; 40 s contra 4 s no 500). **Correção de 2026-10-14:** esta linha dizia "14,7 min contra 12,6"; a diferença entre os totais vem quase toda do sorteio das esperas dos callers, que varia dezenas de segundos entre execuções. A referência para corrigir a #222 é a faixa medida, de 12,5 a 14,7 min |
| `err.type` em erro do Bedrock | Nome da exceção do SDK | `ClientError` (a tradução usa o código AWS) | Nenhum painel nem alerta consulta `err.*` |
| Linha de log em falha de embedding | `console.error({ error: e })` cru no stderr, fora do pino, uma vez por chamada ao SDK (49 por consulta com o Bedrock fora, #222) | O `langchain_aws` registra em ERROR "Error raised by inference endpoint", com traceback, também uma vez por chamada ao SDK | **Corrigido em 2026-10-13:** este registro dizia que develop não tinha linha nenhuma, e tinha. A diferença é só de formato (envelope JSON contra objeto cru). A ponte deixa passar ERROR de propósito. A linha carrega a mensagem do Bedrock, que é a rota 2 da #220. O INFO de cada chamada ("Successfully invoked model…", só metadados) é barrado pelo nível fixo |

## Módulo persistencia (#216)

- **Quatro stores traduzidas** (`atendimentos_db`, `perguntas_db`, `fluxos_planejados_db`, `embeddings_fluxos`), com o SQL **textualmente igual** ao de develop, salvo a sintaxe de parâmetro: 34 instruções conferidas por script, byte a byte, depois de normalizar `$n`, `%s` e `%(nome)s`. Onde develop reutiliza o mesmo `$n`, a tradução usa parâmetros nomeados.
- **Divergências entre a store em memória e a Postgres, mantidas porque develop é assim:**
  1. `concluir` em memória grava só `statusFinal`; o Postgres grava também `destino`, `motivo_handoff`, `tokens_*` e `concluido_em`.
  2. `resolver_confirmacao_ttl_continuar` devolve a resposta pendente em memória e `None` no Postgres: **defeito de produção, [#217](https://github.com/dgd-dprj/maria-langgraph-pp/issues/217)**, fixado por teste com comentário apontando para a issue. **Atualizado em 2026-10-14:** corrigido em develop pelo PR #226 e trazido para a `migration` na branch do fluxos (#241), com o SQL e os três testes de develop. As duas stores agora devolvem o mesmo valor.
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

- **Três subgrafos** em `src/maria/subgrafos/` (`identificar_assistido`, `cadastro_pessoa`, `coletar_endereco`), com os nomes de nó e de canal de develop. Os canais são compartilhados com os pais por nome, e os nomes em camelCase são o contrato.
- **Spec com duas medições feitas antes da tradução:**
  - a soma de tokens composta (#230): 2×, 3× e 6×, igual em develop e no LangGraph Python, sem código extra;
  - o `endereco` que vira JSON, que deu origem ao limite da regra de estado.
- **Diferenças de texto entre JS e Python, em funções únicas em `shared/`:**
  - `trim_js` em `_js.py`, porque o `trim()` do JS remove U+FEFF e não remove `\x1c` a `\x1f`, o oposto do `strip()`;
  - `resposta_eh_sim` em `respostas.py`, que substitui as quatro cópias de develop;
  - `[^0-9]` no lugar de `\D`, porque o `\D` do JS sem a flag `u` só reconhece `0-9` ASCII;
  - o complemento sem NFD, como em develop.
- **Regra de estado aplicada:**
  - `None` nos canais `complemento`, `logradouro`, `bairro`, `municipio` e `uf` quando develop grava `undefined`;
  - chave ausente dentro de `endereco` e do `dadosPessoa` do cadastro.
- **Testes:**
  - os 3 traduzidos de develop e 25 novos, ou 48 casos ao todo com as variantes parametrizadas;
  - o corpo do POST `/pessoa` conferido pelo `cadastrar_pessoa` real com o transporte falso, sem nenhum `null` dentro de `endereco`.
- **Conferência diferencial:** seis cenários do fluxo do CPF rodados no `identificarAssistido` de develop. O estado final bate com o que os testes afirmam: CPF conhecido, três tentativas, "não" ao retry, CPF digitado direto, falha de infra e confirmação.
- **Verificação por mutação: 8 de 8 pegas:**
  - `strip()` no lugar de `trim_js`;
  - `\D`;
  - normalização no complemento;
  - complemento omitido no canal;
  - `None` dentro de `endereco`;
  - `"opcoes": None` nos interrupts de texto;
  - subgrafo sem `tokensGastos` compartilhado;
  - bypass do CPF ignorando `tentativasCpf`.
- **Evidência do Verde (Swagger, 2026-10-14):**
  - `CadastrarPessoaDTO` tem `endereco` com os 7 campos enviados;
  - `GET /orgao/violencia-domestica` recebe só `indicacaoRO` e `idPessoa`, consulta pelo endereço cadastrado e devolve 422 sem endereço. Isso confirma que o encaminhamento não é afetado pela #231;
  - "CEP não encontrado" é HTTP 400 (#232).

## Limites conhecidos da verificação (2026-10-14, #208)

- **Decisão de 2026-10-20: a migração é validada por teste em homologação, e não por revisão humana de código.** O Ícaro aprova e mergeia. **A ausência de revisão humana foi decisão consciente, e não lacuna.** Quem avaliar a confiança da migração precisa saber o que foi feito e o que não foi:
  - **feito:** CI em todo PR (ruff, mypy strict, a suíte padrão, a suíte com Postgres e a imagem Docker); verificação por mutação em todos os módulos de código; conferência diferencial contra develop, cenário a cenário, nos dois lados; as respostas e os logs gravados de develop conferidos byte a byte; os guias de uso executados em pasta limpa; teste em homologação, com o roteiro de 4 casos rodado antes do merge na versão TypeScript, como linha de base, e depois na Python;
  - **não feito:** leitura do código por outra pessoa. O que isso deixa passar está no parágrafo abaixo, escrito antes da decisão e mantido como está.
- **Nenhum módulo teve revisão humana de código.** Vale para fundação, persistencia, integracoes, ia e subgrafos. As proteções são o CI, a verificação por mutação e a conferência diferencial contra develop. Elas pegam a tradução errada que alguém pensou em testar, mas não a premissa errada, o caminho que nenhum teste percorre ou o defeito que o próprio autor não enxerga. **Não substituem revisão humana.** Proposta: alguém do time revisa ao menos os módulos de grafo (`subgrafos`, `fluxos`, `orquestrador` e as rotas do `api`), de preferência antes do merge, olhando a regra de tradução de estado e os testes de "defeito reproduzido de propósito".
- **Lacuna de teste herdada do subgrafos:** o caminho "Verde devolve a pessoa sem `nome`", que produz "Confirma que seus dados são: você?" (#236), foi testado só na função que monta o texto. A verificar no módulo fluxos, de ponta a ponta: violência doméstica e pessoa presa, pelo orquestrador, com "Sim" e com "Não", conferindo contra develop. **Fechada no fluxos (2026-10-14):** os quatro casos foram conferidos contra develop, com resultado igual, e têm teste (`test_7_*` em `tests/fluxos/test_spec_fluxos.py`).

## Módulo fluxos (#241)

- **Base: develop @ `0aecd98`**, porque develop andou desde `4e695f2`:
  - **#226:** a correção da #217, trazida em `2403bab`;
  - **#234:** `shared/respostaSimNao.ts`. A `respostaEhSim` tem o mesmo comportamento, então os subgrafos mergeados continuam fiéis. A confirmação de TTL entra no módulo `api`;
  - **#229:** só documentação, com destino nos módulos documentacao e corte.
- **`metadadosSchema` não é traduzido.** Não tem nenhum consumidor em develop @ `0aecd98`, e a rota declara `metadados` genérico (`additionalProperties: true`). Seria código morto no Python.
- **Divergências aceitas:** `rg` e `encaminhamentoId` com `null`, e contador com texto vindo da Tykhe (D-1, aceita em 2026-10-16) (tabela "Divergências aceitas").
- **Tradução (2026-10-14):** `6713498` (código e os 74 testes de develop) e `c5c18e9` (74 testes novos da spec 05). Suíte local: 398 passando. Achados na seção 8 da spec 05 (`docs/migracao/specs/05-fluxos.md`).
  - **Conferência diferencial contra develop @ `0aecd98`:** 584 cenários, executados nos dois lados com o mesmo Verde (o mock do código ou um Verde falso local). Compara byte a byte as perguntas, os metadados e as requisições ao Verde. Resultado: 569 iguais, 3 divergências aceitas (`rg` e `id` com `null`) e 12 diferentes, todos do contador com texto (D-1, depois aceito como divergência).
  - **Varredura de pré-preenchimento (#240):** cada canal dos dois fluxos recebeu, pela entrada, `null`, texto, número, booleano, `{}`, `[]` e `""`. Foi assim que apareceram as duas correções abaixo e o D-1. A técnica está descrita mais abaixo, para repetir no orquestrador e no api.
  - **Código mergeado corrigido:** `cadastroErro: null` no `cadastro_pessoa` (`65a976a`). O teste passou a ser pela presença da chave, como manda a regra de estado, e a linha entrou na tabela 0.2.
  - **`_js.texto_template`** passou a reproduzir `${obj}` (`[object Object]`) e `${lista}` (`join(",")`) (`55eee00`).
  - **Verificação por mutação:** 27 mutações, todas pegas. As três que passaram na primeira rodada eram lacunas de teste e ganharam teste.
  - **Lacuna herdada do subgrafos ("Verde sem nome") fechada,** ponta a ponta, nos dois fluxos, com "Sim" e com "Não", igual a develop.
- **Diagramas nas issues da migração:** Mermaid no texto, com o guia de estilo do `diagram-specialist`, como o `docs/padroes-issues.md` de develop passou a recomendar (#229). O PNG no S3 fica para a documentação estável em `docs/`.

## Módulo orquestrador (#244)

- **Base: develop @ `1157a6d`**, com o #242 (#225) dentro. **A conferência diferencial roda contra essa base, e nunca contra `0aecd98`:** o catálogo caiu de 76 para 9 opções, e comparar com a base anterior seria comparar com um comportamento que não existe mais.
- **#242 no fluxos mergeado:** `tiposTykhe.ts` e o novo `catalogoParaClassificacao` entram em commit próprio no começo da branch, como o #226 no fluxos (spec 06, D-2). A parte de rota (`redirecionado`, `tipoCaso`, o bridge do WhatsApp) fica no `api`.
- **Divergência aceita:** `resumo: null` do modelo (D-1, tabela "Divergências aceitas").
- **Primeira spec escrita com a regra do desfecho:** toda afirmação sobre develop está marcada como (lido) ou (executado), e cada (lido) vira cenário da conferência diferencial antes do PR.
- **A varredura muda de porta:** aqui a Tykhe não pré-preenche o estado. As portas varridas são a saída do modelo (`idsPlausiveis`, `pergunta`, `resumo`) e a pergunta raiz do banco.
- **`ORQUESTRADOR_INCLUIR_PLANEJADOS`: vale o padrão do código, desligada** (verificado em 2026-10-16). A variável não aparece no `ecs.tf` nem no `release.tf`, nem em `main` nem em `develop`, e por isso o catálogo tem 9 opções.
  - **Produção** roda `main` @ `06f2157`, sem o #242: lá a variável não existe, e o catálogo é o antigo, de 76 opções.
  - **Não foi verificada** a task definition em execução, porque uma variável posta à mão no console não aparece no Terraform. Conferir exigiria `aws ecs describe-task-definition`, que precisa de autorização.
  - A conferência diferencial principal roda com a variável ausente. O caminho com `"true"` é traduzido e entra como cenário secundário.
- **Números de acerto medidos antes do #242 não são comparáveis aos de depois:** com 76 opções o problema era outro (spec 06, 0.1).

- **Conferência diferencial contra develop @ `1157a6d` (2026-10-16):**
  - 80 cenários: 29 principais, 45 da varredura e 6 secundários;
  - 79 iguais; o único diferente é o D-1, já aceito;
  - detalhes na spec 06, seção 10.
- **Itens (lido) da spec:** 12 confirmados por execução e **nenhum corrigido**. 2 não dá para executar aqui (fila do pool com concorrência; A4, que precisa do banco de produção).
  - **É a primeira spec em que a regra do desfecho (abaixo) foi aplicada desde o início.** Nenhuma afirmação sobre develop precisou de correção.
  - **Mas a leitura não previu quatro diferenças**, e a varredura e a conferência acharam as quatro:
    - relato vazio: o SDK JS recusa antes de enviar, e o Python enviava;
    - o `enum` do `z.enum` sem repetidos;
    - o `enum` com índices numéricos primeiro;
    - `TypeError` na resposta nula da pergunta raiz.
  - Três dessas estavam no **módulo ia, já mergeado** (`43e2b43`). **Acertar o que se afirma não é o mesmo que afirmar tudo:** marcar (lido) protege contra o erro de desfecho, e só a execução acha o que ninguém pensou em afirmar.
- **Achados A1 a A3 confirmados por execução:**
  - A1: o texto de fallback fala de opções que não existem;
  - A2: o log da rodada não conta a sumarização;
  - A3: id repetido leva a desambiguar entre o candidato e ele mesmo.
- **Verificação por mutação:** 19 de 19.
- **Ambiente da conferência:**
  - pnpm 12.14.0 (a captura da #209 usou 12.10.1) e lockfile congelado;
  - instalação sem `--ignore-scripts`, o que não muda nada, porque o `allowBuilds` de develop bloqueia o build do esbuild;
  - **worktree em caminho curto (`%TEMP%\m1157a6d`):** no scratchpad, o caminho até o `esbuild.exe` passava de 260 caracteres, o MAX_PATH do Windows.

- **Ponto para a spec do `api`: relato vazio no orquestrador.** Develop aceita `mensagem: ""` em `POST /atendimentos/orquestrador`. O SDK recusa a mensagem vazia, a classificação cai no fallback e a pessoa vai para `outros` (em produção, antes do #242, para `handoff_humano`) **sem classificação nenhuma**. A tradução reproduz isso. **O peso depende de uma pergunta ainda sem resposta: `mensagem: ""` chega a acontecer?**
  - Se a Tykhe valida antes de enviar, é caminho morto, e o registro vira nota de rodapé.
  - Se não valida, quem manda mensagem vazia vai para `outros` sem classificar, e o caso vira issue.
  - **Onde está a resposta:**
    - **contrato da Tykhe:** `docs/contrato-tykhe.md` não diz nada sobre `mensagem` vazia (conferido em develop @ `1157a6d`), então a resposta teria de vir da própria Tykhe;
    - **logs:** cada relato vazio deixa uma linha `[classificar] falha ao classificar (múltiplo)` com `err.message` igual a "Invalid message content: empty string. 'human' must contain non-empty content.". Contar essa mensagem no CloudWatch de produção mede o caso sem tocar em dado pessoal. A consulta exige acesso AWS autorizado.

- **Mudança de desfecho que chega sem decisão com o próximo release (#242).** Ela é maior que a pergunta do relato vazio:

  | Situação | Produção hoje (`main` @ `06f2157`) | Próximo release (develop @ `1157a6d`) |
  |---|---|---|
  | Relato não identificado | `handoff_humano` (`nao_identificado`): atendimento humano | `redirecionado` com `tipoCaso: "outros"`: orientação genérica da Tykhe ("Entendi. Vou te encaminhar para o atendimento de outros assuntos.") |
  | **Relato vazio** (`mensagem: ""`) | `handoff_humano` | `outros`, **sem classificação nenhuma** |
  | **Classificação que falha** (Bedrock fora, throttling esgotado, resposta sem ferramenta) | `handoff_humano` | `outros` |

  - **O que o #242 decidiu:** que o relato não identificado vai para `outros` (#225).
  - **O que ninguém decidiu:** o relato vazio e a falha da classificação também viram "não identificado" (`ids: []` no fallback do ia) e caem nessa regra junto. Hoje essas pessoas chegam a um atendente; depois do release, recebem orientação genérica.
  - **A falha da classificação é o padrão da #196, da #232 e da #239:** falha de infraestrutura que vira desfecho de negócio.
  - **Evidência:**
    - o grafo terminando em `nao_identificado` com o relato vazio e com a classificação sem ferramenta foi **executado** na conferência diferencial (cenários `mensagem_vazia` e `classificar_sem_ferramenta`);
    - o que a rota faz com isso em `main` e em develop foi **lido** (`rotas/orquestrador.ts` das duas branches), não executado.
  - **Não é questão da migração:** a tradução reproduz develop. Se a contagem mostrar que acontece, vira **issue de produto**, porque é mudança de desfecho chegando sem decisão. A consulta de contagem está pronta no comentário da #208.

### O que falta para mandar para teste

**Para ir a teste, faltam dois módulos: o orquestrador (#244) e o `api`.** O grafo do orquestrador **não tem porta de entrada HTTP sozinho**. A rota `POST /atendimentos/orquestrador` vive no módulo `api`, junto com:
- o `thread_id` `orquestrador:<chatId>`;
- os desfechos `redirecionado` (com `tipoCaso`) e `handoff_humano`;
- os logs `orquestrador_*`;
- a entrega ao fluxo escolhido com os tokens;
- o bridge do WhatsApp.

O mesmo vale para os fluxos já mergeados: `POST /atendimentos` e as respostas também estão no `api`. **Com o orquestrador mergeado, o grafo funciona e tem testes, mas ninguém de fora consegue chamá-lo.** O teste de ponta a ponta, com a Tykhe ou o WhatsApp, começa depois do `api`.

**Atualização (2026-10-17):** o PR 1 do `api` (#246) dá porta HTTP à rota do orquestrador e à criação de atendimento. As respostas e o bridge vêm no PR 2.

### Pendência fora do orquestrador: lista de parentescos nova (#212)

Decisão de produto do Ícaro (2026-10-16): a lista passa a ter 8 valores, alinhados ao SIPEN. **É mudança de comportamento, não tradução.** Ela entra **em develop primeiro**, num PR próprio, e depois vem para a `migration` em commit próprio, como o #226 e o #242. Na `migration`, muda o módulo fluxos, já mergeado, e os testes que esperam "Ex-esposo(a)". Fica para depois do orquestrador, por prioridade do Ícaro.

## Módulo api (#246)

Dois PRs (spec 07, D-4). Resultado completo do PR 1 na seção 10.1 da spec 07.

- **PR 1:** pipeline na ordem do Fastify, autenticação, os sete formatos de erro, serialização pelo schema, log de requisição, `/health`, `GET /fluxos`, `POST /atendimentos`, `POST /atendimentos/orquestrador`, `/docs` e o guia [`docs/rodar-localmente.md`](docs/rodar-localmente.md). **Com ele, o orquestrador tem porta HTTP**, e o Ícaro consegue subir a API e ver o `flowId` escolhido. Ainda não dá para continuar a conversa.
- **Fixtures:** 31 das 50 conferidas byte a byte no PR 1; as 19 de `GET /atendimentos/:chatId`, `POST /atendimentos/respostas` e `/webhook/whatsapp` ficam para o PR 2.
- **Conferência diferencial: 343 cenários**, 322 idênticos. Os 21 restantes são: 1 artefato do httpx (idêntico por ASGI cru), 1 efeito da decisão 1 do fluxos, 2 de #210 e 17 da proposta D-5.
- **Mutação:** 29 de 31 pegas, e as 2 que passam são equivalentes.
- **Três achados da tradução, corrigidos:**
  - o `resume` sem pergunta pendente rodava o grafo do começo no Python;
  - um corpo que não é UTF-8 era aceito no Python e dá 400 em develop;
  - um `AWS_PROFILE` inexistente impedia a API Python de subir; em develop, ela sobe e cai no fallback.
  
  **Os dois últimos só apareceram ao testar o guia numa pasta limpa** (técnica registrada abaixo).
- **D-5, aceita em 2026-10-17:** `dadosConhecidos.tokensGastos` fora do formato. Develop zera ou corrompe a contagem em silêncio e responde 200; o Python falha mais cedo e mais alto, com 500. Está na tabela "Divergências aceitas".
- **Divergência registrada:** as linhas de subida são do uvicorn, e não do Fastify. Nenhum painel as consulta.
- **PR 1 mergeado na `migration` em 2026-10-18** (#247, merge `23b63e3`). O guia foi conferido de novo em pasta limpa, já na `migration`, em 2026-10-19.
- **PR 2 (2026-10-19), na branch `refactor/246-api-python`:** `GET /atendimentos/:chatId`, `POST /atendimentos/respostas` com o TTL e o 500 do `resume=""` (D-2), e o bridge do WhatsApp. Resultado completo na seção 10.2 da spec 07.
  - **As 50 fixtures** conferidas byte a byte, com as linhas de log; **os 74 testes de develop** traduzidos.
  - **O roteador do Fastify foi reproduzido** sobre o caminho bruto, e não sobre o caminho que o uvicorn decodifica: `decodeURI` sem os reservados, o parâmetro com os reservados decodificados, `FST_ERR_BAD_URL` e `FST_ERR_MAX_PARAM_LENGTH` sem log, e a query do `fast-querystring`.
  - **Conferência diferencial: 313 cenários**, comparando também as linhas de log de cada cenário: 302 idênticos. Os 11 restantes são HEAD de erro do roteador em que o `inject` devolve corpo e uma conexão HTTP real de develop não. Foi conferido, e o Python faz como o servidor real.
  - **Mutação:** 27 de 28 pegas, e a que passa é equivalente nos grafos de hoje.
  - **Guia, seção 5.1 (responder e consultar),** testado em pasta limpa.
  - **PR #250 aberto em 2026-10-19; CI verde** nos jobs `test` e `imagem` (run `39279987284`: `ruff`, `ruff format --check`, `mypy` em 129 arquivos, 932 testes na suíte padrão e 23 com Postgres). Mergeado em 2026-10-19 (merge `0bd610d`), com a confirmação do usuário; #246 fechada à mão, branch apagada. **Com ele, o api está completo:** dá para testar por HTTP o fluxo inteiro (classificar, criar, responder às perguntas até a conclusão e consultar o atendimento), e não só a classificação.
- **Achados do teste do modo B (2026-10-19), registrados em issue:**
  - **#248:** falha ao chamar o Bedrock vira "não identificado", sem alerta (repetição da #200);
  - **#249:** com o catálogo de 9 opções do #242, causa trabalhista e BPC/LOAS perdem a orientação "não atuamos, procure…", com prazo antes do próximo release;
  - **credencial de `aws login`:** exige `botocore[crt]`, agora no grupo `dev` (`f582150`).

## Módulo scripts (#252)

Spec 08 (`docs/migracao/specs/08-scripts.md`), aprovada em 2026-10-19. Fonte: develop @ `1157a6d`. Tradução feita em 2026-10-19 e 2026-10-20: a extração dos 74 registros, o seed e a coleta.

**Conferência contra develop (2026-10-20): 64 cenários, 62 idênticos.** Os dois crawlers rodam como processo, contra o mesmo Verde falso por HTTP, e a comparação cobre o stdout (com o log pino), o stderr, o código de saída, as chamadas ao Verde na ordem e o que foi gravado. Os 2 restantes são o texto do erro do parser de JSON (V8 contra Python), a divergência aceita na D-4. A primeira rodada parou no 32º cenário porque o sistema passou a recusar a criação de processos (e o Git Bash da máquina perdeu o `usr\bin\bash.exe`); a segunda rodou os 33 restantes com pausa entre eles e gravação a cada cenário.

**Mutações:** 6 de 6 na extração. No seed e na coleta, 22 de 23 nos testes de unidade, e a restante (`ON CONFLICT DO NOTHING`) é pega pelo teste com Postgres no CI. A 1ª rodada tinha pegado 19: três passavam **por falta de caso, e não por ausência de divergência**. `[]` e `{}` são verdadeiros no JS e falsos no Python, e os testes só usavam `"false"` e `0`, que coincidem por acaso. E a fronteira da profundidade só era conferida pela mensagem, que é a mesma com `>` e `>=`. Lição para os próximos módulos: na varredura de verdade do JS, incluir sempre lista e objeto vazios, e numa fronteira testar o valor exato dos dois lados.

**O ponto que não existe em nenhum outro módulo:** os 74 fluxos planejados do seed são **transcritos**, e não traduzidos. Uma palavra-chave perdida não quebra teste nenhum. A verificação tem dois caminhos independentes:
- o arquivo `.ts` de develop entra como fixture, com o id do blob git conferido no teste (`265f1df…`);
- o Node extrai o JSON; um leitor próprio em Python lê a fixture;
- o teste compara 74 ids únicos, o mesmo conjunto, o total de 1.744 palavras-chave e cada registro campo a campo.

**Decisões (aprovadas em 2026-10-19):**
- **D-1:** os 74 registros em `scripts/dados/fluxos_planejados.json`.
- **D-2:** os scripts rodam com `uv run python scripts/<nome>.py`, fora do pacote e da imagem.
- **D-3:** `logs-prod.sh` chama `npx --yes pino-pretty@13.1.3`. **Condição:** o script verifica antes do laço `node`, `npx`, o download do `pino-pretty` e `aws`, e diz o que falta, em vez de falhar com "command not found". Ferramenta de diagnóstico não pode falhar de forma obscura no meio de uma investigação.
- **D-4:** num JSON inválido do Verde, a mensagem de erro sai no texto do Python, e não no do V8.

**Achados:**
- **B1 → #251:** a coleta apaga a árvore da categoria sem transação e sai com código 0 quando falha. É o padrão da #196 numa ferramenta de manutenção. Aberta antes da execução, por decisão: o comportamento está no código.
- **B2:** o seed sobrescreve toda edição por SQL em `fluxos_planejados`. **Colide com a #249:** corrigir `mensagem_fixa` só no banco some no próximo seed. Registrado na #249. **Issue própria: #253** (`[TECH]`, aberta em 2026-10-19 por decisão do usuário): qual é a fonte do dado. A #249 e a #253 se referenciam.
- **B3:** `logs-prod.sh` descarta o stderr do `aws`; credencial vencida fica em silêncio. A ausência do `aws` entra nas checagens da D-3; o resto fica para decisão.
- **B4:** a palavra-chave `"sofri preconceito` (planejado "direitos e diversidade") tem uma aspa solta em develop. Achado pelo leitor estrito da extração. Reproduzido; cosmético, sem issue.
- **B5 → #255:** importar os fluxos inicializa o checkpointer (o ponto 1 da #208, em develop). Nos scripts: uma linha de log extra, as tabelas de checkpoint criadas no banco de destino e a morte sem o próprio prefixo de erro, antes das guardas. A fundação Python já tinha desfeito o acoplamento, então os scripts Python reproduzem o efeito com uma chamada explícita.

**Busca vetorial do orquestrador: traduzida e conferida, mas não em uso em produção (#256).** Quem avaliar a confiança da migração precisa saber que esse trecho não foi exercitado em execução real.
- **Por que não roda:** com o catálogo de 9 opções do #242 e `k` 10, `buscar_candidatos` devolve o catálogo inteiro sem calcular embedding. Executado em 2026-10-20: 0 chamadas ao Bedrock nos dois lados. O boot ainda indexa as 9 descrições (lido).
- **O que foi conferido:** por leitura, o modelo, as dimensões (1024), o cast `::vector`, o `k` e o SQL de ordenação do pgvector. Executado contra um Bedrock falso, com a flag `ORQUESTRADOR_INCLUIR_PLANEJADOS=true` (83 opções): o mesmo texto decodificado nas 84 chamadas, o mesmo modelo e os mesmos cabeçalhos, e os mesmos 10 candidatos na mesma ordem (busca em memória). O JSON do corpo difere só na forma (o JS compacto e em UTF-8 cru, o Python com espaço e escapes `\u`).
- **O que não foi exercitado:** a ordenação no pgvector, os vetores reais do Titan e a cobertura da busca. Se a #249 devolver os planejados ao catálogo, esse caminho passa a ser o primeiro filtro de toda classificação de uma vez; a #256 pede medir a cobertura antes.

## Módulo documentacao (#258)

Spec 09 (`docs/migracao/specs/09-documentacao.md`), aprovada em 2026-10-20 com as decisões D-1 a D-5. Fonte: develop @ `1157a6d`.

**Primeiro, o que develop mudou (D-1):** os quatro commits de documentação de develop posteriores ao nascimento da `migration` (#229, #242, #234, #226) entraram num commit próprio, antes da reescrita (`814395b`).

**A reescrita descreve o repositório como ele passa a ser:** `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `docs/` e `.claude/`. As referências históricas ficam (D-2): decisões datadas, incidentes e números de issue; trecho histórico que cita a versão TypeScript vai numa seção marcada `> **Registro histórico`.

**A verificação é executada, e não só lida:**
- `tests/test_documentacao.py`: links e caminhos citados existem; referência à versão TypeScript só em registro histórico; o conjunto de variáveis lidas pelo código é o da tabela do README (28: as 25 do código e as 3 do SDK da AWS).
- Os guias seguidos num clone limpo, no Windows (resultado na seção 10 da spec). O `docs/novo-fluxo.md` foi seguido de verdade, com um fluxo de exemplo numa branch descartável: os testes do fluxo passaram, e **a suíte quebrou em 12 testes que fixam o catálogo**, o que o guia não dizia (C7, decisão em aberto 6).

**`APP_ENV` (C4, decidido em 2026-10-20):** dois comportamentos, e não três. Só `test` muda alguma coisa; `development` e ausente são o comportamento de produção, em develop e aqui. O critério da #208 que pedia três foi corrigido.

**Diagramas (D-4):** o `orquestrador.png` desenha o relato não identificado como handoff, como antes do #242, também em develop (C1, registrado na #249). `orquestrador`, `padrao-comum-ia` e `mapa-modulos-ia` foram trocados por Mermaid no próprio doc. Gerar e gravar os PNGs novos no S3 é escrita na AWS e fica fora do módulo.

## Técnica a repetir nos próximos módulos: verificação por mutação

Um teste que passa prova que o código faz o esperado no caso testado. Não prova que o teste **pegaria** a tradução errada. Para cada divergência que a spec do módulo trata (o lugar onde a tradução ingênua muda o comportamento), aplique no código a versão ingênua, rode o teste correspondente e confirme que ele **falha**. Depois, restaure o código.

- Usado no módulo integracoes: redirect, prazo de conexão, `True` na query string, escape de URL, POST com o corpo lido dentro do retry (encaminhamento e apenado) e remoção recursiva de `None`. Os sete testes falharam com a mutação.
- **Se a mutação passar, examine a mutação antes do teste.** No integracoes, a primeira versão da mutação de `None` removia só no primeiro nível, e o `null` do teste estava aninhado. A mutação estava errada, não o teste. Corrigir o teste para "pegar" uma mutação mal escrita seria enfraquecê-lo.
- O script é descartável (não entra no repositório), mas a lista de mutações e o resultado vão para a issue ou para o PR do módulo.

## Técnica a repetir nos próximos módulos: varredura de pré-preenchimento

**Repetir no orquestrador e no api.** É o método mais produtivo que apareceu na migração: no fluxos, achou dois itens que nenhuma leitura pegaria (o `cadastroErro: null` no `cadastro_pessoa` mergeado e o `texto_template` de objeto e lista) e o D-1.

- **Como:** para cada canal que pode chegar de fora (hoje, o `dadosConhecidos` da Tykhe, #240), pré-preencha o canal com cada valor da lista `null`, texto (`"x"`), número (`0`, `7`), booleano (`true`, `false`), `{}`, `[]` e `""`. Rode o mesmo cenário em develop e no Python, com o mesmo Verde, e compare byte a byte as perguntas, os metadados, o que vai ao Verde e a exceção.
- **Por que funciona:** a leitura do código segue o tipo declarado, e a varredura testa o que o tipo não impede. As divergências da migração se concentram justamente aí: `null` × `undefined`, coerção do JS e `str()` contra template literal.
- **Tamanho no fluxos:** 495 dos 584 cenários da conferência diferencial (spec 05, seção 8.1).
- **Como na mutação:** o script fica fora do repositório, e a contagem e o resultado vão para o PR do módulo.

## Técnica a repetir nos próximos módulos: testar o guia de uso numa pasta limpa

**Vale tanto quanto a varredura e a mutação.** O guia de instalação e uso não é só documentação: executá-lo é parte da verificação.

- **Como:**
  - clone literal do repositório numa pasta nova;
  - os comandos colados do guia, sem ajuste;
  - o `.env` copiado ao pé da letra, inclusive os valores de exemplo;
  - os dois shells que o guia cita;
  - as credenciais da máquina escondidas, só para o processo.

  Confira cada resposta e cada linha de log que o guia promete.
- **Por que funciona:** os dois achados do PR 1 do api (#246) vieram dali, e **nenhum apareceria em teste**:
  - **Latin-1:** veio de um `curl` real no Git Bash do Windows, que entrega o acento em Latin-1. A conferência só mandava UTF-8 válido.
  - **`AWS_PROFILE`:** veio de copiar o `.env` ao pé da letra, com o perfil de exemplo, que não existe. Nenhum teste subia a API com um perfil errado.

  São **defeitos de uso**, e só a execução encontra.
- **Quando:** antes de abrir o PR de todo módulo que muda como a aplicação sobe, é configurada ou é chamada de fora. Depois de cada correção, o teste do guia roda de novo, da pasta limpa.
- **No PR:** o que foi testado, onde (sistema, shell, versões) e **o que não foi testado**, dito no topo do guia.

## Técnica a repetir nos próximos módulos: sondar a infraestrutura de develop

**Mesma classe da varredura de pré-preenchimento:** a varredura testa o que o tipo declarado não impede; a sonda testa o que a infraestrutura faz sem que ninguém tenha especificado.

- **O que apareceu no PR 2 do api (#246):** a sonda do roteador do Fastify contra develop mostrou comportamentos que nenhuma spec descrevia e nenhuma das 50 fixtures capturava:
  - `%2F` vira `/` dentro do `chatId`, depois de casar a rota;
  - um `%` malformado dá 400 `FST_ERR_BAD_URL` **sem nenhuma linha de log**;
  - um parâmetro com mais de 100 unidades UTF-16 dá 414;
  - num método sem rota, a URL malformada dá 404 só com a linha "not found".
- **Por que importa:** são comportamentos de infraestrutura (roteador, parser, servidor HTTP). O código da aplicação não os mostra, e a biblioteca Python equivalente faz diferente: o uvicorn decodifica o caminho inteiro antes do roteamento.
- **Como:**
  1. Listar as camadas que a requisição atravessa antes do handler (roteador, decodificação de URL, query string, parser do corpo) e as entradas de borda de cada uma: escapes malformados, reservados codificados, caixa, barras extras, tamanhos-limite, chaves repetidas.
  2. Rodar cada entrada contra o app real de develop e ler o código da biblioteca para entender a regra.
  3. Transformar cada entrada em cenário da conferência diferencial, com a resposta e o log.
- **Quando:** em todo módulo que recebe entrada de fora pela infraestrutura: rotas HTTP, webhooks, filas.

## Princípio: ferramenta de teste não é o sistema

**Divergência contra uma ferramenta de teste pede verificação contra o comportamento real antes de virar correção.**

- **O caso (PR 2 do api, #246):** 11 cenários da conferência divergiram porque, num HEAD que dá 404, 400 ou 414, o `app.inject` de develop devolve o corpo, e o Python não.
  - Aceitar a comparação teria levado o Python a reproduzir um artefato do `inject`.
  - Antes de corrigir, a resposta foi conferida numa conexão HTTP real com o servidor de develop. Ali, o corpo não vai: o Node descarta o corpo de toda resposta a HEAD.
  - O Python já fazia como o servidor real, e os 11 ficaram registrados como artefato, no teste de regressão e na spec 07.
- **A regra:** a conferência compara o Python com uma **observação** de develop, e a observação passa por uma ferramenta: o `inject`, um transporte de teste, um mock. Quando a divergência pode estar na ferramenta, observe develop pelo caminho que a produção usa antes de mudar o Python.
- **Sinais de que pode ser a ferramenta:** a diferença está em detalhe de protocolo (HEAD, cabeçalhos automáticos, codificação de URL, `content-length`), e não em regra de negócio. Ou a ferramenta pula uma camada que a produção atravessa.

## Padrão: arquivo novo que o build passa a precisar não é avisado por nada (2026-10-21)

**Mesma classe do princípio acima:** o CI passar não diz que a imagem constrói, assim como a ferramenta de teste não é o sistema.

- **O caso (PR #272, `fast-uri` em `develop`):** os `overrides` do `fast-uri` ficaram no `pnpm-workspace.yaml`, porque no pnpm 12 eles só valem ali (o campo `pnpm.overrides` do `package.json` é ignorado; conferido). O lock passou a registrar os `overrides`. Mas o `Dockerfile` da versão TypeScript copia só o `package.json` e o `pnpm-lock.yaml` nos estágios que instalam as dependências. Dentro da imagem, os `overrides` não existiam, e o `pnpm install --frozen-lockfile` falhava com `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH`.
- **Por que nada avisou:** o CI do PR instala com o repositório inteiro, onde o arquivo existe, e não constrói a imagem. O CI passou. No merge, o job de testes do deploy do release passaria, o `docker build` falharia, e **a correção de segurança não chegaria a lugar nenhum**.
- **Como apareceu:** construindo a imagem localmente, como o deploy faz, antes do merge. A correção foi o `Dockerfile` copiar também o `pnpm-workspace.yaml`. Depois do merge, o deploy do release construiu a imagem e fez o deployment (run `39620973087`).
- **A regra:** toda mudança que mexe em configuração de build (lockfile, configuração do gerenciador de pacotes, arquivos que a imagem copia) **constrói a imagem antes do merge**, com o mesmo `Dockerfile` do deploy, e confere dentro dela as versões instaladas.

**Lacuna conhecida até o corte: o CI de `develop` não constrói a imagem.** O `ci.yml` de `develop` é o da versão TypeScript e só roda `typecheck` e `test`. O job `imagem` existe só no CI da Python, que roda em PR para a `migration`. **Até o corte, uma mudança que afete o build em `develop` passa despercebida pelo CI.** No corte, o `ci.yml` da Python, com o job `imagem` e os gatilhos de `develop` e `main`, substitui o atual, e a lacuna some.

**O mesmo padrão no teste `MANTER`:** a lista de nomes cobria o `package.json` e os lockfiles, e deixava passar o `pnpm-workspace.yaml`. O merge do #272 na branch do corte mostrou isso. A lista passou a incluir o `pnpm-workspace.yaml` e o `.npmrc`.

**O ponto cego é de desenho, e não de descuido.** Um teste feito para impedir que o Node volte enumera à mão o que é proibido (extensões e nomes de arquivo), então cobre só o que alguém lembrou. Se aparecer outro arquivo de configuração de Node (`.nvmrc`, `bunfig.toml`, `tsconfig.base.json`, um lockfile novo), o teste deixa passar outra vez, em silêncio. **Inverter a lógica seria mais seguro:** listar o que é permitido no repositório (extensões e diretórios de uma aplicação Python, mais as exceções de `MANTER`) e falhar com qualquer outra coisa. **Não foi invertido agora, por decisão de 2026-10-21:** fica registrado para quem mexer no teste depois.

## Padrão: afirmação sobre desfecho inferida do código, sem execução

Três vezes, uma afirmação sobre o que acontece com a pessoa atendida foi escrita a partir da leitura do código, e a execução mostrou outra coisa. **O padrão é inferir o desfecho a partir do código em vez de rodar.**

1. **#217, "conta como não":** a issue dizia que a resposta vazia na confirmação de TTL contava como "não". Ao rodar o LangGraph JS com `resume: ""`, o resultado foi `EmptyInputError` e 500, com o grafo parado na mesma pergunta (correção na #217, 2026-10-14).
2. **#232, a gravidade: afirmação feita em revisão e corrigida antes de virar texto publicado.** Numa revisão em conversa, durante a spec do subgrafos, a falha de infra no CEP foi avaliada como "de gravidade menor que a da #196". A avaliação foi corrigida ao se confirmar que, na #196, o RG não encontrado leva a handoff, e não a atendimento errado. O desfecho das duas é o mesmo: handoff desnecessário por falha de infra (spec 04, decisão 2). Por isso a primeira avaliação não aparece no repositório nem na issue. **Diferente dos outros dois casos, o erro foi pego antes de ser publicado.** A #232 mantém uma ressalva: o desfecho só converge se a falha durar o atendimento inteiro.
3. **`rg: null` no fluxos (#241):** o registro dizia que develop "pula a pergunta e consulta `""`" no Verde. A conferência diferencial mostrou que develop não consulta: `""` falha no formato e ele pergunta "O RG deve conter apenas números…" (spec 05, 8.2 item 3).

**Regra a partir daqui:** a afirmação sobre desfecho (o que a pessoa vê, o que vai ao Verde, como o atendimento termina) só entra em issue, spec ou registro depois de executada, ou marcada explicitamente como **inferida da leitura, não executada**.

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
- **Caracteres invisíveis literais no código-fonte:** um BOM literal no `pipeline.py` foi trocado pelo escape `"﻿"` (#246). Outros continuam em arquivos de teste antigos. Em `_js.py` são intencionais, mas o escape deixaria isso visível na revisão.
- **Alerta do token do Verde:** o `verificar-token-verde.yml` falha todo dia por causa do token de release, e com isso deixou de alertar. Separar prod e release em execuções distintas.

## Prazos: a conexão com o banco e as chamadas ao Verde são assuntos diferentes

Trocar um prazo pelo outro é o mesmo erro do padrão "parâmetro com nome familiar e semântica diferente" (comentário 12 da #208). Registro de 2026-10-20, depois de uma confusão na investigação do B5 (#255): um valor de 10 s, usado só numa sonda descartável para não esperar 120 s, foi relatado sem dizer de onde vinha.

**Conexão com o Postgres. Requisito: banco fora do ar falha rápido.**

| Prazo | Valor | Onde | Situação |
|---|---|---|---|
| Espera de quem pede conexão ao pool | 120 s | `src/maria/shared/pool.py` (`ESPERA_POR_CONEXAO_S`) | **Decisão 5, fechada em 2026-10-20 (correção de migração, #268).** Com a conexão recusada, o erro agora chega a quem espera na hora, como no `pg` (`PoolComoPg`). O prazo de 120 s continua limitando o que nenhum dos dois devolve sozinho: o pacote descartado (no Linux, o `pg` errou em 21 s) e o pool cheio |
| Abrir a conexão (`connect_timeout` do libpq) | ausente | conexões diretas, fora do pool: o `CREATE SCHEMA` do checkpointer no boot (`shared/checkpointer.py`), o seed e as fixtures de teste | Igual ao `pg` de develop, que também não tem prazo por padrão (`connect_timeout: 0`, `pg/lib/defaults.js:78`). No Linux, a conexão recusada falha na hora; um pacote descartado espera o prazo do TCP do sistema. **No Windows, o libpq não percebe a conexão recusada e espera sem limite** (medido: `socket` puro recusado em 2,1 s, `psycopg.connect` preso por mais de 150 s; numa rodada de mutações do seed, a conexão direta a uma porta fechada levou 2 min 10 s até o teste falhar): afeta só o desenvolvimento local. **Não é o prazo do pool:** são conexões que não passam por ele |

**Chamadas HTTP ao Verde. Requisito: o Verde lento não vira "não encontrado" (#196).**

| Prazo | Valor | Onde | Origem |
|---|---|---|---|
| Total de cada tentativa, inclusive a leitura do corpo | 30 s | `src/maria/integracoes/verde.py:55` (`TIMEOUT_VERDE_S`), aplicado com `asyncio.timeout_at` em `:170`, `:176` e `:188` | #196: um RG real voltou "não encontrado" com o Verde de homologação levando 13,5 s e o prazo antigo de 20 s |
| Abrir a conexão TCP | 10 s | `src/maria/integracoes/cliente_http.py:34` (`connect=10.0`) | `connectTimeout` do undici, medido no módulo integracoes. Corre dentro dos 30 s, e não no lugar deles |
| Total de cada chamada do script de coleta | 20 s | `scripts/coletar_arvore_perguntas_verde.py` (`TIMEOUT_MS`) | Reproduz o script de develop, que a #196 não alterou. Mesmo risco da #196 numa ferramenta de manutenção (ver #251) |

## Plano de corte: a troca de versão no release (combinado em 2026-10-20)

> **Corrigido em 2026-10-20, no fim do dia: não há release em uso.** O Ícaro informou que não usa o release, e a validação deixa de depender dele. O texto abaixo, escrito antes da informação, fica como estava. Valem as observações:
> - **O release está parado.** O token do Verde no segredo dele venceu em 04/10, e ninguém o usa. O deploy automático dele continua acontecendo (houve um em 2026-10-20, 17:31, com o #254 do Dependabot), mas não serve de validação.
> - **O endereço que o fluxo de teste da Tykhe chamava** (`d2urkrsd5u4rck.cloudfront.net`) continua sendo o release pela evidência (o `tipoCaso` do #242 no `/docs/json`). Se a Tykhe usada de verdade chama a produção, o merge da `migration` em `develop` não muda o que a Tykhe vê; a troca que importa é a de `main`, e a linha de base, o roteiro e a troca da chave de API passam a ser da produção. **A confirmar com o Ícaro, antes do merge.**
> - **O teste em homologação passou a ser local:** as duas versões rodando na máquina de desenvolvimento, contra o Verde de homologação, com o token e o client id de teste (válidos até 29/10). Ver a seção "Teste local contra a homologação do Verde".

## Módulo corte (#268)

Leva a `migration` para `develop`. O PR #267 (`migration` → `develop`) foi aberto em 2026-10-20 e **só é mergeado depois da linha de base do roteiro de 4 casos, no ambiente que a Tykhe usa de verdade** (a confirmar). **Corrigido em 2026-10-21:** o merge foi feito antes dessa linha de base (ver abaixo).

**Merge em `develop`: feito em 2026-10-21, às 19:47 UTC, pelo Ícaro** (`icaroeduardo-lab`), com merge commit (`252ce8a`).
- **Foi feito sem a linha de base pela Tykhe.** O roteiro de 4 casos não foi rodado pelo fluxo da Tykhe na versão TypeScript antes do merge. A comparação que existe é a linha de base pela API local, nas duas versões: a parte fixa e a IA, idênticas. A comparação pela Tykhe passa a ser só contra a versão Python, sem a referência TypeScript gravada.
- **Antes do merge:** o #262 e o #263 (Dependabot, só `pnpm-lock.yaml`) foram mergeados em develop às 19:24, ao contrário da decisão de fechá-los depois do corte. Isso deixou o #267 com conflito, resolvido mantendo o lockfile apagado (PR #275, e o #276, duplicado, sem arquivos). **A árvore de develop depois do merge é idêntica à da `migration`** (mesmo tree `1bd5500`).
- **Primeira subida da versão Python em ambiente real (release, task `03affdb9`, 19:49:25 UTC):** `[checkpoint] PostgresSaver conectado`; as tabelas `atendimentos`, `perguntas`/`assuntos_verde`/`flow_assuntos`, `fluxos_planejados` e `fluxo_embeddings` (pgvector) prontas; o catálogo de embeddings reindexado; e `Application startup complete`. **Nenhum aviso nem erro:** 38 linhas, todas de nível 30. O envelope é o do pino de develop (`hostname`, `level` numérico, `msg`, `pid`, `time` numérico; `req` com `host`, `method`, `remoteAddress`, `remotePort` e `url`; `res` com `statusCode`; e `reqId` e `responseTime`). O serviço ficou estável às 19:51, com 0 falhas, e as 14 checagens de saúde (`GET /health`) responderam 200.
- **Depois do merge:** o #277 (Dependabot, `certifi` no `uv.lock`), o primeiro do lado Python, foi mergeado às 19:51 e disparou outro deploy. A segunda subida (task `8d1ffcc4`, 19:53:51 UTC) saiu igual à primeira: as mesmas linhas, 34 de nível 30, nenhum aviso nem erro. O serviço ficou estável às 19:55, com 0 falhas.
- **Pendências:** o token do Verde no segredo do release continua vencido. A primeira consulta de pessoa presa ou de violência doméstica vai falhar até o Ícaro gravar o token válido e fazer o deploy. Também falta trocar a chave de API.

**O que entrou em develop desde a base (`4e695f2`), e onde está na `migration`:** #226 (`2403bab`, módulo fluxos), #229 (`814395b`), #234 (`respostas.py`, PR #250) e #242 (PRs #245, #247 e #250), todos já na `migration`. O #254 (Dependabot) não se aplica, porque mudou só o `pnpm-lock.yaml`. A única mudança de develop que faltava, o painel `observabilidade.json` do #242, entra pelo merge, e os 3 eventos que ele filtra existem no código Python.

**Merge de develop na branch do corte, resolvido (2026-10-20):**
- 16 conflitos: 3 de documentação, resolvidos com a versão da `migration`, que já contém o texto de develop; e 13 de modificação contra remoção (`pnpm-lock.yaml` e 12 `.ts`), que continuam apagados.
- **Achado: 4 arquivos `.ts` entravam sem conflito nenhum.** Develop os criou depois da base, e o git os deixava preparados para o commit sem avisar: `tiposTykhe.ts`, `respostaSimNao.ts` e dois testes. Foram apagados.
- **`tests/test_sem_typescript.py`:** falha com qualquer `.ts`/`.js`, `package.json`, lockfile ou `tsconfig` no disco fora da lista `MANTER` (os 2 hooks do Claude Code e as 7 fixtures de evidência), e com item de `MANTER` que não existe mais. É o que impede o "nenhum arquivo TypeScript" de virar falso em silêncio depois de um merge mal resolvido. Mutações conferidas: o `.ts` sobrevivente de volta e um `package.json`.
- Depois da resolução, a branch difere da `migration` só no `observabilidade.json`, e a simulação do merge em `develop` sai sem conflito.

**`ci.yml`:** os gatilhos de PR para `develop` e `main` voltaram; `migration` fica até o fim do corte.

**Decisão 5 fechada como correção de migração** (seção "Decisões em aberto").

**Decisão 3 (conversas em andamento no corte): corrigir antes do corte, na #270 (melhoria sobre develop, 2026-10-21).**
- **O problema, executado num Postgres local:** depois da troca, a conversa em andamento recebia 409 com status `concluido` e a mensagem de sucesso do fluxo ("Show! Já confirmei os dados da pessoa presa. Vou seguir com o encaminhamento…"), sem que nada tivesse acontecido. A pessoa vai embora achando que foi atendida.
- **É herdado:** com o checkpoint apagado, a versão TypeScript responde igual (controle executado). O corte transforma o caso raro em evento de massa.
- **A correção:** na rota de respostas, um atendimento sem checkpoint (nenhum valor nem nó pendente) passa a ser tratado como expirado. Reaproveita o contrato que o TTL já usa: 409 com `status: expirado`. A mensagem tem texto próprio, porque não é inatividade; o desfecho vai para a `atendimentos` (`expirado`, `sessao_expirada`), e o log tem o evento `atendimento_sem_checkpoint`, para contar quantas conversas o corte atingiu.
- **Escopo:** só quem vem pela Tykhe, cujo `chatId` persiste. O bridge do WhatsApp guarda as conversas em memória e abre um atendimento novo depois do reinício.
- **Pré-condição, com o usuário:** conferir se a Tykhe grava o corpo do 409 nas variáveis. Se não gravar, a resposta passa a ser 200.

## Teste local contra a homologação do Verde (desde 2026-10-20)

Substitui o "teste em homologação" pelo release, que não está em uso.

- **Como:** `teste-tykhe/verde_homolog_duas_versoes.py` (fora do repositório) sobe a versão TypeScript (develop @ `1157a6d`) e a Python, uma de cada vez, e roda os mesmos cenários pela API nas duas. O Verde fica atrás de um **proxy local que só deixa passar GET e o `POST /apenado`** (consulta por RG) e recusa qualquer outro POST: nada é gravado na homologação. O proxy registra o método, o caminho, o corpo, o status e o formato da resposta, sem o token.
- **Primeira rodada (executada em 2026-10-20):** 3 cenários (processo digitado com pontuação, RG, CPF), **idênticos nas duas versões**, inclusive as 3 chamadas ao Verde (método, caminho, escape, corpo, status e formato da resposta). Nenhuma chamada bloqueada. A consulta de CEP e o cadastro não foram exercidos.
- **Incidente da primeira rodada, resolvido em 2026-10-20:** o RG inventado `000000000` devolveu um registro, e a pergunta de confirmação trouxe um nome completo. **O Ícaro confirmou em 2026-10-20 que a homologação do Verde tem dados de teste, e não de pessoas reais: não houve exposição de dado pessoal.** O comportamento é o da #236, nas duas versões, e em produção, onde os dados são reais, continua sendo o que a issue descreve (evidência registrada lá, sem o nome). Os arquivos locais com o nome foram apagados.
- **Mascaramento:** desde então, o executor mascara todo texto que pode vir do Verde (sequências de palavras em maiúsculas viram `[DADO DO VERDE]`) antes de imprimir ou gravar. A comparação entre as versões continua usando o texto inteiro, só em memória.
- ~~**Suspenso até a resposta do Ícaro sobre dados reais na homologação:** qualquer teste que envolva nome, CPF ou RG.~~ **Liberado em 2026-10-20, com a confirmação do Ícaro:** a homologação tem dados de teste. O mascaramento continua no executor, porque não custa nada e protege se alguém apontar o executor para outro ambiente por engano. **A gravação na homologação também foi liberada em 2026-10-20:** o cadastro de pessoa com endereço e o encaminhamento voltam ao escopo dos testes. O proxy passa a deixar passar esses dois POST, e só eles, e nunca aponta para o Verde de produção.
- **Segunda rodada, com gravação (executada em 2026-10-20):** `teste-tykhe/verde_homolog_orquestrador.py`. Os cenários entram pelo orquestrador, porque só por ele o fluxo chega à identificação por CPF e ao cadastro (`viaOrquestrador`, `violencia_domestica/graph.py:198-199`). A classificação é a simulada do modo de teste (`MOCK_CLASSIFICACAO_FLOWID`), e o Verde é o real: o Verde simulado só liga quando falta o token, nas duas versões (`verde.py:255`, `verde.ts:108`). Cada versão usa um CPF inventado próprio, com dígito verificador válido. 22 chamadas ao Verde, nenhuma bloqueada.

  | Cenário | TypeScript × Python | O que foi exercido no Verde |
  |---|---|---|
  | Pessoa presa, RG `000000000`, confirma o nome | igual (13 passos) | apenado, CPF 404, CEP, **cadastro com endereço (201)**; handoff "sem número do processo" |
  | Pessoa presa, o mesmo RG, "não" à confirmação | igual (4 passos) | apenado; handoff "não consegui confirmar" |
  | Violência doméstica, cadastro e encaminhamento | mesmo comportamento (12 passos, `concluido`, urgente) | CPF 404, CEP, **cadastro (201)**, plantão, órgãos, **encaminhamento (201)** |

  Na violência doméstica, **o que a Maria envia ao Verde é igual**: os corpos do `POST /pessoa` (199 bytes) e do encaminhamento (230 bytes) têm os mesmos campos, na mesma ordem. Quem diferiu foi o Verde: para cada pessoa cadastrada, ele devolveu um órgão diferente (ids 386 e 270), com horários diferentes. A diferença é de dado da homologação, e não de tradução. Ficaram na homologação 4 pessoas de teste e 2 encaminhamentos de teste. **Não coberto:** o CPF que já existe na homologação (falta um CPF de teste).

**Quando a `migration` entrar em `develop`, o `deploy-release.yml` sobe a versão Python no release sozinho, no push.** O endereço que o fluxo da Tykhe chama não muda, e o comportamento muda de uma vez. Por isso a troca tem momento combinado.

### Qual ambiente a Tykhe chama (executado em 2026-10-20)

O fluxo "Orquestrador" da Tykhe chama `https://d2urkrsd5u4rck.cloudfront.net`. **É o release**, por evidência, e não pela informação repassada:
- o `GET /docs/json` público desse endereço traz `redirecionado` e `tipoCaso`, que são do #242;
- o #242 está em `develop` (3 ocorrências de `tipoCaso` em `src/`) e não está em `main` (0 ocorrências; o último merge em `main` é de 2026-10-01);
- o release faz deploy no push para `develop` (`deploy-release.yml`), e a produção no push para `main` (`deploy-prod.yml`).

**A chave de API desse fluxo é o `API_KEY` do segredo `maria-langgraph-pp-release/app`**, e não o de `maria-langgraph-pp-prod/app`. Assumir o ambiente errado significaria gravar a chave no segredo errado, ou trocar a de produção achando que era a do release.

### Quem consome a chave do release

| Possível consumidor | Usa a chave? | Se a chave for trocada |
|---|---|---|
| Fluxo "Orquestrador" da Tykhe (3 nós de Chamada API) | sim | quebra até os cabeçalhos serem atualizados |
| Workflows do GitHub (deploys, Grafana, verificação do token do Verde) | não; o único segredo de API nos workflows é o `GRAFANA_API_TOKEN` | nada |
| Health check do ALB | não; `/health` não exige chave | nada |
| Bridge do WhatsApp do release | sim, a chave da própria API, lida quando o container sobe | se ajusta no novo deploy |
| Testes do repositório | não; chave fixa de teste, sem rede | nada |
| **Fora do repositório:** outros fluxos da Tykhe, coleções do Postman, scripts de quem testa | **não dá para saber pelo código** | quebram até serem atualizados |

**O risco real está fora do repositório.** "A Tykhe é o único consumidor esperado" (`docs/contrato-tykhe.md`) é intenção documentada, e não inventário. Antes de trocar a chave, perguntar ao Ícaro e a quem administra a Tykhe quem mais usa a chave do release.

**Troca da chave (ficou exposta num arquivo):** gerar a nova; gravar no campo `API_KEY` do segredo do release, mantendo os outros campos; novo deploy do serviço `api-release`; atualizar a Tykhe logo em seguida (entre o deploy e a atualização, as chamadas recebem 401). **Na mesma janela da troca de versão**, para quem testa parar uma vez só.

### A janela

1. Merge da `migration` em `develop` numa janela anunciada, fora do horário de teste.
2. Nada de teste na Tykhe durante o deploy do release.
3. **Conversas em andamento se perdem na troca.** O checkpoint do Python fica no schema `checkpoint_py`, porque as duas serializações são incompatíveis. Quem estiver no meio de um atendimento ou de uma desambiguação recomeça a conversa. O destino das threads em andamento é a decisão em aberto 3.
4. O roteiro abaixo, **duas vezes**: antes do merge, contra a versão TypeScript, para registrar a linha de base; e logo depois do deploy, contra a versão Python. **A rodada na versão TypeScript é pré-condição do merge:** sem a linha de base, toda diferença vira discussão sobre se já era assim.

### Roteiro de conferência: 4 casos, no próprio fluxo da Tykhe, pelo WhatsApp de teste

Relatos inventados, como aqui. Para cada caso, o esperado está dividido entre o que é **fixo** (código, sem IA) e o que **depende da IA** (a classificação e o texto da pergunta de desambiguação). **Se uma parte fixa não bater, é falha. Se só uma parte da IA mudar, compare com a linha de base do TypeScript, e não com este texto.** Os campos são os do fluxo da Tykhe: `StatusFluxo` (status), `TipoFluxo` (flowId), `TipoResposta`, `tipoCaso` e `RespostaFluxo` (resposta).

**Caso 1. Fluxo da Maria identificado.** Relato: *"Meu companheiro me ameaçou ontem à noite e quebrou meu celular. Tenho medo de voltar pra casa."*
- **Depende da IA:** a classificação escolher violência doméstica. Não executado com o Bedrock real para este relato.
- **Fixo, se escolher:** `StatusFluxo` = `em_andamento`; `TipoFluxo` = `cabb2495-4e12-4f4a-9956-3d20649059bc`; `TipoResposta` = `sim_nao`; a pergunta é **"Você é a vítima de violência doméstica?"**, com as opções Sim e Não (executado na API Python em 2026-10-19, com a classificação simulada).

**Caso 2. Redirecionado para a Tykhe.** Relato: *"Fui mandado embora da empresa onde trabalhei três anos e eles não pagaram minha rescisão nem o FGTS. O que eu faço pra receber?"*
- **Depende da IA, já medido:** na API Python com o Bedrock real (2026-10-19, duas vezes): `redirecionado`, `tipoCaso` = `novo-processo`.
- **Fixo, dado o `tipoCaso`:** `StatusFluxo` = `redirecionado`; sem `TipoFluxo`; `RespostaFluxo` = **"Entendi. Vou te encaminhar para o atendimento de abertura de um novo caso."**
- **Atenção:** este é o defeito da #249 (deveria orientar a procurar o sindicato). Se a #249 for corrigida antes da troca, o esperado muda para o que ela decidir.
- **Atualizado em 2026-10-21: o redirecionamento sem o "Falha. Diferente de 200" depois, e sem segunda chamada à Maria.** Num teste pelo WhatsApp (relato de pensão alimentícia), o fluxo da Tykhe mostrou "Falha. Diferente de 200" junto do redirecionamento. **A falha não vem da API:**
  - a Maria responde **200** ao redirecionamento (`orquestrador.ts:198` e `:207` na versão TypeScript; o mesmo na Python);
  - o fluxo da Tykhe testava "sem `TipoFluxo`" antes de "`StatusFluxo` = `redirecionado`", tratava o redirecionamento como desambiguação e fazia **uma segunda chamada com `resposta` vazia**. A Maria responde **400** ("resposta não pode ser vazia", `orquestrador.ts:141-142`), e é esse 400 que vira o "Falha". Com texto, a segunda chamada receberia 200, com o redirecionamento repetido (executado na versão TypeScript);
  - acontece com **qualquer** assunto redirecionado, nas duas versões da Maria;
  - **a correção é no fluxo da Tykhe** (redirecionamento testado antes de qualquer condição baseada em `TipoFluxo`), feita pelo usuário antes da rodada pela Tykhe. Se a rodada acontecer antes da correção, o "Falha" aparece nas duas versões e não indica diferença entre elas.

**Caso 3. Desambiguação.** Relato: *"Meu marido foi preso semana passada depois de uma briga lá em casa e eu não sei o que fazer."* Depois, a resposta: *"Quero saber onde ele está preso e como visitar."*
- **Fixo, na 1ª resposta, se a IA achar o relato ambíguo:** `StatusFluxo` = `em_andamento` e **sem `TipoFluxo`**. O fluxo da Tykhe vai para "Orquestrador (rodadas seguintes)", e a 2ª chamada sai com o campo `resposta`, no mesmo chat.
- **Fixo, nas rodadas seguintes:** em no máximo 5 respostas a conversa sai da desambiguação, identificada ou redirecionada. Na 6ª, a API devolve `redirecionado`, `tipoCaso` = `outros`, **"Entendi. Vou te encaminhar para o atendimento de outros assuntos."**
- **Depende da IA:** se o relato é tido como ambíguo, o texto da pergunta e para onde a 2ª resposta leva (o esperado é pessoa presa, `TipoFluxo` = `3df874f2-675a-4c43-9ec7-480f7c702f50`).

**Caso 4. Conversa até o fim.** Num chat novo, o relato do caso 1. À pergunta "Você é a vítima de violência doméstica?", responder **Não**. Depois, mandar mais uma mensagem qualquer no mesmo chat.
- **Fixo:** `StatusFluxo` = `handoff_humano`; `RespostaFluxo` = **"Esse atendimento é destinado apenas para quem é vítima da violência. Vou encaminhar você para um atendente humano."** (fixture `violencia-domestica-handoff-nao-vitima-200`, gravada contra develop @ `1157a6d`).
- **Fixo, na mensagem seguinte:** a API responde **409** (atendimento já concluído). No fluxo da Tykhe, cai no grupo "Falha", porque a Chamada API só tem a saída "falhou" (fixture `erro-atendimento-ja-concluido-409`).

**Registro de cada rodada:** a data, a versão (TypeScript ou Python), e para cada caso os campos de depuração do fluxo da Tykhe e o texto que chegou ao WhatsApp. Uma diferença na parte fixa entre as duas rodadas é falha da troca; na parte da IA, é variação a anotar.

### O histórico num rollback (registrado em 2026-10-20)

Duas coisas diferentes:

**1. Retomar a conversa: não é viável, e fica como está.** As duas versões serializam o checkpoint de forma incompatível, e por isso a versão Python grava no schema `checkpoint_py`, e não nas tabelas que a versão TypeScript usa em `public`. Depois de um rollback, a versão TypeScript não enxerga as conversas que a Python começou.

**2. O histórico para análise sobrevive.** Um rollback troca a imagem e não mexe no banco: as tabelas de `checkpoint_py` continuam lá, com o estado de cada conversa conduzida pela versão Python.

> **⚠ Não limpar o `checkpoint_py` num rollback achando que é resíduo.** É o único lugar com o estado completo das conversas da versão Python. Apagá-lo é uma decisão separada, com o descarte desses dados tratado como tal: eles contêm dado pessoal (CPF, nome, relato).

**A tabela `atendimentos` é compartilhada e um rollback não a afeta** (conferido no código das duas versões, 2026-10-20):
- o `CREATE TABLE`, os `ALTER TABLE` e o `UPDATE` de desfecho são idênticos em `src/maria/shared/atendimentos_db.py` e no `atendimentosDb.ts` de develop @ `1157a6d`;
- as duas gravam no schema padrão: o pool da `atendimentos` não fixa `search_path` (só o do checkpointer fixa `checkpoint_py`);
- as duas leem o `DATABASE_URL` da mesma chave do mesmo segredo de cada ambiente (`ecs.tf`, `release.tf`). Que o valor seja o mesmo antes e depois da troca não foi lido no segredo: a conferir na janela.

É ela que importa para análise: guarda o fluxo, o desfecho (`status_final`, `destino`, `motivo_handoff`), os tokens e as datas, e alimenta os painéis. As linhas gravadas pela versão Python continuam valendo depois de um rollback, no mesmo formato.

**O que se perde, ou fica incompleto, para análise num rollback:**
- **O desfecho dos atendimentos em andamento na hora do rollback.** A `atendimentos` só recebe desfecho e tokens no `concluir()`. Uma conversa que a versão Python começou e não terminou fica com a linha sem `status_final` e sem tokens. O que a versão TypeScript faz quando essa pessoa manda a próxima mensagem não foi executado. Se ela concluir, grava o desfecho dela, sem os tokens das rodadas da Python. O estado até ali continua no `checkpoint_py`, para recuperação manual.
- **Os tokens das rodadas já feitas nessas conversas.** Ficam acumulados no estado (`tokensGastos`), ou seja, no `checkpoint_py`, e não na tabela.
- **Os desfechos do orquestrador nunca estiveram na `atendimentos`**, em nenhuma das duas versões: a rota do orquestrador só cria a linha quando identifica um fluxo da Maria. `redirecionado`/`tipoCaso` e as rodadas de desambiguação ficam nos logs e no checkpoint (`orquestrador:<chatId>`). Os logs do CloudWatch não dependem da versão. As conversas da versão Python continuam no `checkpoint_py`. Não é perda causada pelo rollback, mas quem analisar o orquestrador precisa saber que a tabela não o cobre.

## Decisões em aberto

1. **Major do Postgres de produção. Valor provisório: 16**, na imagem `pgvector/pgvector:pg16` do CI. A conferir com `SELECT version()` no RDS (do stack antigo). Se for outra, o ajuste é uma linha no `ci.yml`.
2. **Nome do schema do checkpointer. Valor provisório: `checkpoint_py`** (`SCHEMA_CHECKPOINT` em `shared/checkpointer.py`). O schema separado foi aprovado na #208, mas o nome não tinha sido definido.
3. **Threads `orquestrador:*` no corte:** decididas na issue do corte.
4. **Token do Verde em release:** pré-requisito do corte (detalhes na #208).
5. **Espera por conexão do pool. Valor provisório: 120 s** (`ESPERA_POR_CONEXAO_S` em `shared/pool.py`). Requisito registrado em 2026-10-20: banco fora do ar deve falhar rápido. Com 120 s, uma pessoa no WhatsApp pode ficar até 120 s sem resposta durante uma queda do banco. O `connect_timeout` não resolve isso, porque não limita quem espera o pool (seção "Prazos").
   - **Como chegamos em 120 s:** aproximação do `ConnectionBorrowTimeout` do RDS Proxy (padrão da AWS), pensada para o **pool cheio com o banco no ar**. O caso de **banco indisponível** nunca foi avaliado com esse número: é outro problema no mesmo parâmetro, o padrão "parâmetro com nome familiar e semântica diferente" outra vez (a acrescentar à lista do comentário 12 da #208).
   - **Lido em develop:** no `pg-pool` 3.14, cada consulta sem conexão livre abre um cliente próprio (`index.js:235`), e o erro de conexão vai direto para quem pediu (`index.js:283`), sem prazo no meio.
   - **PENDÊNCIA, antes de escolher o valor: medir no Linux quanto o `pg` leva para devolver erro a quem pede conexão com o banco fora do ar**, e o mesmo para o pool Python. Não pode ser medido no Windows, onde a recusa da conexão leva cerca de 2 s e o libpq não a percebe. As sondas estão prontas: `.sonda/pool-banco-fora.mts` no worktree de develop (o `pg`, mesmo `new Pool({ connectionString })` das stores) e uma sonda Python com o prazo real do código. Medir nos dois casos: conexão recusada (porta fechada) e pacote descartado (host que não responde).
   - **O que a medição decide:** se o `pg` devolve o erro em segundos e o Python espera 120 s, a tradução piorou, e é **correção de migração**, com commit próprio na `migration`. Se o `pg` também fica pendurado, é **defeito herdado**, registrado como melhoria. Isso muda quem decide e com que urgência. O rascunho da issue espera essa medição.
   - **FECHADA em 2026-10-20: correção de migração, aprovada e feita na branch do corte (#268).** Medido em containers Linux, duas consultas por caso:

     | Banco fora do ar | `pg` de develop (8.23.0, pg-pool 3.14.0) | pool Python antes | pool Python depois |
     |---|---|---|---|
     | Conexão recusada | erro em 0,00 s | `PoolTimeout` em 120 s | erro da conexão abaixo de 1 s |
     | Pacote descartado | erro em 21 s | `PoolTimeout` em 120 s | `PoolTimeout` no prazo do pool |

     `PoolComoPg` (`shared/pool.py`) entrega o erro de conexão a quem está na fila e encerra a tentativa sem retentativa em segundo plano, como o `newClient` do `pg-pool`. O pool cheio com o banco no ar não muda. `tests/shared/test_pool_banco_fora.py` mede o tempo até o erro. Mutação conferida em Linux: sem a correção, o teste falha com `PoolTimeout` em 5 s. **Lição:** o `PoolTimeout` é subclasse de `OperationalError`, e a primeira versão do teste aceitava os dois. A mutação mostrou isso, e o teste passou a recusar o `PoolTimeout` explicitamente.

6. ~~Como as respostas gravadas evoluem depois do corte~~ **Decidida em 2026-10-20:** ficam congeladas, e o contrato atual é conferido por testes escritos. Ver a seção "As respostas gravadas são evidência, não teste de regressão".

*A decisão 5 (contador com texto vindo da Tykhe, D-1) foi fechada em 2026-10-16: divergência aceita (tabela "Divergências aceitas").*

## Resultado do `langgraph.json` com fábrica

**Funciona.** Testado em 2026-10-09 com LangGraph CLI 0.4.33 (langgraph-api 0.15.4), no Windows (`langgraph dev` precisou do pacote `colorama` ali). Uma fábrica assíncrona (`async def criar_grafo(config)`) é registrada como assistant, e um run devolve o estado. O `langgraph.json` aponta para `criar_grafo` nos dois fluxos, mas esses arquivos só existem a partir do módulo `fluxos`: até lá, o Studio local não sobe.

## Índice de issues: o canônico é o comentário da #208

- **Índice canônico:** [comentário da #208](https://github.com/dgd-dprj/maria-langgraph-pp/issues/208#issuecomment-6222948856). Ele traz:
  - todas as issues ligadas à migração;
  - o estado no GitHub e a **situação explícita**: mergeada na migration; corrigida em develop e pendente na migration; aprovada, aguardando janela; aguardando decisão; aguardando dado externo;
  - a data e o comando que gerou o índice.
- **Cópias:** `docs/migracao/INDICE-ISSUES.md` (no repositório) e `migracao-specs/INDICE-ISSUES.md` (local). Se divergirem, vale o comentário.
- **A cópia do repositório anda na branch do módulo seguinte** (achado C3 da spec 09): entre o merge de um módulo e a branch do próximo, a cópia na `migration` fica atrás do comentário. Depois do último módulo, a atualização vai num commit próprio na `migration`.
- **Rotina ao fim de cada módulo:**
  1. fechar a issue com comentário;
  2. apagar a branch;
  3. **editar o comentário do índice**, com `gh api -X PATCH repos/dgd-dprj/maria-langgraph-pp/issues/comments/6222948856 -F body=@<arquivo>`;
  4. atualizar as cópias.
- **Por quê:** "fechada" no GitHub não quer dizer correção na `migration`. **Um índice desatualizado é pior que nenhum.**

## Pendências operacionais

- **Remover o worktree de captura.** As fixtures de contrato e a caracterização da dupla contagem foram gravadas num worktree destacado de `develop` @ `4e695f2`, registrado no git local de quem fez a captura (`git worktree list`). Ele é removido com `git worktree remove <caminho>` depois que as fixtures estiverem no primeiro commit de `migration` (feito na fundação) e o teste de caracterização (`caracterizacao-tokens-subgrafo.test.ts`, já copiado para fora do worktree) tiver sido traduzido no módulo `subgrafos`.
- **Build da imagem Docker** não pôde ser rodado na máquina da fundação: o Docker Desktop não inicia porque a virtualização está desativada ali (WSL2). A verificação passou para o job `imagem` do CI. Localmente, só foi possível simular a instalação da imagem (`uv sync --frozen --no-dev --no-editable` num diretório limpo, sem o código-fonte solto): o servidor subiu com `APP_ENV=production` e o `/health` respondeu 200.
