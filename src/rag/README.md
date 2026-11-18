# RAG independente para a API Verde

Este diretório contém um projeto Python isolado da aplicação principal. Ele usa
o Swagger local para indexar os contratos da API Verde, gera embeddings com
Amazon Bedrock, persiste os vetores em um Postgres/pgvector próprio e recupera os
trechos mais próximos para explicar mensagens técnicas em linguagem simples.

Também oferece um índice separado para recuperar candidatos de um catálogo,
com busca semântica ou combinação semântica e lexical por RRF (k=60).

O fluxo segue o mesmo desenho de `guia-maria`: carregar documentos,
fragmentar, gerar embeddings, persistir, recuperar os trechos mais relevantes e
montar uma resposta fundamentada. Prisma não é necessário: a tabela e o índice
vetorial são criados por SQL em `src/rag/src/rag/vector_store.py`.

## Estrutura do código

| Arquivo                     | Responsabilidade                                                                            |
| --------------------------- | ------------------------------------------------------------------------------------------- |
| `src/rag/src/rag/ingest_documentos.py` | Lê OpenAPI (`swagger.json`/`openapi.json`) ou uma captura HTML e fragmenta as operações. |
| `src/rag/embeddings.py`     | Configura o modelo Titan Embeddings do Amazon Bedrock.                                      |
| `src/rag/vector_store.py`   | Cria a tabela `rag_documentos_swagger` e executa gravação e busca por cosseno no pgvector.  |
| `src/rag/retriever.py`      | Evita embeddings repetidos por hash, indexa documentos e recupera os três melhores trechos. |
| `src/rag/prompt.py`         | Orienta a explicação a usar linguagem simples e não extrapolar o contexto recuperado. |
| `src/rag/chain.py`          | Liga recuperação e geração da explicação com um modelo do Bedrock.                          |
| `src/rag/ingest.py`         | Permite executar a ingestão pela linha de comando.                                          |
| `src/rag/catalogo.py` | Define o formato dos candidatos e normaliza texto para busca lexical. |
| `src/rag/recuperador_catalogo.py` | Indexa e recupera candidatos por busca semântica ou fusão RRF. |
| `src/rag/api.py` | Expõe endpoints para indexar Swagger e catálogo, buscar trechos e explicar mensagens. |

O banco deste projeto é exclusivo: serviço `rag-postgres`, porta `55433`, banco
`rag_db` e volume `rag_pgvector_data`, separado do banco da aplicação principal.

## Executar e testar sem iniciar a aplicação principal

Pré-requisitos: Docker com Compose, Python 3.12, `uv` e credenciais AWS com
permissão para invocar os modelos configurados no Amazon Bedrock. O Swagger já
está em `documentos/swagger.json`; o índice inicial tem cerca de 100 trechos.

Na raiz do repositório:

```bash
docker compose -f src/rag/docker-compose.yml up -d
cp src/rag/.env.rag.example src/rag/.env.rag
uv sync --project src/rag --python 3.12
```

Edite `src/rag/.env.rag` para selecionar `AWS_PROFILE` ou configure as
credenciais AWS no ambiente. Ajuste `AWS_REGION` caso os modelos Bedrock não
estejam disponíveis em `us-east-1`. O exemplo separa a configuração do RAG do
`.env` da aplicação.

Indexe o Swagger. O primeiro comando chama Bedrock para gerar os embeddings; nas
execuções seguintes, documentos sem alteração são reaproveitados do Postgres:

```bash
uv run --project src/rag python -m rag.ingest
```

Inicie a API local de demonstração em outro terminal:

```bash
uv run --project src/rag uvicorn rag.api:app --app-dir src/rag/src --host 0.0.0.0 --port 8010
```

Abra `http://127.0.0.1:8010/docs` para explorar os endpoints. A sequência abaixo
demonstra indexação, busca e explicação:

