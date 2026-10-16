# SDD — Módulo `fluxos`

Parte de #208. Branch: `refactor/<issue>-fluxos-python`, criada a partir de `migration` @ `80de7bb` (depois do subgrafos). **Fonte de comportamento: develop @ `0aecd98`**, e não mais `4e695f2`, porque develop andou (seção 0.3). **As linhas citadas (`arquivo:linha`) são de `0aecd98`**, convertidas por alinhamento de linhas a partir do inventário feito em `4e695f2`.

| Origem (develop) | Destino (migration) |
|---|---|
| `src/fluxos/index.ts` (114 linhas) | `src/maria/fluxos/__init__.py` (catálogo, `buscar_fluxo`, `catalogo_para_classificacao`, IDs) |
| `src/fluxos/padrao/{graph,state,api}.ts` (80) | `src/maria/fluxos/padrao/` |
| `src/fluxos/pessoaPresa/{graph,state,api}.ts` (805) | `src/maria/fluxos/pessoa_presa/` |
| `src/fluxos/violenciaDomestica/{graph,state,api}.ts` (726) | `src/maria/fluxos/violencia_domestica/` |
| 84 testes (`graph.test.ts` e `http.test.ts` dos três) | `tests/fluxos/` (os `http.test.ts` ficam para o módulo `api`, que tem as rotas) |

**Fora deste módulo:** as rotas (`rotas/atendimentos.ts`, `rotas/orquestrador.ts`), inclusive a confirmação de TTL e o filtro de `dadosConhecidos`, que ficam no módulo `api`. O grafo do orquestrador fica no módulo `orquestrador`.

---

## 0. O que mudou desde o subgrafos

### 0.1 Correções em código já mergeado (primeiros commits da branch)

1. **`cadastro_pessoa`, `idPessoa: null` (aprovada).** O Python converte `None` em chave ausente dentro de `dadosPessoa`. Develop mantém `null` quando o Verde responde sucesso com `"idPessoa": null`, porque o guarda é `=== undefined`. A correção mantém o valor do Verde como veio. O commit diz que corrige código mergeado (`80de7bb`).
2. **`identificar_assistido`, bypass do CPF (aprovada).** O Python testa `state.get("cpf") is not None`; develop testa `state.cpf !== undefined`. Develop nunca grava `undefined` em `cpf`, então a ausência da chave é o `undefined`. Com `dadosConhecidos.cpf: null` vindo da Tykhe, develop **pula** a pergunta e consulta `""`, e o Python **pergunta**. A correção passa a testar a presença da chave.
3. **Correção do #226 (persistencia):** `resolver_confirmacao_ttl_continuar` passa a devolver a resposta guardada, com o SQL e o teste do #226 (decisão já registrada na #208).

### 0.2 Regra de estado: `undefined` × `null`, caso a caso (aprovada)

**Critério:** num canal que **nunca foi escrito**, a chave não aparece no estado Python. Num canal escrito com `None`, ela aparece. *(Verificado em 2026-10-14 no LangGraph 1.2.14, no pai e no subgrafo embutido: sem o canal, `"cpf" in state` é `False`; com `{"cpf": None}`, é `True`.)* Então:
- **o canal não recebe `undefined` em develop:** chave ausente = `undefined`, e `None` = `null`. Os dois são distinguíveis, e os guardas usam a **presença da chave**;
- **o canal recebe `undefined` em develop e o `null` não entra:** `None` = `undefined`, e os guardas usam `is not None`;
- **o canal recebe `undefined` e o `null` também entra:** **conflito**. A tabela decide, com o motivo e o que mudaria.

