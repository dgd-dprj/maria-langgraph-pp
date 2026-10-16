# SDD — Módulo `persistencia`

Parte de #208. Branch: `refactor/216-persistencia-python`, criada a partir de `migration` depois da fundação (#209). Fonte de comportamento: `develop` @ `4e695f2`.

Arquivos de origem → destino:

| Origem (develop) | Destino (migration) |
|---|---|
| `src/shared/atendimentosDb.ts` | `src/maria/shared/atendimentos_db.py` |
| `src/shared/perguntasDb.ts` | `src/maria/shared/perguntas_db.py` |
| `src/shared/fluxosPlanejadosDb.ts` | `src/maria/shared/fluxos_planejados_db.py` |
| `src/shared/embeddingsFluxos.ts` | `src/maria/shared/embeddings_fluxos.py` |
| `src/shared/perguntasDb.test.ts`, `src/shared/embeddingsFluxos.test.ts` | `tests/shared/test_perguntas_db.py`, `tests/shared/test_embeddings_fluxos.py` |

---

## 1. Contexto

Quatro stores dão ao serviço o que o checkpoint do LangGraph não dá:

- **`atendimentos`**: liga cada `chatId` a exatamente um `flowId`. O checkpoint é indexado só por `thread_id = chatId`, sem separar fluxo. A store também guarda o desfecho (lido pelo painel id 12 do Grafana, via SQL) e o controle de TTL de inatividade (issue #166).
- **`perguntas` / `assuntos_verde` / `flow_assuntos`**: a árvore de perguntas do Verde por categoria, coletada pelo script de crawl. O orquestrador lê só a pergunta raiz (issue #32).
- **`fluxos_planejados`**: o catálogo de categorias que a Maria reconhece, mas que caem no grafo padrão.
- **`fluxo_embeddings`**: os vetores do catálogo em pgvector, usados para cortar os candidatos antes da classificação por IA (issue #8).

Todas as stores têm duas implementações:
- **Postgres**, quando `DATABASE_URL` existe.
- **Em memória**, quando não existe. É o que os testes usam.

A escolha acontece uma vez por processo e fica memoizada.

## 2. Contrato

Interfaces públicas, que os outros módulos consomem. Os nomes viram snake_case; os campos dos objetos de domínio continuam em camelCase, porque viram estado de grafo, JSON ou log.

### `atendimentos_db`

```python
async def obter_atendimentos_store() -> AtendimentosStore

class AtendimentosStore(Protocol):
    async def registrar(self, chat_id: str, flow_id: str) -> RegistroOk | RegistroConflito
    async def buscar_flow_id(self, chat_id: str) -> str | None
    async def concluir(self, chat_id: str, dados: ConclusaoAtendimento) -> None
    async def buscar_atividade(self, chat_id: str) -> AtividadeAtendimento | None
    async def marcar_atividade(self, chat_id: str) -> None
    async def marcar_aguardando_confirmacao_ttl(self, chat_id: str, resposta_pendente: str) -> None
    async def resolver_confirmacao_ttl_continuar(self, chat_id: str) -> str | None
```

- `RegistroOk = {"ok": True}`. `RegistroConflito = {"ok": False, "flowIdExistente": str}`.
- `ConclusaoAtendimento`: `statusFinal` (`"concluido" | "handoff_humano" | "expirado"`), mais `destino`, `motivoHandoff` e `tokensGastos` (`{input, output, total}`), todos opcionais.
- `AtividadeAtendimento`: `atualizadoEm` (datetime com fuso), `statusFinal` (`str | None`), `aguardandoConfirmacaoTtl` (`bool`), `respostaPendente` (`str | None`).

### `perguntas_db`

`obter_perguntas_store()` e os métodos `inserir_pergunta`, `inserir_assunto`, `inserir_flow_assunto`, `listar_perguntas_por_flow`, `buscar_pergunta_raiz`, `listar_assuntos_por_flow` e `limpar_flow`. Tipos `PerguntaArvore`, `AssuntoVerde`, `FlowAssunto` e `AssuntoDoFlow`, com os mesmos campos de `perguntasDb.ts:13-62`.

### `fluxos_planejados_db`

- `listar_fluxos_planejados()`, `buscar_fluxo_planejado_por_id(id)` e `texto_para_classificacao(f)`.
- Os auxiliares de teste `adicionar_planejado_de_teste(f)` e `remover_planejado_de_teste(id)` funcionam só com a store em memória e lançam a mesma mensagem fora dela.

### `embeddings_fluxos`

- `buscar_candidatos(mensagem, k, catalogo) -> list[FluxoParaIndexar]`.
- `aquecer_catalogo(catalogo) -> None`.

### Esquema SQL

Idêntico ao atual: mesmos nomes de tabela, coluna, índice e tipo, e as mesmas instruções idempotentes, na mesma ordem.

- `atendimentos`:
  1. `CREATE TABLE IF NOT EXISTS`
  2. `ALTER ... ADD COLUMN IF NOT EXISTS` das colunas de desfecho
  3. `ALTER ... ADD COLUMN IF NOT EXISTS` das colunas de TTL
  4. `ALTER COLUMN atualizado_em SET DEFAULT now()`
  5. `UPDATE ... SET atualizado_em = criado_em WHERE atualizado_em IS NULL`
- `perguntas`, `assuntos_verde`, `flow_assuntos` e os dois índices `*_flow_id_idx`.
- `fluxos_planejados`, mais o `ALTER ... ADD COLUMN IF NOT EXISTS mensagem_fixa`.
- `CREATE EXTENSION IF NOT EXISTS vector` e `fluxo_embeddings` com `vector(1024)`.

O texto SQL de cada instrução é copiado sem alteração, salvo a sintaxe de parâmetro (ver 3.2).

## 3. Comportamento

### 3.1 Escolha da implementação e memoização

- Cada `obter_*` lê `DATABASE_URL` na primeira chamada e memoiza o resultado por processo. A memoização é por promessa ou tarefa, de modo que chamadas concorrentes recebem a mesma inicialização.
- **`atendimentos`**: a criação do esquema roda **dentro** de `obter_atendimentos_store()`. Se ela falhar, o objeto memoizado continua falhando em todas as chamadas seguintes, sem nova tentativa. Isso é igual a `atendimentosDb.ts:237-243`.
- **`perguntas` e `fluxos_planejados`**: a store é devolvida na hora, e a criação do esquema dispara na construção. Cada método aguarda essa inicialização antes de consultar. Se ela falhar, todas as chamadas falham, sem nova tentativa (`perguntasDb.ts:120-156`, `fluxosPlanejadosDb.ts:85-100`).
- **`embeddings`**: a criação da extensão e da tabela também dispara na construção e é aguardada pela indexação. A indexação é memoizada **com reinício em caso de falha** (`embeddingsFluxos.ts:152-160`): se falhar, a próxima chamada tenta de novo.
- **Fechamento (novo em relação a develop, sem efeito observável).** Cada store expõe `fechar_*()`, que fecha o pool e zera a memoização, no mesmo padrão do `fechar_checkpointer()` da fundação. O `finally` do lifespan em `app.py` chama esses fechamentos depois do checkpointer. Motivo: o pytest-asyncio cria um event loop por teste, e um pool memoizado aberto no loop de um teste quebra no seguinte. Em develop, o Node tem um único loop e os pools nunca são fechados. Os testes usam uma fixture que fecha as stores antes e depois de cada teste, como `tests/shared/test_checkpointer.py`.
- **Ordem de inicialização.** Este módulo acrescenta ao `INICIALIZADORES_PADRAO` de `src/maria/app.py` (criado na fundação), **depois** do checkpointer, a mesma sequência de `app.ts:40-43`:
  1. `obter_atendimentos_store()`;
  2. `obter_perguntas_store()`, seguido de `listar_perguntas_por_flow("00000000-0000-0000-0000-000000000000")`, para forçar o esquema;
  3. `listar_fluxos_planejados()`.

  O `fluxo_embeddings` **não** entra no startup. Ele é criado no pré-aquecimento disparado depois que o servidor sobe, sem bloquear (`server.ts:16-18`), ou na primeira busca, o que vier antes. O pré-aquecimento é ligado pelo módulo `api`. O lifespan da fundação garante que os inicializadores terminam antes do `/health`; este módulo acrescenta um teste de que a lista padrão tem o checkpointer primeiro e as três stores depois, nessa ordem.

### 3.2 Diferenças entre `pg` e `psycopg` que precisam ser neutralizadas

| Ponto | `pg` (develop) | `psycopg` (padrão) | O que a tradução faz |
|---|---|---|---|
| Sintaxe de parâmetro | `$1`, `$2`; o mesmo `$5` reaparece em `DO UPDATE SET` (`perguntasDb.ts:164`, `:173-174`, `:192`) | `%s` posicional, sem reuso por número | Usa parâmetros nomeados (`%(textoPergunta)s`) onde há reuso. O SQL resultante é equivalente |
| Coluna `UUID` (`atendimentos.flow_id`) | `string` em minúsculas | `uuid.UUID` | Converte com `str()` em `registrar` (comparação e `flowIdExistente`) e em `buscar_flow_id`. Sem isso, `registrar` acusa conflito falso, porque `UUID != str`, e a rota devolve 409 para um `chatId` + `flowId` legítimo |
| `TIMESTAMPTZ` | `Date`, com precisão de **milissegundo**. O Postgres guarda microssegundo; é o driver que descarta na leitura | `datetime` com fuso, com precisão de **microssegundo** | **Nada.** Mantém o microssegundo. Ver o motivo abaixo |
| `INTEGER` | `number` | `int` | Nada |
| `JSONB` (`opcoes`, `documentos_necessarios`) | Objeto já interpretado | Objeto já interpretado | Na escrita, mantém o texto JSON com cast explícito `::jsonb`, como hoje (`JSON.stringify` → `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`) |
| `TEXT[]` (`palavras_chave`) | `string[]` | `list[str]` | Nada |
| `NULL` → ausente | `?? undefined` | `None` | Os objetos de domínio **omitem** a chave quando o valor é `None`, onde o original faz `?? undefined` (`mensagemFixa`, `nomeMateria`, `descricao`, `txDocumentosNecessarios`, `statusFinal`, `respostaPendente`). Em `PerguntaArvore`, `idItemCategoria` e `veioDaRespostaId` continuam `None`, porque o original devolve `null` ali, e não `undefined` |
| `rowCount` em `INSERT ... ON CONFLICT DO NOTHING RETURNING` | 0 ou 1 | `cursor.rowcount` | Mesma semântica |
| Pool | `new Pool(...)` (`pg-pool` 3.14): preguiçoso, conexão só na primeira consulta, máximo 10; **conexão ociosa fecha em 10 s** (`idleTimeoutMillis`); **espera sem limite** por conexão quando o pool está cheio (`connectionTimeoutMillis` = 0), mas **com o banco fora do ar devolve o erro de conexão a quem pediu** (`newClient`); conexões sem idade máxima; cada consulta como transação própria; só statements sem nome | `AsyncConnectionPool`: abre `min_size` conexões ao iniciar (padrão 4); ociosa fecha em **600 s** (`max_idle`); espera no máximo **30 s** (`timeout`) e lança `PoolTimeout`; recicla cada conexão a cada **3600 s** (`max_lifetime`); com o banco fora do ar, tenta reconectar em segundo plano e **não avisa quem espera**; transação implícita; prepara a consulta depois de 5 execuções | `min_size=0`, `max_size=10`, `max_idle=10.0`, `timeout=120.0` (**provisório**, decisão em aberto na #208: com `math.inf`, o banco fora do ar pendurava a requisição para sempre; 120 s é o `ConnectionBorrowTimeout` padrão do RDS Proxy, a melhor aproximação disponível), `max_lifetime=math.inf`, e conexões com `autocommit=True` e `prepare_threshold=None` (sem prepared statements: `0` faria o contrário e fixaria a sessão no RDS Proxy), reproduzindo o `pg`. O pool é criado com `open=False` e aberto explicitamente com `await pool.open()`, o padrão recomendado pela biblioteca. **A função já existe: `criar_pool` em `shared/pool.py`, entregue na fundação (PR #213), que o checkpointer usa. As quatro stores só a usam**, sem repetir parâmetros. Isso não é a consolidação dos pools, que continua fora do escopo |

**Por que o microssegundo fica (decidido).** A precisão só mudaria o contrato se algum timestamp atravessasse a fronteira HTTP. Nenhum atravessa: nenhuma das 50 fixtures de contrato tem timestamp no corpo de resposta, e nenhuma rota ou `api.ts` de `develop` serializa `criado_em`, `concluido_em` ou `atualizado_em`. Truncar seria escrever código cuja única função é reproduzir a perda de precisão de um driver.

`TTL_INATIVIDADE_HORAS=0` é um controle de teste, não configuração de produção (`atendimentos.ts:22-26`): ele existe para forçar a expiração sem esperar tempo real. Com o TTL medido em horas, o microssegundo é irrelevante na fronteira real. Os testes de TTL traduzidos garantem um intervalo maior que zero entre a atividade e a resposta, sem depender de colisão no mesmo milissegundo.

**Por que `min_size=0` não é detalhe (decidido).** Com o padrão do `psycopg_pool`, os cinco pools (quatro stores e o checkpointer) abririam 20 conexões no startup contra o RDS Proxy, que é compartilhado com o stack antigo. Seria uma mudança de comportamento visível para um sistema que não pertence a este repositório. Consolidar os cinco pools em um só seria melhor, mas é melhoria, não tradução. Fica registrada no `MIGRACAO.md` como melhoria fora do escopo e não entra no código.

### 3.3 `pgvector` com cast manual

- O vetor trafega como texto `'[v1,v2,...]'`, com cast `::vector`, sem o pacote `pgvector` (`embeddingsFluxos.ts:95-100`). A tradução mantém o cast manual e não introduz o adaptador `pgvector` do Python. Isso seria dependência nova.
- Formato numérico: JS escreve `1` para inteiros e `1e-7` para expoentes; Python escreve `1.0` e `1e-07`. O pgvector aceita os dois e o valor armazenado é o mesmo. Um teste fixa que um vetor com inteiro, decimal e expoente faz ida e volta sem diferença numérica.
- `WHERE id = ANY($2)` recebe a lista de ids. O psycopg adapta `list[str]` para `text[]`, que é o mesmo tipo.
- `ORDER BY embedding <=> $1::vector LIMIT $3`. Em caso de empate de distância, a ordem não é determinística nem hoje.
- **Indexação:** lotes de 10 itens concorrentes (`CONCORRENCIA = 10`), um lote por vez. Um embedding e um `UPSERT` por item.

### 3.4 Embeddings (Bedrock)

- Modelo: `BEDROCK_EMBEDDING_MODEL_ID`, padrão `amazon.titan-embed-text-v2:0`. Região: `AWS_REGION`, padrão `us-east-1`. Dimensão: 1024.
- O texto enviado substitui `\n` por espaço. É o que o `BedrockEmbeddings` do JS faz (`@langchain/aws/dist/embeddings.js:75`). O do Python substitui `os.linesep`, que é `\n` no container Linux, mas seria `\r\n` no Windows. A tradução faz a substituição explícita de `\n` antes de chamar a biblioteca, para não depender do sistema operacional.
- Corpo da requisição: só `inputText`. Nenhum parâmetro novo (`dimensions`, `normalize`). A normalização do lado do cliente do Python (`normalize=False`) continua desligada.
- **`APP_ENV=test` nunca chama o Bedrock.** O embedding falso soma os **code units UTF-16** em 16 posições (`embeddingsFluxos.ts:39-44`). Em Python, `ord()` itera code points. **Decidido: reproduzir a semântica UTF-16**, com a soma iterando `texto.encode("utf-16-le")` em pares de bytes.
  - Motivo: a ordem dos candidatos depende desse vetor. Se ela mudar, um teste que afirma qual fluxo foi escolhido passa a ter outro resultado em Python, e a tradução deixa de ter "os mesmos cenários", que é critério de aceite da #208.
  - Hoje nenhum arquivo de `src/`, `test/`, `test-integracao/` ou `scripts/` de `develop` tem caractere fora do BMP. A diferença ainda não se manifesta, mas apareceria sem aviso no primeiro emoji acrescentado a um teste.

### 3.5 Busca em memória

- Se `len(catalogo) <= k`, devolve o catálogo **inteiro, na ordem recebida**, sem gerar embedding nenhum. O mesmo vale na variante Postgres, que nesse caso nem indexa.
- Calcula o cosseno com o embedding da mensagem; o cache é por `f.id`, não por descrição. Ordena de forma estável por similaridade decrescente, então empates mantêm a ordem do catálogo, e corta em `k`.
- Similaridade é 0 quando a norma de um dos vetores é 0.

### 3.6 `registrar` (atendimentos)

- **Postgres:**
  1. `INSERT ... ON CONFLICT (chat_id) DO NOTHING RETURNING flow_id`.
  2. Se inseriu, devolve `ok`.
  3. Se não inseriu, faz `SELECT flow_id` e compara o texto com o `flowId` recebido.
  4. Se a linha sumiu entre as duas consultas, considera o `flowId` recebido.
- **Em memória:** a mesma regra, com `atualizadoEm = agora`, `statusFinal = None`, `aguardandoConfirmacaoTtl = False` e `respostaPendente = None`.
- **Diferença entre implementações que se mantém.** Na de memória, `concluir` grava **só** `statusFinal` (`atendimentosDb.ts:70-73`). Na Postgres, grava `concluido_em`, `status_final`, `destino`, `motivo_handoff` e `tokens_*`, com `None` → `NULL`.
- **Terceira divergência entre as stores: defeito de produção, reproduzido de propósito ([#217](https://github.com/dgd-dprj/maria-langgraph-pp/issues/217)).** Em `resolver_confirmacao_ttl_continuar`, a store Postgres executa `SET resposta_pendente_ttl = NULL … RETURNING resposta_pendente_ttl` (`atendimentosDb.ts:222-228`). O `RETURNING` devolve o valor já atualizado, ou seja, sempre `NULL`, e a função devolve `None`. A store em memória guarda o valor antes de limpar e devolve a resposta pendente (`atendimentosDb.ts:95-103`). Em produção, a rota processa `""` no lugar da resposta que a pessoa deu depois de confirmar que quer continuar. **O SQL é copiado sem alteração**; um teste `postgres` fixa o `None`, com comentário dizendo que é deliberado e temporário e com link para a #217. A correção segue a regra da #217: depois do merge, salvo se a contagem em produção for relevante ou houver caso em fluxo sensível, quando ela vai antes, em `develop`, e é trazida traduzida.
- **Quarta divergência entre as stores (encontrada na tradução, não estava nesta spec).** `listar_fluxos_planejados` ordena por `id` no Postgres (`ORDER BY id`, `fluxosPlanejadosDb.ts:123`) e mantém a ordem de inserção em memória (`fluxosPlanejadosDb.ts:67-69`). Reproduzida e fixada por teste nos dois lados.

### 3.7 Árvore de perguntas

- `listar_perguntas_por_flow` ordena por `ordem` na store Postgres. **Na store em memória, mantém a ordem de inserção, sem ordenar** (`perguntasDb.ts:96-98`). A diferença é mantida.
- `buscar_pergunta_raiz` faz `ordem = 0 LIMIT 1` no Postgres e devolve a primeira inserida com `ordem === 0` na memória.
- Na store em memória, `listar_assuntos_por_flow` lança `flowAssunto aponta pra idAssunto {id} sem detalhe inserido` quando falta o detalhe.
- `limpar_flow` apaga `perguntas` e `flow_assuntos` do `flowId`, **nunca** `assuntos_verde`.
- Os `INSERT ... ON CONFLICT DO UPDATE` atualizam exatamente as colunas de hoje. Por exemplo, em `perguntas`, `flow_id` e os ids de origem **não** são atualizados no conflito.

## 4. Casos de erro

| Situação | Comportamento esperado (igual a develop) |
|---|---|
| Postgres fora do ar no startup | `obter_atendimentos_store()` falha. A aplicação não sobe e o `/health` nunca responde. Sem nova tentativa dentro do processo. Na fundação, isso é o uvicorn encerrando o processo com código 3 (`tests/test_app.py`), e o ECS recria a task |
| `flowId` que não é UUID chegando a `registrar` | Erro do Postgres (`invalid input syntax for type uuid`) propagado; vira 500 na rota. Só acontece pelo orquestrador, se um id de `fluxos_planejados` (coluna `TEXT`) não for UUID |
| Falha do Bedrock na indexação | A promessa memoizada é reiniciada e a próxima busca tenta de novo. A busca atual falha e o erro se propaga para o orquestrador, como hoje |
| Falha na criação do esquema de `perguntas` ou `fluxos_planejados` | Todas as chamadas dessa store falham até reiniciar o processo |
| Auxiliar de teste com `DATABASE_URL` definido | Lança `adicionarPlanejadoDeTeste só funciona sem DATABASE_URL` (o texto da mensagem é mantido) |

## 5. O que não muda

- Nomes de tabela, coluna, índice, tipo e valor padrão. O painel id 12 consulta `flow_id`, `status_final`, `concluido_em` e `criado_em`.
- Os campos dos objetos de domínio, em camelCase.
- A escolha Postgres ou memória por `DATABASE_URL`.
- A ausência de FK entre `perguntas.flow_id` e qualquer tabela.
- A falta de dependência `pgvector`.
- A falta de nova tentativa nas stores, salvo a indexação de embeddings.
- O que o `concluir` em memória grava, que é menos do que o Postgres grava.
- O que `resolver_confirmacao_ttl_continuar` devolve em cada store: `None` no Postgres, a resposta pendente em memória (#217).
- A ordem de `listar_fluxos_planejados`: por `id` no Postgres, de inserção em memória.

## 6. Observabilidade

Linhas de log idênticas em mensagem (`msg`), nível e campos, no envelope pino da fundação:

| Origem | Nível | `msg` | Campos |
|---|---|---|---|
| `atendimentosDb.ts:151` | info (30) | `[atendimentosDb] tabela 'atendimentos' pronta (Postgres)` | — |
| `perguntasDb.ts:155` | info | `[perguntasDb] tabelas 'perguntas', 'assuntos_verde' e 'flow_assuntos' prontas (Postgres)` | — |
| `fluxosPlanejadosDb.ts:99` | info | `[fluxosPlanejadosDb] tabela 'fluxos_planejados' pronta (Postgres)` | — |
| `embeddingsFluxos.ts:114` | info | `[embeddingsFluxos] tabela 'fluxo_embeddings' pronta (pgvector)` | — |
| `embeddingsFluxos.ts:145` | info | `[embeddingsFluxos] catálogo (re)indexado` | `total` |
| `embeddingsFluxos.ts:176` | info | `[embeddingsFluxos] busca por similaridade concluída` | `candidatos`, `tempoMs` |

Nenhum dado pessoal no log. As stores não registram `chatId` nem conteúdo.

## 7. Testes que provam

**Traduzidos de develop**, mesmos cenários e mesmas asserções:
- `perguntasDb.test.ts` (6 testes);
- `embeddingsFluxos.test.ts` (4 testes, com o BDD da issue #8).

**Novos, para as divergências desta seção.** Os testes que dependem de banco ficam atrás do marcador `postgres` e rodam contra Postgres com pgvector, como serviço do CI. A suíte rápida (`pytest` sem marcador) continua sem banco, como em `develop`.
1. `[postgres]` `registrar` com um `flowId` já registrado no mesmo `chatId` devolve `ok`. Prova a conversão de `uuid.UUID` para texto.
2. `[postgres]` `registrar` com outro `flowId` devolve conflito, com `flowIdExistente` em `str` minúsculo.
3. `[postgres]` `buscar_flow_id` devolve `str`, não `uuid.UUID`.
4. `[postgres]` `concluir` grava `concluido_em`, `status_final`, `destino`, `motivo_handoff` e `tokens_*` juntos, e `None` vira `NULL`. É o caminho que o plano de corte (#208) usa para encerrar atendimentos: um teste em memória passaria sem provar nada, porque a store em memória grava só `statusFinal`.
5. `[postgres]` `buscar_atividade.atualizadoEm` devolve `datetime` com fuso. O valor não é truncado.
6. `[postgres]` Ida e volta de vetor `[1, 0.5, 1e-7, ...]` via cast `::vector`, sem diferença numérica.
7. Embedding falso de uma string com emoji igual ao valor de referência calculado em `develop` (soma por code unit UTF-16). Em memória.
8. `len(catalogo) <= k` devolve o catálogo na mesma ordem e não chama o gerador de embedding. Em memória.
9. Empate de similaridade mantém a ordem do catálogo. Em memória.
10. `[postgres]` `listar_fluxos_planejados` com `mensagem_fixa NULL` devolve um objeto **sem** a chave `mensagemFixa`.
11. `[postgres]` `PerguntaArvore` raiz devolve `idItemCategoria: None` e `veioDaRespostaId: None`, com a chave presente.
12. `[postgres]` `UPSERT` de pergunta com o mesmo `id` não altera `flow_id`.
13. `[postgres]` A indexação que falha na primeira tentativa é refeita na segunda chamada (memoização com reinício). **Corrigido na tradução:** esta spec dizia "em memória", mas só a variante Postgres indexa; a busca em memória não tem indexação nem aquecimento (`embeddingsFluxos.ts:69-93`). O gerador falso é substituído por vetores de 1024 posições, porque o de 16 não cabe em `vector(1024)`.
14. `[postgres]` Esquema: depois da inicialização, `information_schema.columns` de `atendimentos` lista exatamente as colunas, tipos e padrões esperados. Inclui `atualizado_em DEFAULT now()` e `aguardando_confirmacao_ttl NOT NULL DEFAULT false`.
15. `[postgres]` Pool: **antes da primeira consulta de cada store**, o pool dela não tem nenhuma conexão (`pool.get_stats()["pool_size"] == 0`, `min_size=0`); depois da primeira consulta, tem a conexão usada. A medida é pelas estatísticas de cada pool, e não por `pg_stat_activity`: no mesmo banco, o pool do checkpointer da fundação já mantém conexão ociosa depois do `setup()`, e o banco não distingue de qual pool ela é. Observação: atendimentos, perguntas e fluxos planejados consultam o banco na própria inicialização (esquema), então para elas a conexão aparece já no startup, como no `pg` de develop.
16. `INICIALIZADORES_PADRAO` tem o checkpointer primeiro e, depois, as três stores na ordem de `app.ts:40-43`. Em memória.
17. As quatro stores criam o pool por `criar_pool` (`shared/pool.py`), sem `AsyncConnectionPool` direto. Sem banco, interceptando `criar_pool`. Os valores dos parâmetros já são provados em `tests/shared/test_pool.py`, da fundação.
18. `[postgres]` `resolver_confirmacao_ttl_continuar` depois de `marcar_aguardando_confirmacao_ttl(chat_id, "123456789")` devolve **`None`**, e a coluna fica `NULL`; em memória, o mesmo caminho devolve `"123456789"`. Comentário obrigatório no teste: a divergência é deliberada e temporária, reproduz `develop` e está registrada na #217; não corrigir aqui. É também a confirmação, contra Postgres real, do defeito descrito na #217.

## 8. Critérios de aceite

- [ ] Os 10 testes traduzidos de develop passam com as mesmas asserções.
- [ ] Os 18 testes novos da seção 7 passam. Os marcados `[postgres]` rodam no CI com serviço Postgres e pgvector, na mesma major do RDS de produção (16, provisório). A suíte rápida roda sem banco.
- [ ] As quatro stores criam o pool por `criar_pool` (`shared/pool.py`, da fundação) e o abrem explicitamente com `await pool.open()`.
- [ ] Consolidação dos cinco pools registrada no `MIGRACAO.md` como melhoria fora do escopo.
- [ ] O SQL de cada instrução é textualmente igual ao de develop, salvo a sintaxe de parâmetro (revisão por diff).
- [ ] Nenhum ponto do código devolve `uuid.UUID` para fora do módulo. O `datetime` sai com fuso e com microssegundo, sem truncar (decisão 1).
- [ ] As linhas de log da seção 6 têm o mesmo `msg`, nível e campos.
- [ ] `ruff`, `ruff format --check`, `mypy` (strict no projeto inteiro, configuração da fundação) e `pytest` verdes, e os jobs `test` e `imagem` do CI verdes (obrigatórios na proteção de `migration`).
- [ ] Nenhuma dependência nova além das previstas. `psycopg[binary]` e `psycopg-pool` já vieram na fundação. **`langchain-aws` entra no `pyproject.toml` neste módulo** (para o `BedrockEmbeddings`), como dependência de runtime, com o `uv.lock` atualizado.
- [ ] **Logs de dependência (regra do `MIGRACAO.md`):** para cada dependência nova deste módulo, o PR responde o que ela registra por padrão, em que logger e em que nível, e confirma que nada com dado pessoal passa pela ponte da fundação (bibliotecas só de WARNING para cima). Aqui: `langchain-aws`, e com ele `boto3`/`botocore` (o botocore registra em DEBUG a requisição assinada, inclusive o corpo com o texto do embedding).
- [ ] `fechar_*()` de cada store chamado no `finally` do lifespan, depois do checkpointer.
- [ ] Toda decisão tomada durante o módulo registrada como comentário na #208 e no `MIGRACAO.md`.

## Decisões registradas nesta revisão

1. **Timestamp:** fica o microssegundo, sem truncar. Verificado: nenhuma das 50 fixtures e nenhuma rota de `develop` serializa timestamp.
2. **Pool:** `min_size=0`, `max_size=10` e abertura explícita. Consolidar os pools vai para o `MIGRACAO.md`, não para o código.
3. **Postgres no CI:** sim, com o marcador `postgres`, e a suíte rápida continua sem banco. Isso também serve ao módulo `corte`: o teste do encerramento por `store.concluir` precisa de Postgres real. Já entregue na fundação (#209, PR #213): o `ci.yml` tem o serviço pgvector 16 e a etapa `pytest -m postgres`.
4. **Embedding falso:** reproduz a semântica UTF-16.

## Releitura contra a fundação (2026-10-13)

Spec escrita antes da fundação e relida contra o que o PR #213 entregou. O que mudou:
1. **Ordem de inicialização:** as stores entram no `INICIALIZADORES_PADRAO` de `app.py`, depois do checkpointer, e não no módulo `api` (seção 3.1; teste 16).
2. **Fechamento das stores:** `fechar_*()` e chamada no `finally` do lifespan, por causa dos event loops por teste do pytest-asyncio (seção 3.1).
3. **Teste 15:** medido por `pool.get_stats()`, porque o pool do checkpointer já tem conexão no mesmo banco.
4. **Critério de aceite** que contradizia a decisão do microssegundo, corrigido.
5. **Dependências:** `langchain-aws` entra aqui; o resto já veio na fundação. mypy strict vale para o projeto inteiro.
6. **Postgres fora do ar no startup:** o processo sai com código 3, como provado na fundação.
7. **Achado novo: tempos do pool.** Nenhuma versão anterior desta spec, nem a fundação, reproduzia o tempo de ociosidade (10 s no `pg`, 600 s no `psycopg_pool`), a espera sem limite por conexão (contra 30 s e `PoolTimeout`) e a ausência de idade máxima (contra 3600 s). Sem o ajuste, cada pool manteria conexões ociosas no RDS Proxy compartilhado por 10 minutos em vez de 10 segundos. **Corrigido na própria fundação, antes do merge** (PR #213, commit `eb62fdf`): `shared/pool.py` com `criar_pool`, já usada pelo checkpointer. Este módulo só a usa nas quatro stores (teste 17).

Conferido e sem mudança: logger (`logger.info(msg, **campos)`, `None` omitido), envelope pino das linhas da seção 6, `APP_ENV`, marcador `postgres`, serviço pgvector 16 no CI.

## O que a tradução encontrou (2026-10-13)

Esta spec foi escrita e revisada por leitura de código, e relida contra a fundação. A tradução linha a linha ainda encontrou:

1. **Defeito de produção no TTL:** `resolver_confirmacao_ttl_continuar` devolve `None` no Postgres e descarta a resposta da pessoa ([#217](https://github.com/dgd-dprj/maria-langgraph-pp/issues/217)). Virou a terceira divergência.
2. **Quarta divergência:** a ordem de `listar_fluxos_planejados` (seção 3.6).
3. **O teste 13 não pode ser em memória:** só a variante Postgres indexa.
4. **Dois parâmetros de pool com nome familiar e semântica diferente:** `prepare_threshold=0` (no psycopg, prepara toda consulta; só `None` desliga) e `timeout=math.inf` (o psycopg_pool usa o mesmo parâmetro para pool cheio e banco fora do ar, que o `pg` trata de forma diferente). Os dois vieram da fundação e foram corrigidos neste módulo.

**Calibragem para os próximos módulos.** A spec previu três divergências entre as stores e a tradução achou quatro. As duas últimas, o defeito do TTL e a ordem dos fluxos planejados, só apareceram quando alguém traduziu linha a linha. Não é falha desta spec: é o limite de escrever especificação por leitura de código. As specs de integracoes e ia, escritas da mesma forma, devem ser lidas como ponto de partida, e a issue de cada módulo deve ser atualizada com o que a tradução encontrar **antes** de o PR abrir, para a revisão comparar o código contra o que de fato foi feito.

## Em aberto

- **Major do Postgres de produção. Valor provisório: 16**, usado na imagem pgvector do CI. Conferir com `SELECT version()` no banco de produção ou com quem administra o stack antigo, ao qual o RDS pertence (`infra/terraform/data.tf:6-13`). Se a major for outra, o ajuste é uma linha.
