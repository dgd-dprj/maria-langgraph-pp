# SDD — Módulo `scripts`

Parte de #208. Issue: #252. Branch: `refactor/252-scripts-python`, a partir de `migration`. **Fonte de comportamento: develop @ `1157a6d`.** **As linhas citadas (`arquivo:linha`) são de `1157a6d`.**

**Regra desta spec** (a mesma da spec 07):
- **(lido):** a afirmação sobre develop veio da leitura do código. Cada uma vira cenário da conferência (seção 7) antes do PR.
- **(executado):** a afirmação já rodou.

| Origem (develop) | Destino (migration) |
|---|---|
| `scripts/coletarArvorePerguntasVerde.ts` (191 linhas) | `scripts/coletar_arvore_perguntas_verde.py` |
| `scripts/seedFluxosPlanejados.ts` (164 linhas, com o literal `DADOS_SEED` dos 74 registros) | `scripts/seed_fluxos_planejados.py` + `scripts/dados/fluxos_planejados.json` (os 74 registros) |
| `scripts/logs-prod.sh` (11 linhas) | já está na `migration`, idêntico (mesmo blob `9cfdd26`, modo 755). Ver D-3 |
| `scripts/README.md` | já está na `migration`, idêntico (blob `6156b29`), ainda falando de `.ts` e `pnpm`. Atualizado aqui |
| `package.json`: `seed:fluxos-planejados`, `coletar:arvore-perguntas-verde`, `logs:prod` | comandos `uv run` no README (D-2) |
| Testes de develop | **nenhum.** Os dois scripts não têm teste em develop (lido: nenhum `*.test.ts` importa `scripts/`) |

**Fora deste módulo:** a menção a `scripts/coletarArvorePerguntasVerde.ts` em `docs/arquitetura.md:67` (módulo documentacao).

**Nenhum dos dois scripts entra na imagem** (lido): o Dockerfile de develop copia só `dist/`, e o da `migration` copia só `src/`. São utilitários rodados à mão, de uma máquina com acesso ao banco.

---

## 0. O que já existe na `migration`

| Peça | Onde | Situação |
|---|---|---|
| `obter_perguntas_store()`, `limpar_flow`, `inserir_pergunta`, `inserir_assunto` (upsert por `id_assunto`), `inserir_flow_assunto` | `shared/perguntas_db.py` (persistencia) | Prontas, conferidas no módulo persistencia |
| `listar_fluxos_planejados()` (Postgres com `DATABASE_URL`, `ORDER BY id`) e o DDL de `fluxos_planejados` com o `ALTER ... mensagem_fixa` | `shared/fluxos_planejados_db.py` | Prontos. O DDL do seed é o mesmo texto (lido) |
| `fluxos_por_id`, `ID_VIOLENCIA_DOMESTICA` | `fluxos/__init__.py` | Prontos |
| `trim_js` e os auxiliares de semântica JS | `shared/_js.py` | Prontos |
| `python-dotenv` | dependência de `pyproject.toml`, usado em `main.py` | Pronto. `load_dotenv()` não sobrescreve variável já definida, como o `dotenv/config` |

O módulo é só a casca dos dois scripts e o arquivo de dados. Toda a gravação passa pelas stores que já existem.

## 1. Contexto