O `null` só entra por três portas: **Tykhe** (`dadosConhecidos`, qualquer canal, #240), **Verde** (respostas) e **modelo** (extração, #212).

| Canal | develop grava `undefined`? | O `null` entra? | Tradução | Por quê / o que mudaria |
|---|---|---|---|---|
| `cpf` | não | sim (Tykhe) | guarda por **presença da chave** | Distinguível. Item 0.1.2 |
| `rg` | **sim** (`prepararPerguntaRgInvalido`, `pessoaPresa/graph.ts:206`) | sim (Tykhe; extração com `null` é omitida, `:94-97`) | `None` = `undefined`; guarda `is not None` | **Conflito, divergência aceita (decisão 1).** Com `dadosConhecidos.rg: null`, develop pula a primeira pergunta, valida `rg ?? ""`, que falha no formato, e pergunta "O RG deve conter apenas números. Qual o RG da pessoa presa? …". O Python faz a pergunta normal, "Qual o RG da pessoa presa? …". Aceito porque só acontece se a Tykhe mandar `rg: null`; a #240 vai restringir os campos. **Se a Tykhe passar a mandar `null`**, muda só o texto da primeira pergunta do RG; o resto do atendimento é igual. *(Corrigido na tradução, seção 8: a versão anterior dizia que develop consultava `""` no Verde, o que não acontece.)* |
| `temProcesso`, `numeroProcesso`, `parentesco` | não (gravados só por resposta, extração ou classificação) | sim (Tykhe; extração mantém `null`, `:94-97` só omite `undefined`) | guarda por **presença da chave** | Distinguível. Com `temProcesso: null`, develop pula a pergunta e chega a `origem_processo_nao_suportada` (inventário, achado 6). Reproduzido e testado |
| `encaminhamentoId` | **sim** (sucesso sem `dados.id`, `violenciaDomestica/graph.ts:297-298`) | sim, se o Verde mandar `"id": null` | `None` = `undefined`; `encaminhamentoId is not None` | **Conflito, divergência aceita (decisão 1).** Com `"id": null`, develop conclui com "Protocolo: null." e o Python vai para `falha_encaminhamento`. Aceito porque a Swagger declara `id` inteiro e não há registro de `null`. **Se o Verde passar a mandar `id: null`**, o desfecho vira falha em vez de concluído. Defeito vizinho: #238 |
| `perguntaAtualTexto`, `perguntaAtualTokensTotal` | sim (`prepararPergunta`) | não (só o `reescrever` escreve; a Tykhe poderia, pela #240, mas o canal é reescrito a cada pergunta) | `None` = `undefined` | Já é assim no ia. Se a Tykhe pré-preencher, o valor some na primeira pergunta, igual a develop |
| `dadosPessoa.idPessoa` (aninhado) | não | sim (Verde) | mantém `None` como `null` | Item 0.1.1 |
| `dadosPessoa.enderecoDetalhado.{idUf,idBairro,idMunicipio}` (aninhado, `consultarCep`) | sim (`dadosCep` sem o id) | não (o Python de `consultar_cep` usa AUSENTE, `verde.py:387-389`) | chave **removida** do objeto | Develop sobrescreve com `undefined` uma chave que já existia, e o JSON e o checkpoint apagam. Não basta deixar de escrever |
| `idLocalAtendimento` (argumento do encaminhamento) | sim (`orgao?.enderecos?.[0]?.idLocalAtendimento`) | sim (Verde) | **omitir** quando ausente, **`None`** quando `null` | O Python `DadosEncaminhamento` usa `in` (`verde.py:572`). Distinguível no ponto de leitura |
| `mensagemFinal`, `motivoHandoff` | não (terminais que não gravam deixam a chave ausente) | sim (Tykhe) | **presença da chave** na rota | A rota usa `values.mensagemFinal ?? padrão`. Com `null` da Tykhe, cai no padrão nos dois. Sem divergência |
| `cadastroErro` *(linha acrescentada na tradução, seção 8)* | não (só a mensagem do erro, `erro ?? "erro desconhecido"`) | sim (Tykhe) | guarda por **presença da chave**, no fluxo e no subgrafo `cadastro_pessoa` | Distinguível. Com `cadastroErro: null`, develop cadastra no Verde e vai para `falha_cadastro` **sem** perguntar a confirmação. O subgrafo mergeado testava `is not None` e fazia a pergunta a mais: corrigido em `65a976a` |

### 0.3 Develop andou: `4e695f2` → `0aecd98`

| PR | Em `src/fluxos` | Para este módulo |
|---|---|---|
| #234 | `respostaEhSim` local substituída por `shared/respostaSimNao.ts`, com o mesmo conjunto | Importar `resposta_eh_sim` de `shared/respostas.py`. O comentário removido documentava que a Tykhe às vezes repassa "Sim"/"Não" (achado ao vivo de 2026-08-31) |
| #226, #229 | nada | — |

### 0.4 O que o subgrafos já entrega e os fluxos usam

O inventário conferiu contra o Python, e tudo bate:
- `dadosPessoa.encontrado` e `falhaInfra`;
- `confirmaAssistido` só com `viaOrquestrador`;
- `cadastroErro` em falha;
- `dadosPessoa` sem `enderecoDetalhado` depois do cadastro (#231);
- `endereco` que não volta ao pai;
- a soma de tokens (#230).

## 1. Contexto

Três grafos, compilados com o checkpointer da fundação:
- **`padrao`:** um nó só, para fluxo planejado sem implementação. Conclui com a `mensagemFixa` do planejado ou a mensagem genérica.
- **`pessoaPresa`:** 27 canais.
  - Perguntas: extração livre (com `EXTRACAO_LIVRE_IA`), processo, número, RG (até 3 tentativas), confirmação do nome da pessoa presa e parentesco (classificado por IA).
  - Com `viaOrquestrador`: `identificarAssistido` e `cadastroPessoa`.
  - Desfechos: concluído, ou handoff com 8 motivos.
- **`violenciaDomestica`:** 30 canais.
  - Perguntas: é vítima, processo (até 3 tentativas), RO.
  - Sempre passa por `identificarAssistido` e, com `viaOrquestrador`, por `cadastroPessoa`.
  - Depois: CEP, plantão, órgãos e **encaminhamento real no Verde**.
  - Desfechos: concluído (urgente ou padrão), ou handoff com 7 motivos.

A topologia completa (nós, arestas, funções de roteamento e retornos), os textos das perguntas, os nós terminais e as mensagens estão no inventário de develop (anexo da issue). A tradução os reproduz **byte a byte**, e o teste 1 compara a topologia.

## 2. Contrato

- **Nomes:** os de develop para nós, canais (camelCase) e motivos de handoff. Os canais são compartilhados com os subgrafos por nome.
- **`FluxoConfig`:** `nome`, `descricao`, `grafo`, `extrair_metadados`, `mensagem_concluido`, `mensagem_handoff` e o opcional `id_categoria_assunto_verde`.
  - `metadadosSchema` **não é traduzido**: não tem nenhum consumidor em develop, e a rota declara `metadados` genérico.
  - A decisão fica registrada no `MIGRACAO.md`.
- **`extrair_metadados`:** devolve as chaves **na ordem de develop**, porque a comparação de contrato do `api` compara bytes.
  - O `undefined` de topo some; o `null` fica.
  - Recortes de pessoa presa: `dadosProcesso` vira `{id, origem}` e `dadosApenado` vira `{idSeap, idPessoa, nome, situacao, tipoPreso, regime}`.
  - `dadosPessoa` vai inteiro (#237).
- **IDs fixos:** `3df874f2-…` (pessoa presa) e `cabb2495-…` (violência doméstica). `id_categoria_assunto_verde = 10113` em violência doméstica.

## 3. Comportamento: pontos onde a tradução ingênua erra

### 3.1 Texto

| Ponto | develop | Python |
|---|---|---|
| RG (`pessoaPresa/graph.ts:188-192`) | `z.string().trim().regex(/^\d+$/)`; o `trim` vale só para validar, e o `rg` é gravado com espaços | `trim_js` e `[0-9]+`, sem `\d`. Grava o valor cru. Rejeita valor que não é string |
| Retry do RG | **qualquer** resposta só com dígitos (inclusive "1") vira RG digitado direto (`:248-250`) | idem |
| Processo, violência doméstica (`violenciaDomestica/graph.ts:24-26`) | `replace(/\D/g,"").length === 20` | `[^0-9]`. Grava cru |
| Processo, pessoa presa | sem validação; "tem processo?" não aceita o número direto | idem |
| `normalizarSituacao` (`pessoaPresa/graph.ts:39-45`) | `toUpperCase`, `split("/")`, `trim`, `replace(/^EM\s+/,"")` | **`\s` do JS é Unicode** (inclui U+FEFF e U+00A0, não inclui `\x1c` a `\x1f`): classe explícita com o conjunto de `_ESPACOS_JS`, mais `trim_js` |
| `tipoPreso`, `regime`, origem | `toUpperCase() ===`; origem `=== "SEEU"` sensível a caixa | `upper()`; conferir caso a caso os valores do mock |
| Protocolo (`violenciaDomestica/graph.ts:321`) | `` `Protocolo: ${encaminhamentoId}.` `` com guarda `!== undefined` | `texto_template` |

### 3.2 Exceções reproduzidas

- **`concluir` de pessoa presa com `situacao`, `tipoPreso` ou `regime` `null` vindo do Verde:** `null.toUpperCase()` lança `TypeError` e a rota responde 500. O Python **lança também**. Teste e registro no `MIGRACAO.md`.

### 3.3 Guardas de ambiente

- `classificarParentesco`: em develop, `NODE_ENV === "test"` devolve `MOCK_CLASSIFICACAO_PARENTESCO ?? "Outro"`. No Python, `APP_ENV == "test"`, com o `??` reproduzido (`""` passa como `""`).
- `EXTRACAO_LIVRE_IA === "true"` decide a rota inicial de pessoa presa e é lido a cada chamada.

### 3.4 Defeitos reproduzidos, com issue

| Issue | Onde |
|---|---|
| #236 (LGPD) | `pedirConfirmaNome` com o RG; a confirmação do CPF (subgrafo); a mensagem final com o município em violência doméstica |
| #238 | sucesso sem `dados.id` vira `falha_encaminhamento` |
| #239 | falha de infra na consulta de órgãos vira "ligue 129"; na de plantão, vira "sem plantão" |
| #240 | qualquer canal pré-preenchível (a rota fica no `api`; aqui, os testes de desfecho) |
| #212 | parentesco não validado; lista diferente da do SIPEN |
| #230, #231, #232, #237 | herdados dos subgrafos e do Verde |

## 4. O que não muda

Textos das perguntas e das mensagens, nomes de nó, canal e motivo, ordem das perguntas, bypasses, limites de tentativas, o que vai ao Verde, a ordem das chaves dos metadados e a soma de tokens.

## 5. Observabilidade

Nenhum log dentro de `src/fluxos`. A tradução não acrescenta nenhum.

## 6. Testes que provam

**Traduzidos:** os 74 de `graph.test.ts` (padrão 3, pessoa presa 40, violência doméstica 31), com o Verde em mock e o checkpointer em memória. Os 10 de `http.test.ts` passam por rota e ficam no `api`.

**Novos:**
1. Topologia dos três grafos igual à de develop (lista literal).
2. Interrupts: payload de cada pergunta; `opcoes` só nos `sim_nao`.
3. Tabela da seção 0.2, um teste por linha. Nos conflitos, o teste fixa o comportamento escolhido e cita o motivo.
4. `extrair_metadados`: chaves e ordem iguais às de develop, comparadas byte a byte com as fixtures de contrato existentes (`violencia-domestica-handoff-nao-vitima-200`, `pessoa-presa-get-metadados-parciais-200`).
5. `TypeError` em `concluir` com `null` do Verde (3.2).
6. Texto (3.1):
   - RG com dígitos de outros alfabetos e com espaços;
   - "1" no retry vira RG;
   - processo com 20 dígitos pontuados;
   - `normalizarSituacao` com U+FEFF e `\x1c`.
7. **Lacuna herdada do subgrafos:** Verde devolvendo a pessoa encontrada **sem `nome`**, nos dois fluxos, pelo orquestrador, com "Sim" e com "Não". O resultado é conferido contra develop no mesmo cenário.
8. Tokens: semente do orquestrador e deltas próprios; 6× em violência doméstica com cadastro (#230).
9. **Conferência diferencial contra develop @ `0aecd98`:** os desfechos (`statusFinal`, `motivoHandoff`, `mensagemFinal`, metadados) dos caminhos principais dos dois fluxos, executados em develop e em Python.

**Mutações a executar antes do PR:**

| Mutação | Teste |
|---|---|
| `\d` ou `\D` no RG e no processo | 6 |
| `\s` do Python em `normalizarSituacao` | 6 |
| Guarda por `is not None` onde é por presença (`cpf`, `temProcesso`) | 3 |
| Guarda por presença onde é por `is not None` (`rg`, `encaminhamentoId`) | 3 |
| Chave `idUf` deixada (e não removida) no `consultarCep` | 3 |
| `str.upper()` sem lançar com `None` | 5 |
| Ordem das chaves dos metadados alterada | 4 |
| `respostaEhSim` local com `strip()` | 3 do subgrafos |

## 7. Critérios de aceite

- [x] Correções da seção 0.1 em commits próprios, antes da tradução, dizendo que corrigem código mergeado (`d5e5965`, `2403bab`; mais `65a976a` e `55eee00`, da seção 8).
- [x] 74 testes traduzidos e os novos da seção 6 passando sem rede (74 + 74, `c5c18e9`).
- [x] Tabela da seção 0.2 com um teste por linha.
- [ ] Mutações executadas (27, todas pegas, seção 8), com o resultado no PR. *Falta: o PR.*
- [ ] Conferência diferencial contra develop @ `0aecd98` (584 cenários, seção 8) registrada no PR. *Falta: o PR.*
- [x] `MIGRACAO.md` com o texto pendente (`migracao-specs/pendente-migracao-md-fluxos.md`) e a seção do módulo.
- [ ] `ruff`, `ruff format --check`, `mypy` strict e `pytest` verdes (localmente: 398 passando); jobs `test` e `imagem` verdes. *Falta: o CI do PR, que também roda pela primeira vez os testes `postgres` do #226.*

## 8. Achados da tradução (2026-10-14)

Tradução em `6713498` (código e os 74 testes de develop) e `c5c18e9` (os 74 testes novos da seção 6). Suíte local: 398 passando.

### 8.1 Conferência diferencial contra develop @ `0aecd98`

Os mesmos cenários foram executados em develop (TypeScript, `node --import tsx`) e no Python, comparando byte a byte:
- as perguntas (payload de cada interrupt);
- os metadados;
- os corpos e as URLs enviados ao Verde;
- a exceção, quando há.

O estado final também foi comparado, como objeto. Os cenários rodam em dois modos:
- **mock:** o Verde do próprio código, sem token;
- **http:** um Verde falso local, para os casos que o mock não cobre, como pessoa sem nome, `null` nos campos do apenado, CEP sem id, `id: null` no encaminhamento e plantão com id `null`.

| Bloco | Cenários | Iguais | Divergência aceita | Diferentes |
|---|---|---|---|---|
| Caminhos principais, tabela 0.2, texto, exceções, tokens, lacuna do "Verde sem nome" | 89 | 87 | 2 (`rg: null`, `id: null`) | 0 |
| Varredura: cada canal dos dois fluxos pré-preenchido pela Tykhe com `null`, `"x"`, `0`, `7`, `true`, `false`, `{}`, `[]` e `""` (#240) | 495 | 482 | 1 (`rg: null`) | 12 (8.3, D-1) |

A varredura achou dois defeitos de tradução, já corrigidos, e uma divergência, aceita em 2026-10-16 (8.3). Ela entrou no `MIGRACAO.md` como técnica a repetir no orquestrador e no api.

### 8.2 Corrigido durante a tradução

1. **`cadastroErro: null` da Tykhe (`65a976a`, corrige código mergeado em `80de7bb`).** Develop testa `!== undefined` num canal que nunca recebe `undefined`. Com `null`, cadastra a pessoa no Verde e vai para `falha_cadastro` **sem** perguntar a confirmação. O subgrafo `cadastro_pessoa` testava `is not None` e fazia a pergunta a mais. Passou a testar a presença da chave, e a linha entrou na tabela 0.2.
2. **`texto_template` de objeto e lista (`55eee00`).** `${obj}` de JS dá `[object Object]`, e `${lista}` dá `join(",")`. O Python usava `str()`. Aparecia na mensagem de `falha_cadastro` com `cadastroErro` objeto ou lista.
3. **Registro errado da divergência do `rg`** (tabela 0.2 e decisão 1, corrigidas aqui, no `MIGRACAO.md` e na #208). A versão anterior dizia que develop "pula a pergunta e consulta `""`". Na verdade, develop pula a primeira pergunta, `""` falha no formato do RG e ele pergunta "O RG deve conter apenas números…". O Python faz a pergunta normal. A diferença é só o texto da primeira pergunta do RG. É o terceiro caso de afirmação sobre desfecho inferida do código e não confirmada na execução, junto com o "conta como não" da #217 e a gravidade da #232 (`MIGRACAO.md`, "Padrão: afirmação sobre desfecho inferida do código, sem execução").

### 8.3 Decidido em 2026-10-16: divergência aceita

**D-1. Contador com valor que não é número, vindo da Tykhe** (`tentativasCpf`, `tentativasRg`, `tentativasProcesso`).

- **develop:** `(t ?? 0) + 1` concatena texto. `"x"` vira `"x1"`, e a pergunta sai "tentativa x1 de 3". `"x1" >= 3` é falso, então o retry continua, com contagem sem sentido. Com `""`, vira `"1"`, depois `"11"`, e esgota na segunda tentativa.
- **Python:** `TypeError` no `+ 1`. A rota responde 500.
- **Alcance:** só acontece se a Tykhe mandar texto, objeto ou lista num contador interno. A #240 vai restringir os campos aceitos. `null`, número e booleano dão o mesmo resultado nos dois.
- **Opções:**
  - (a) aceitar como divergência registrada;
  - (b) reproduzir o `+` e o `>=` do JS nos três contadores, o que inclui o `identificar_assistido` mergeado.
- **Decisão: (a), aceita como divergência registrada** (tabela "Divergências aceitas" do `MIGRACAO.md`). **O Python falha mais cedo e mais alto que develop:** 500 na hora, onde develop seguiria o atendimento com a contagem sem sentido. Um 500 vindo da Tykhe com `TypeError` num `tentativas*` é este caso. Motivos:
  - concatenar texto num contador é acidente de tipagem fraca, não comportamento desenhado;
  - o caminho exige que a Tykhe viole o próprio contrato num campo numérico, e ela é cliente autenticado, não entrada de cidadão;
  - a falha visível é melhor na prática que o atendimento seguir com contagem sem sentido.
- Reproduzir o `+` e o `>=` em três lugares, incluindo código mergeado, espalharia coerção frouxa pelo Python para preservar algo que ninguém desenhou. A #240 elimina o caso na origem.

### 8.4 Verificação por mutação

27 mutações, todas pegas. Três passaram na primeira rodada. Examinada cada uma, as três eram lacunas reais de teste, e não mutações mal escritas:
- `strip()` em `normalizarSituacao`: nenhum caso tinha BOM ou `\x1c` na ponta de uma parte;
- bypass do **preparar** por `is not None`: em `APP_ENV=test` o efeito não aparece no fluxo; com IA ligada, gastaria uma chamada ao Bedrock;
- `rg` `None` nos metadados como `null`: o teste conferia o estado, e não os metadados.

As três ganharam teste e passaram a ser pegas. A lista completa, com o teste que pega cada uma, vai no PR.

### 8.5 Confirmado

- **Lacuna herdada do subgrafos, fechada:** com o Verde devolvendo a pessoa sem nome, os dois fluxos, pelo orquestrador, perguntam "Confirma que seus dados são: você?". Com "Sim", concluem; com "Não", vão para `assistido_nao_confirmado`. É igual a develop (#236).
- **Tokens (#230):** a semente de 150 vira 300 com identificação e 900 com cadastro, nos dois fluxos. O padrão repassa 150. É igual a develop.
- **`TypeError`** de `null.toUpperCase()` com a mesma mensagem, e o curto-circuito do `&&`, que não lança quando a situação já está fora da lista.
- **`"123\n"` é RG válido** nos dois lados: o `trim` do zod remove a quebra antes da regex. A spec (3.1) só citava o `$`.
- **`fluxosPorId[id]`** com chave do protótipo (`"constructor"`) não é alcançável: a rota valida `flowId` com `format: "uuid"`.

## Decisões (fechadas em 2026-10-14)

1. **`rg` e `encaminhamentoId`: divergências aceitas e registradas** (tabela 0.2). O motivo técnico é o **colapso de `undefined` e `null` em `None` num canal que recebe escrita externa**: develop grava `undefined` nesses canais e o `null` pode entrar de fora, então o Python não tem como distinguir os dois.
   - **`rg`:** se a Tykhe passar a mandar `rg: null`, a primeira pergunta do RG sai com o texto normal, e não com "O RG deve conter apenas números…". *(Corrigido na tradução: a versão anterior dizia "em vez de consultar `""`"; a conferência diferencial mostrou que develop não consulta o Verde nesse caso.)*
   - **`encaminhamentoId`:** se o Verde passar a mandar `id: null`, o desfecho vira `falha_encaminhamento` em vez de concluir com "Protocolo: null.". **Isso evita mostrar um protocolo inválido à pessoa atendida**, o mesmo problema da #238.
2. **Bypass do `cpf: null` no `identificar_assistido`: corrigido**, com o mesmo tratamento do `idPessoa` no `cadastro_pessoa`: guarda pela presença da chave e testes com o `null` da Tykhe. Commit próprio, que corrige código mergeado.
3. **`metadadosSchema`: não traduzido.** Não tem consumidor em develop @ `0aecd98` (busca fora de `src/fluxos` vazia), e a rota declara `metadados` genérico (`rotas/atendimentos.ts`). Carregar código morto para o Python não faz sentido. A omissão fica registrada aqui e no `MIGRACAO.md`.
4. **D-1, contador com texto vindo da Tykhe: divergência aceita (2026-10-16).** Ver 8.3. O Python falha mais cedo e mais alto (500), onde develop concatena e segue.

**Diagramas da issue:** Mermaid em texto (caminho A), com o guia de estilo do `diagram-specialist`. Para issues da migração que mudam durante a tradução, o caminho A fica aceito; o PNG no S3 (caminho B) fica para a documentação estável em `docs/`.

## Dependências

- `migration` @ `80de7bb`: subgrafos, ia, integracoes e `shared/`.
- Develop @ `0aecd98`.
- Issues afetadas: #212, #230, #231, #232, #236, #237, #238, #239, #240.