```bash
curl http://127.0.0.1:8010/health
curl -X POST http://127.0.0.1:8010/api/index
curl -X POST http://127.0.0.1:8010/api/search \
  -H 'Content-Type: application/json' \
  -d '{"consulta":"O que significa erro de CEP inválido?","limite":3}'
curl -X POST http://127.0.0.1:8010/api/explain \
  -H 'Content-Type: application/json' \
  -d '{"mensagem":"CEP inválido","endpoint":"/integra/cep/{codigoCep}","metodo":"GET","status_http":400}'
```

`/api/search` serve para inspecionar quais documentos foram recuperados e suas
similaridades. `/api/explain` envia os trechos recuperados ao modelo de chat do
Bedrock e devolve a explicação com referências aos trechos usados. Se não houver
contexto com similaridade suficiente, a cadeia se abstém de inventar uma causa.

## Recuperar candidatos do orquestrador (#353 e #360)

Este recurso é uma preparação do lado do RAG: o consumidor envia o catálogo
completo (ou uma atualização parcial) para indexação. Cada candidato deve ter
`id`, `nome` e `descricao`; `palavras_chave` e `dados` são opcionais. `dados`
preserva identificadores de retorno, como `flowId`, `tipoCaso` ou a origem, sem
usá-los no texto de busca.

```bash
curl -X POST http://127.0.0.1:8010/api/catalog/index \
  -H 'Content-Type: application/json' \
  -d '{"candidatos":[{"id":"tykhe:novo-processo","nome":"Novo processo","descricao":"Pessoa precisa iniciar um processo na Defensoria.","palavras_chave":["ação nova","abrir processo"],"dados":{"tipoCaso":"novo-processo"}}]}'
curl -X POST http://127.0.0.1:8010/api/catalog/search \
  -H 'Content-Type: application/json' \
  -d '{"relato":"Quero abrir uma ação nova","limite":15}'
```

`/api/catalog/index` recebe o snapshot completo por padrão e remove do índice os
IDs que não vierem no pedido. Use `"sincronizar_completo": false` para apenas
adicionar ou atualizar os candidatos enviados. Hashes evitam gerar novamente
embeddings de candidatos inalterados. A persistência usa a tabela
`rag_catalogo_orquestrador`, separada de `rag_documentos_swagger`.

`/api/catalog/search` retorna até 15 resultados, estáveis em caso de empate. Por
padrão usa busca semântica. `ORQUESTRADOR_BUSCA_HIBRIDA` é lida a cada chamada e
só o valor exato `true` ativa a busca lexical em português combinada com a
semântica por Reciprocal Rank Fusion (RRF, k=60). Para comparar os modos durante
avaliação, o corpo pode definir `busca_hibrida: false` ou `true`; sem esse campo,
vale a variável de ambiente. A busca lexical normaliza caixa e acentos na
aplicação e usa `to_tsvector('portuguese', ...)` com índice GIN, sem exigir a
extensão `unaccent`.

Essa API prepara a recuperação e devolve candidatos com ranks e score RRF; ela
não escolhe o destino final nem chama o modelo de classificação. O consumidor
continua responsável por essa etapa. A busca híbrida deve permanecer desligada
até ser avaliada com relatos confirmados, porque a medição da #353 mostrou
regressão na métrica de candidatos.

Os testes unitários locais do ranking não usam banco nem Bedrock:

```bash
PYTHONPATH=src/rag/src src/rag/.venv/bin/python -m unittest discover -s src/rag/tests -v
```

Para desligar apenas o banco do RAG:

```bash
docker compose -f src/rag/docker-compose.yml down
```

Os vetores continuam no volume. Para apagar o índice local e começar do zero,
remova o volume dedicado com `docker compose -f src/rag/docker-compose.yml down
-v`.

## Limites

O Swagger descreve contratos técnicos; não garante explicar todas as mensagens
de erro nem traduz por si só conceitos jurídicos. Para ampliar a cobertura, devem
ser incluídos materiais institucionais aprovados como fontes separadas. O limiar
de similaridade em `.env.rag` é um ponto inicial para avaliação, não um valor
calibrado para produção. Envie à API somente a mensagem e o contexto mínimo da
chamada, sem payloads que possam conter dados pessoais.