- **`coletarArvorePerguntasVerde` (issue #20):** varre a árvore de perguntas do Verde, categoria por categoria, e grava `perguntas`, `assuntos_verde` e `flow_assuntos`. O orquestrador usa essas tabelas na desambiguação. Roda sob demanda, quando a árvore do Verde muda. Fala com o Verde de verdade e exige `VERDE_JWT_TOKEN` e `DATABASE_URL`. **Não tem modo mock.**
- **`seedFluxosPlanejados` (issue #26):** migração única, já rodada em produção. Continua no repositório porque **é a única cópia dos 74 registros** de origem (README de `scripts/`). Serve para recriar `fluxos_planejados` do zero: banco novo ou recuperação de desastre.

## 2. A extração dos 74 registros

**É o único ponto da migração em que conteúdo é transcrito, e não traduzido.** Uma palavra-chave perdida ou alterada não quebra teste nenhum: só muda, em silêncio, o que o orquestrador reconhece.

### 2.1 O que o literal tem (executado em 2026-10-19, avaliando o literal de `1157a6d` com o Node)

| Medida | Valor |
|---|---|
| Registros | 74 |
| `id` únicos | 74 |
| `idCategoriaAssuntoVerde` únicos | 74 |
| Palavras-chave (soma das listas) | **1.744** |
| Palavras-chave repetidas dentro do mesmo registro | 0 |
| Registros com `palavrasChave: []` | **4** (ver 3.2, item 4) |
| Registros com `mensagemFixa` | 2: "reclamação trabalhista" (10085, 73 caracteres) e "loas" (10092, 67 caracteres) |
| Chaves usadas | `id`, `nome`, `descricao`, `idCategoriaAssuntoVerde`, `palavrasChave`, `mensagemFixa` |
| Textos fora da forma NFC | 0 |
| Textos com espaço na borda (`nome` e palavras-chave) | 0 |
| Escapes de string | **1**: `\"`, na palavra-chave `"sofri preconceito` de "direitos e diversidade", com a aspa solta (achado B4). Achado pelo leitor estrito na primeira execução do teste; uma contagem anterior, feita com `grep`, tinha dado 0 por erro de padrão |

### 2.2 Como extrair

- **Formato:** JSON em UTF-8, sem escapar acentos, na ordem do literal (registros e palavras-chave). `mensagemFixa` ausente continua ausente, e não vira `null`.
- **Extração:** o Node avalia o literal de `1157a6d`, como na medição da tabela acima, e grava o JSON. Quem interpreta os escapes de string é o próprio JavaScript, e não uma releitura nossa.

### 2.3 Verificação automática contra o literal de develop

**A fonte fica no repositório.** O arquivo `scripts/seedFluxosPlanejados.ts` de `1157a6d` entra como fixture, byte a byte, em `tests/fixtures/scripts/seedFluxosPlanejados-1157a6d.ts`. O teste confere primeiro que a fixture é o blob de develop: calcula o id git (`sha1("blob <tamanho>\0" + conteúdo)`) e compara com `265f1df4f64c5a34abf9e01ce421efa4822dc2e2`. Uma fixture editada à mão falha aí.

**Depois, o teste lê o literal com um leitor próprio, em Python,** e não com o Node da extração. São dois caminhos independentes, e eles precisam concordar. O leitor cobre só o que o literal usa: objetos, listas, strings com aspas duplas, inteiros, e um único escape, `\"`. Qualquer outra construção, inclusive outro escape, faz o teste falhar, em vez de ser ignorada.

**O teste compara (`tests/scripts/test_seed_extracao.py`):**
1. 74 `id` únicos nos dois lados;
2. o conjunto de `id` idêntico;
3. o total de palavras-chave idêntico (1.744);
4. **além do pedido:** cada registro igual campo a campo, inclusive a ordem das palavras-chave, a ausência de `mensagemFixa` e o texto exato das duas mensagens fixas;
5. a ordem dos registros igual.

O teste roda na suíte padrão, sem banco. Um registro trocado, uma palavra-chave a menos ou um acento normalizado diferente o faz falhar.

### 2.4 Ligação com a #249

As mensagens fixas da #249 (trabalhista e LOAS) estão neste seed.
- **Se a #249 for resolvida em develop antes do PR deste módulo,** e a resolução tocar o seed, a régua de `scripts/` avança para o commit novo. A fixture, o id do blob esperado e o arquivo de dados mudam juntos, no mesmo commit.
- **Se for resolvida depois,** a mudança vem na base Python, como qualquer correção pós-migração. O teste de 2.3 obriga a trocar a fixture junto, e assim a proveniência continua registrada.

## 3. Comportamento: pontos onde a tradução ingênua erra

### 3.1 `coletar_arvore_perguntas_verde`

1. **Ordem dos alvos (lido, `:159-163`):** violência doméstica primeiro (o único fluxo implementado com categoria do Verde), depois os planejados na ordem do `listar` (`ORDER BY id`).
2. **Pausa de 120 ms antes de cada chamada, inclusive a primeira (lido).** Timeout de 20 s por chamada, sem retentativa. O fetch é próprio, e não o `chamar_verde_com_retry` da integração.
3. **`limpar_flow` antes de varrer (lido, `:80`), sem transação.** Uma categoria que falha no meio fica gravada pela metade. Ver o achado B1 (#251).
4. **`ordem` é um contador único por flow, em pré-ordem (lido):** só cresce em pergunta, e não em assunto.
5. **Verdade do JS:**
   - `if (dados.assuntoEncontrado)`: a string `"false"` conta como verdadeira;
   - `if (!pergunta)`: a string vazia conta como ausente;
   - `respostas ?? []`: `null` vira lista vazia.
6. **`idAssunto === undefined` (lido, `:93`):** só a chave ausente dispara o erro. **`idAssunto: null` passa** e vira `GET /assunto/null`. A tradução testa a ausência da chave, e não `is None`.
7. **`nome: detalhe.nome ?? dados.nomeAssunto ?? ""`:** o `??` pula `null` e ausente, mas não a string vazia.
8. **`tipoDaPergunta` (lido, `:72-76`):** `trim()` e `toUpperCase()` do JS (usar `trim_js`). É `sim_nao` só com exatamente duas respostas, "SIM" e "NÃO". Nó sem respostas vira `texto`.
9. **Montagem da URL:** `idCategoria=${n}` com a conversão de número do JS. Um `resposta.id` não inteiro vindo do Verde (lido, nunca visto) sairia diferente com o `str()` do Python.
10. **`VERDE_API_URL ?? padrão`:** variável definida e vazia continua vazia, e não cai no padrão de homologação.
11. **Tolerância a falha:** cada categoria roda num `try`. A mensagem registrada é `err.message`. O processo sai com código 0 mesmo com falhas; só sai com 1 por erro fatal (variável faltando, falha ao listar planejados).
12. **Mensagens de erro reproduzidas texto a texto:**
    - `consultar-item-arvore HTTP <status> (<params JSON>)`;
    - `... sem 'dados' (...)`;
    - `GET /assunto/<id> HTTP <status>`;
    - `profundidade máxima (12) excedida em "<nome>" — ...`;
    - `assuntoEncontrado sem idAssunto em "<nome>"`;
    - `nó sem pergunta e sem assuntoEncontrado em "<nome>" (...)`.
    
    O `JSON.stringify(params)` sai sem espaços e só com a chave usada.
    - **O timeout sai como `The operation was aborted due to timeout`**, a mensagem do `AbortSignal.timeout` do Node (lido, a executar).
    - **JSON inválido na resposta do Verde:** a mensagem do V8 (`Unexpected token ...`) não é reproduzível. Proposta na D-4.
13. **Saída:** `console.log` e `console.error`, em texto puro, e não o logger pino. Mesmas linhas, nos mesmos canais (stdout e stderr). O resumo da categoria é `[<nome>] N pergunta(s), M assunto(s)`.

### 3.2 `seed_fluxos_planejados`

1. **`validar()` antes de conectar (lido, `:104-127`):** as mesmas checagens, na mesma ordem dentro de cada registro, com as mesmas mensagens. A contagem `!== 74` é checada só no fim. `descricao.trim()` usa o `trim_js`.
2. **`f.id in fluxosPorId`:** no JS, o `in` também acha propriedades herdadas (`"constructor"`, `"toString"`). Com 74 UUIDs fixos, isso não tem efeito. A tradução usa `in` do dicionário e registra a diferença.
3. **DDL, `ALTER` e 74 upserts, cada um no próprio autocommit, sem transação (lido).** Uma falha no meio deixa parte gravada; rodar de novo completa (`ON CONFLICT (id) DO UPDATE`).
4. **Os 4 registros com `palavrasChave: []` (executado, 2.1):** o `pg` do Node manda `{}`. O psycopg 3 manda a lista vazia sem tipo, e o Postgres infere o tipo pela coluna (lido na documentação do psycopg). **A conferir no CI com Postgres** (teste 4 da seção 6).
5. **`mensagemFixa ?? null`:** os 72 sem mensagem gravam `NULL`, e com isso **apagam uma mensagem que tenha sido posta à mão** (achado B2).
6. **Saída:** `seed concluído: 74 fluxos planejados inseridos/atualizados em fluxos_planejados`; erro fatal sai com `seed falhou:` e código 1.

## 4. O que não muda

- Tabelas, colunas e SQL;
- as mensagens de saída e de erro;
- os códigos de saída;
- a pausa, o timeout e o limite de profundidade;
- a ausência de modo mock no crawler;
- os 74 registros, byte a byte;
- `logs-prod.sh`, salvo a D-3 (ferramenta e checagens prévias).

## 5. Observabilidade

Os scripts não usam o logger, como em develop. Nenhuma saída traz dado pessoal: só nomes de categoria, contagens e ids do Verde.

## 6. Testes que provam

Develop não tem teste destes scripts. Todos os testes abaixo são novos.

1. **Extração (2.3):** o blob da fixture e as cinco comparações. Roda na suíte padrão.
2. **Crawler, com Verde falso (`httpx.MockTransport`) e as stores em memória.** A árvore de teste é inventada, e não uma árvore real do Verde. Casos:
   - pergunta sim/não;
   - pergunta com opções;
   - duas opções que não são sim/não;
   - nó `texto` sem respostas;
   - assunto compartilhado entre duas categorias (um upsert e duas ligações);
   - `ordem` em pré-ordem.
3. **Crawler, falhas.** Cada mensagem do item 12 de 3.1, e também:
   - profundidade 13;
   - `idAssunto: null` (chega em `GET /assunto/null`);
   - `assuntoEncontrado: "false"`;
   - categoria que falha no meio (as outras seguem; o código de saída é 0; a categoria fica parcial, achado B1).
   
   Também entram as variáveis faltando (código 1, nenhuma chamada ao Verde).
4. **Seed com Postgres (marcador `postgres`, só no CI):** rodar duas vezes e ler as 74 linhas de volta, iguais ao arquivo de dados. Os 4 registros vazios devem voltar com `palavras_chave = '{}'`, e os 72 sem mensagem, com `mensagem_fixa IS NULL`. O `listar_fluxos_planejados()` devolve os 74.
5. **`validar()`:** cada mensagem de erro, provocada com uma cópia alterada dos dados (o arquivo real não muda).

**Mutações a executar antes do PR:**

| Mutação | Teste |
|---|---|
| Uma palavra-chave a menos no JSON | 1 |
| Um acento em NFD no JSON | 1 |
| `mensagemFixa: null` no lugar da chave ausente | 1 |
| Dois registros trocados de lugar | 1 |
| Fixture com um byte a mais | 1 |
| `is None` no lugar de chave ausente em `idAssunto` | 3 |
| `ordem` contando assunto | 2 |
| `strip()` no lugar de `trim_js` | 2 |
| Exceção da categoria propagada (aborta o resto) | 3 |
| Código de saída 1 quando há falha de categoria | 3 |
| `ON CONFLICT DO NOTHING` | 4 |
| Contagem 74 checada antes dos registros | 5 |

## 7. Conferência contra develop

- **Crawler, por saída e por linhas gravadas.** O crawler de develop e o Python rodam contra o mesmo Verde falso, um servidor HTTP local com árvores inventadas, inclusive os casos de falha de 3.1. Compara-se:
  - o stdout e o stderr, linha a linha;
  - o código de saída;
  - as linhas que cada um grava, normalizadas sem os UUIDs.
  
  **Ajuste necessário no lado de develop:** o script exige `DATABASE_URL`, e esta máquina não tem Postgres. Para a conferência, roda uma cópia do script em `.sonda/`, no worktree, sem a guarda de `DATABASE_URL`, com as stores em memória e com uma linha final que despeja as linhas gravadas. **Essa é a única mudança na cópia,** e o diff dela fica registrado na seção 10.
- **Seed:** o SQL é comparado texto a texto, porque a gravação de develop não roda sem banco nesta máquina. O lado Python roda no CI (teste 4).
- **Cada item (lido) desta spec vira cenário,** como na spec 07.

## 8. Critérios de aceite

- [x] `scripts/dados/fluxos_planejados.json` extraído e verificado (2.3) em commit próprio, antes da tradução: 21 testes, e 6 de 6 mutações pegas (palavra-chave a menos, acento em NFD, `mensagemFixa: null`, registros trocados, espaço no fim, fixture com um byte a mais).
- [x] Os dois scripts traduzidos (`8daa072`, `db9a56f`); `scripts/` incluído no `mypy` (`files`) e no `ruff`.
- [x] Testes da seção 6 passando localmente. *Falta: o teste 4 (Postgres) e os do `logs-prod.sh`, que só rodam no CI.*
- [x] Conferência da seção 7: 64 cenários, 62 idênticos e 2 da D-4 (seção 10.2).
- [x] Mutações executadas: 6 de 6 na extração; 22 de 23 no seed e na coleta, e a restante é pega pelo teste com Postgres no CI (seção 10.2). *Falta: a lista no corpo do PR.*
- [x] `scripts/README.md` com os comandos novos, os pré-requisitos do `logs-prod.sh` (D-3) e os avisos da #251, da #253 (colisão com a #249) e da #255 (`f3e7b6c`).
- [x] `logs-prod.sh` com as checagens prévias da D-3, testadas com `PATH` sem `node`, sem `npx`, sem `aws` e com o download falhando (`f3e7b6c`). *Os testes rodam no CI; no Windows são pulados.*
- [x] `MIGRACAO.md` com a seção do módulo; o índice de issues e a #208 atualizados.
- [ ] `ruff`, `ruff format --check`, `mypy` strict e `pytest` verdes (localmente: sim, fora os 2 testes de `test_workflows.py`, que dependem do Git Bash, quebrado nesta máquina); os jobs `test` e `imagem` verdes. *Falta: o CI do PR.*

## 9. Decisões (aprovadas em 2026-10-19)

| Decisão | Proposta | O que mudaria |
|---|---|---|
| **D-1** Formato dos dados | JSON em `scripts/dados/`, fora do código, com a fixture do `.ts` de develop como fonte verificada (2.3) | Um módulo Python com o literal também funcionaria, mas o diff de uma mudança de dado ficaria misturado com código |
| **D-2** Como rodar | `uv run python scripts/seed_fluxos_planejados.py` e `uv run python scripts/coletar_arvore_perguntas_verde.py`, documentados no README. Sem `[project.scripts]`, porque `scripts/` não faz parte do pacote | Com entradas no `pyproject`, os scripts entrariam no pacote instalado e na imagem |
| **D-3** `logs-prod.sh` | Trocar `pino-pretty` por `npx --yes pino-pretty@13.1.3`. Em develop, o `pino-pretty` vinha do `node_modules` pelo `pnpm logs:prod`; na `migration` não há `node_modules`, e o script falha com "command not found" (lido). O formato do log Python é o envelope pino (conferido nos módulos anteriores), então o `pino-pretty` continua servindo. **Condição da aprovação:** o `npx --yes` exige Node e rede, e o script detecta a falta antes do laço e diz o que falta, em vez de falhar com "command not found". É ferramenta de diagnóstico, e falhar de forma obscura no meio de uma investigação é o pior momento. Ver 9.1 | Sem a troca, o script fica no repositório, mas não roda numa máquina limpa |
| **D-4** JSON inválido do Verde | Registrar a mensagem do Python, e não a do V8. A mensagem só aparece no console de quem roda o script | Reproduzir o texto do V8 pediria imitar o parser |

### 9.1 Checagens prévias do `logs-prod.sh` (D-3)

Antes do laço, nesta ordem, cada uma com uma mensagem própria em stderr e código de saída 1:
1. **`node` e `npx` no `PATH`** (`command -v`). Mensagem: o que falta e que o `pino-pretty` roda pelo `npx`.
2. **`pino-pretty` obtido pelo `npx`:** `npx --yes pino-pretty@13.1.3 --version` uma vez. Se falhar, a mensagem diz que o download falhou e que a primeira execução precisa de rede. Depois da primeira vez, o pacote fica no cache do `npx`.
3. **`aws` no `PATH`.** Hoje, sem o `aws`, o erro vai para o `2>/dev/null` do laço e o script fica em silêncio para sempre (lido). Ver o achado B3.

O laço em si não muda.

## 10. Achados

| Id | Achado | Origem | Proposta |
|---|---|---|---|
| **B1** | O crawler apaga a árvore do flow antes de varrer, sem transação, e sai com código 0 quando uma categoria falha. Uma falha na primeira chamada deixa a categoria sem árvore; uma falha no meio, com a árvore parcial. O resumo diz que a categoria "pode ser categoria sem árvore no Verde", misturando falha de infraestrutura com ausência esperada: o padrão da #196. O único leitor em atendimento lê só a raiz (`src/orquestrador/graph.ts:106-116`), e com o catálogo do #242 o efeito na conversa deve ser nenhum hoje (lido); volta se os planejados voltarem ao catálogo (#249, opções 1 e 3) | lido, `:80`, `:170-191` | **Issue #251** (`[BUG]`, aberta em 2026-10-19, sem esperar a execução). A tradução reproduz; a conferência executa os desfechos e comenta na #251 |
| **B2** | O seed grava `mensagem_fixa = NULL` nos 72 registros sem mensagem e sobrescreve `nome`, `descricao` e `palavras_chave`. Rodar o seed de novo num banco editado à mão desfaz as edições. O comentário de `:103` diz que a tabela "passa a ser editada por SQL". **Colide com a #249:** uma correção feita editando `mensagem_fixa` no banco some no próximo seed, e a #22 foi entregue justamente mudando só o seed (`6806952`) | lido, `:149-154` | Reproduzir. **Registrado na #249** (comentário de 2026-10-19, com critério de aceitação proposto) e no README. **Issue própria: #253** (`[TECH]`, seção 10.1) |
| **B4** | A palavra-chave `"sofri preconceito` (planejado "direitos e diversidade") começa com uma aspa solta, escrita como `\"` no literal: provável erro de digitação. As palavras-chave só entram no texto dado à IA e ao embedding (`src/shared/fluxosPlanejadosDb.ts:42-43`), e não há comparação exata | executado (leitor e extração), uso lido | Reproduzir; o teste `test_aspa_solta_de_develop_preservada` trava o valor. Efeito cosmético: sem issue |
| **B3** | `logs-prod.sh` manda o stderr do `aws logs tail` para `/dev/null`. Credencial expirada, perfil errado ou `aws` ausente não mostram nada: o script fica em silêncio, como se não houvesse log | lido, `logs-prod.sh:8` | A ausência do `aws` entra nas checagens da D-3. Mostrar o erro da credencial muda o laço e fica para decisão |

| **B5** | Importar os fluxos inicializa o checkpointer (top-level await nos grafos, o ponto 1 da #208): os scripts logam o aviso do MemorySaver, criam as tabelas de checkpoint no banco de destino e, com o banco inalcançável, morrem sem o próprio prefixo de erro, antes das guardas. A fundação Python já desfez o acoplamento | executado (seed e coleta de develop, 2026-10-19 e 2026-10-20); o `CREATE TABLE`, lido | **Issue #255.** Os scripts Python reproduzem com uma chamada explícita a `inicializar_checkpointer()`, fora do tratamento de erro do script |

**Achado lateral, sem relação com os scripts: a busca vetorial do orquestrador não roda em produção (#256).** Com o catálogo de 9 opções e `k` 10, `buscar_candidatos` devolve o catálogo inteiro sem calcular embedding (executado: 0 chamadas ao Bedrock nos dois lados). Encontrado na verificação da busca, feita sem melhoria.

### 10.2 Resultado (executado em 2026-10-19 e 2026-10-20)

**Conferência contra develop @ `1157a6d`: 64 cenários, 62 idênticos.** Os dois crawlers rodam como processo, contra o mesmo Verde falso por HTTP (`tests/fixtures/scripts/conferencia-coleta/`). Develop roda pela cópia sonda, cujo diff é impresso por `gerar_sonda.py`. A comparação cobre o stdout (o log pino sem `time`, `pid` e `hostname`), o stderr (num erro fatal, só a primeira linha), o código de saída, as chamadas ao Verde na ordem e o que foi gravado (chave ausente e `null` contam igual, como no Postgres). Os 2 restantes são o texto do erro do parser de JSON, a divergência aceita na D-4:

| Cenário | develop | Python |
|---|---|---|
| JSON inválido | `Expected property name or '}' in JSON at position 1 (line 1 column 2)` | `Expecting property name enclosed in double quotes: line 1 column 2 (char 1)` |
| Corpo vazio com 200 | `Unexpected end of JSON input` | `Expecting value: line 1 column 1 (char 0)` |

A primeira rodada parou no 32º cenário: o sistema passou a recusar a criação de processos (e o Git Bash da máquina perdeu o `usr\bin\bash.exe`). A segunda rodou os 33 restantes com pausa entre eles e gravação a cada cenário.

**Mutações:**
- **extração dos 74 registros:** 6 de 6 (`83c8437`);
- **seed e coleta:** 23 mutações. A 1ª rodada pegou 19. As 4 que passaram:
  - `assuntoEncontrado` e `pergunta` com o `bool()` do Python: faltava o caso. `[]` e `{}` são verdadeiros no JS e falsos no Python; `"false"` e `0` coincidem por acaso. Testes novos (`bb5e3a6`);
  - profundidade `>=` no lugar de `>`: o teste só conferia a mensagem, que é a mesma nos dois casos (usa a constante 12). Faltava a fronteira exata, a profundidade 12 passando. Teste novo (`bb5e3a6`);
  - `ON CONFLICT DO NOTHING` no seed: legítima. Só o teste com Postgres (`test_seed_desfaz_edicao_manual_da_mensagem_fixa`) pega, e ele roda no CI.
  
  **Depois dos testes novos: 22 de 23 nos testes de unidade, e a 23ª pega pelo teste com Postgres no CI.**

### 10.1 B2: vale issue própria?

**Avaliação: sim, como `[TECH]`.** O problema não é só da #249. O seed e a tabela são duas fontes do mesmo dado, sem regra de qual vale:
- toda edição por SQL (palavras-chave, descrição, mensagem) some no próximo seed e não existe na cópia de recuperação;
- toda mudança feita só no seed precisa de um seed novo para chegar ao banco, e esse seed desfaz as edições por SQL.

A decisão que a issue pede: qual é a fonte (o arquivo ou o banco) e como uma mudança chega à outra. **Aberta como #253 em 2026-10-19**, por decisão do usuário: a #249 provavelmente será resolvida editando `mensagem_fixa` no banco, e quem fizer isso perde a correção no próximo seed sem entender por quê.

## Dependências

- `migration` com o api (#246) mergeado. O módulo não depende do api, mas a branch sai da `migration` mais recente.
- develop @ `1157a6d`, com o worktree em `%TEMP%\m1157a6d` para a extração e a conferência.
- Issues afetadas: #20, #26 (origem dos scripts), #249 (mensagens fixas do seed; colisão do B2), #251 (B1) e #253 (B2).
