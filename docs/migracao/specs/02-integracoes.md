# SDD — Módulo `integracoes`

Parte de #208. Branch: `refactor/219-integracoes-python`, criada a partir de `migration` depois de `persistencia`. Fonte de comportamento: `develop` @ `4e695f2`.

| Origem (develop) | Destino (migration) |
|---|---|
| `src/integracoes/verde.ts` | `src/maria/integracoes/verde.py` |
| `src/integracoes/whatsapp.ts` | `src/maria/integracoes/whatsapp.py` |
| `src/integracoes/verde.test.ts` | `tests/integracoes/test_verde.py` |

**Fora deste módulo:** a ponte do WhatsApp (`src/rotas/webhookWhatsapp.ts`) é uma rota. Ela depende do app (chamada interna às rotas protegidas) e do grafo do orquestrador, por isso migra no módulo `api`. A seção 3.5 fixa o que este módulo entrega à ponte e os requisitos de estado que o `api` herda.

---

## 1. Contexto

- **`verde`**: cliente HTTP do Verde, o sistema da Defensoria. Tem 8 operações: apenado por RG, processo, pessoa por CPF, CEP, órgãos de violência doméstica (normal e de plantão), plantão vigente, encaminhamento e cadastro de pessoa. Tem retry automático para falha de infra (issue #172) e um **modo mock** quando `VERDE_JWT_TOKEN` está vazio, que é o modo usado por todos os testes.
- **`whatsapp`**: envio de mensagem pela Graph API da Meta e extração de mensagem ou status de entrega do payload do webhook (issue #198). Também tem modo mock, quando falta token ou `phone_number_id`.

## 2. Contrato

### `verde`

```python
TENTATIVAS_RETRY_VERDE = 3
async def chamar_verde_com_retry(chamada: str, montar_requisicao: Callable[[], Awaitable[httpx.Response]]) -> ResultadoChamadaVerde
async def consultar_apenado_por_rg(rg: str) -> DadosApenado
async def consultar_processo(numero: str) -> DadosProcesso
async def consultar_pessoa_por_cpf(cpf: str) -> DadosPessoa
async def consultar_cep(cep: str) -> DadosCep
async def consultar_orgaos_violencia_domestica(indicacao_ro: bool, id_pessoa: int) -> OrgaosViolenciaDomestica
async def consultar_plantao_vigente() -> list[Plantao]
async def consultar_orgaos_plantao_violencia_domestica(id_plantao: list[int], id_assistido: int) -> OrgaosViolenciaDomestica
async def criar_encaminhamento_violencia_domestica(dados: DadosEncaminhamento) -> ResultadoEncaminhamento
async def cadastrar_pessoa(dados: DadosCadastroPessoa) -> ResultadoCadastroPessoa
```

- `ResultadoChamadaVerde`: `{ok: True, res}` ou `{ok: False, res?: Response, falhaInfra: bool}`.
- Os tipos de retorno estão em `shared/types.py` (fundação). Os campos ficam em camelCase, porque vão para o estado do grafo e para `metadados` na resposta à Tykhe.
- **Campos que admitem `null` já tipados na fundação** (PR #213, commit `eb62fdf`): `int | None` em `DadosApenado.idPessoa`, `DadosProcesso.id`, `DadosPessoa.idPessoa`, `Plantao.id`, `ResultadoEncaminhamento.id` e `ResultadoCadastroPessoa.idPessoa`, como a tabela 3.3 exige. Este módulo não altera `shared/types.py`.

### `whatsapp`

```python
async def enviar_mensagem_whatsapp(para: str, texto: str, chat_id: str) -> None   # nunca lança exceção
def extrair_mensagem_whatsapp(payload: object) -> MensagemRecebidaWhatsapp | None  # {de, texto}
def extrair_status_whatsapp(payload: object) -> StatusEntregaWhatsapp | None       # {status, erroCodigo?, erroTitulo?}
```

### Requisições ao Verde

As requisições precisam ser idênticas nos bytes que importam: método, URL, `content-type`, `accept`, `authorization`, `x-client-id` e corpo.

| Operação | Método e URL (base `VERDE_API_URL`) | Corpo |
|---|---|---|
| apenado | `POST /apenado` | `{"rg": rg}` |
| processo | `GET /processo/consultar/{encodeURIComponent(numero)}` | — |
| pessoa | `GET /pessoa?cpf={encodeURIComponent(cpf)}` | — |
| cep | `GET /cep/{encodeURIComponent(cep)}` | — |
| órgãos VD | `GET /orgao/violencia-domestica?indicacaoRO={true\|false}&idPessoa={n}` | — |
| plantão vigente | `GET /plantao/vigente` | — |
| órgãos plantão | `GET /orgao/plantao/violencia-domestica?idPlantao={a}&idPlantao={b}&idAssistido={n}` | — |
| encaminhamento | `POST /encaminhamento/encaminhar` | `idPessoa, idOrgao, [idLocalAtendimento], urgencia, preferenciaAtendimento:"Remoto", fluxoEncaminhamento:"VIOLENCIA_DOMESTICA", [motivoUrgencia]`, nessa ordem de chaves |
| cadastro | `POST /pessoa` | `nome, cpf, dtNascimento, [endereco]`, nessa ordem |

Cabeçalhos: `authorization: Bearer {VERDE_JWT_TOKEN}` e `x-client-id: {VERDE_CLIENT_ID}` em todas. `content-type: application/json` nos POST. `accept: application/json` em todas, salvo o `POST /apenado`, que **não** envia `accept` (`verde.ts:154-158`).

## 3. Comportamento

### 3.1 As quatro divergências de `fetch` × `httpx`, nos pontos onde aparecem

Cada divergência está registrada no ponto do `verde.ts` (`develop` @ `4e695f2`) onde ela ocorre, com a origem do valor envolvido e o efeito concreto no fluxo se a tradução for ingênua.

#### 3.1.1 Redirect

- **Onde:** nas 9 chamadas `fetch` do arquivo. Nenhuma passa a opção `redirect`, então todas usam o padrão `"follow"`.

  | Linha | Chamada | Método |
  |---|---|---|
  | `:152` | `/apenado` | POST |
  | `:218` | `/processo/consultar/…` | GET |
  | `:291` | `/pessoa?cpf=` | GET |
  | `:372` | `/cep/…` | GET |
  | `:460` | `/orgao/violencia-domestica` | GET |
  | `:504` | `/plantao/vigente` | GET |
  | `:549` | `/orgao/plantao/violencia-domestica` | GET |
  | `:624` | `/encaminhamento/encaminhar` | POST |
  | `:701` | `/pessoa` | POST |

- **`fetch`:** segue até 20 redirecionamentos. Em 301 e 302, um POST vira GET sem corpo; em 303, vira GET; em 307 e 308, mantém método e corpo. Num redirect para outra origem, remove o `authorization` e mantém o `x-client-id`.
- **`httpx` sem ajuste:** não segue. Devolve o próprio 3xx.
- **Efeito concreto:** o 3xx chega a `chamarVerdeComRetry`. Lá, `res.ok` é falso e `ehAuthOuInfra(3xx)` também, então a função cai na saída de negócio (`:71-74`): `{ok: false, falhaInfra: false}`, **sem retry e sem `falhaInfra`**.
  - Em `consultarApenadoPorRg` (`:163`), isso vira `encontrado: false`. O fluxo de pessoa presa pergunta "Não encontrei ninguém com esse RG… Quer tentar de novo?" a quem digitou um RG que existe, e depois de 3 vezes encerra com `motivoHandoff: "rg_nao_encontrado"`.
  - O mesmo vale para CPF (`:301`, `cpf_nao_encontrado`), e o encaminhamento (`:636-648`) vira `falha_encaminhamento` com `erro: "HTTP 302"`.
  - Os dois motivos de handoff são valores que o painel id 7 conta. A métrica de tentativas esgotadas subiria sem nenhum erro registrado.
- **O que a tradução faz:**
  - `follow_redirects=True` e `max_redirects=20` no cliente.
  - As regras de troca de método do httpx (301 e 302 POST→GET, 303→GET, 307 e 308 preservados) e a remoção do `authorization` em mudança de origem coincidem com as do `fetch`. O teste fixa isso, para não depender da coincidência.
- **Testes:** 1 e 1b (seção 7).

#### 3.1.2 Timeout total

- **Onde:**
  - `TIMEOUT_VERDE_MS = 30_000` (`:24`), aplicado como `signal: AbortSignal.timeout(TIMEOUT_VERDE_MS)` em cada uma das 9 chamadas (`:160`, `:225`, `:298`, `:379`, `:467`, `:511`, `:556`, `:633`, `:710`).
  - O sinal é criado **dentro** da função `montarRequisicao`, então cada tentativa tem seus próprios 30 s. O pior caso é de 90 s por consulta.
  - No WhatsApp, `TIMEOUT_WHATSAPP_MS = 10_000` (`whatsapp.ts:10`, `:30`).
- **Origem do número:** issue #196 (comentário em `:20-24`). Um RG real voltou "não encontrado" porque o Verde de homologação levou 13,5 s e o timeout era de 20 s. Neste código, o valor do timeout decide se a pessoa é encontrada ou não.
- **`fetch`:** o prazo é **total**, do envio ao último byte do corpo. O `await fetch(...)` resolve quando chegam os cabeçalhos, e isso acontece **dentro** do retry. O mesmo sinal continua valendo na leitura do corpo, que acontece **fora** do retry (`:164`, `:229`, `:302`, `:383`, `:471`, `:515`, `:561`, `:637`, `:650`, `:714`, `:723`).
- **`httpx` sem ajuste:** o timeout é **por fase** (conexão, escrita, cada leitura), com padrão de **5 s**. Além disso, `client.post(...)` lê o corpo inteiro antes de devolver, ou seja, **dentro** do retry.
- **Efeito concreto:**
  - **Cabeçalhos lentos (o caso da #196).** O `/apenado` de homologação levou 13,5 s para responder. Com o padrão de 5 s do httpx, as 3 tentativas estouram, e o RG que existe vira `falha_infra_verde`. É a regressão da #196, agora com 5 s em vez de 20 s.
  - **Corpo lento.** Uma resposta do `/pessoa?cpf=` com cabeçalhos aos 25 s e corpo chegando aos poucos até 45 s. Em develop, o sinal aborta a leitura aos 30 s, fora do retry, e a exceção sobe até a rota (500). Com timeout por fase, a resposta completa e a pessoa é encontrada.
  - O resultado do atendimento muda conforme a forma como o Verde entrega os bytes.
- **O que a tradução faz:**
  - Prazo de 30 s **por tentativa**, criado dentro de `montar_requisicao`, igual ao sinal por tentativa de hoje. O prazo é um instante absoluto (`asyncio.timeout_at`), que vale tanto para a espera dos cabeçalhos quanto para a leitura do corpo, mesmo quando a leitura acontece fora do retry.
  - **Conexão em 10 s, como o undici** (achado na releitura de 2026-10-13): o `fetch` do Node tem um prazo próprio só para abrir a conexão (TCP e TLS), `connectTimeout` = 10 s no undici, abaixo dos 30 s do `AbortSignal`. Medido no Node 24.21 contra um endereço que não responde: `ConnectTimeoutError` (`UND_ERR_CONNECT_TIMEOUT`) em 10,8 s. Com 3 tentativas, develop desiste de um Verde que não aceita conexão em cerca de 30 s; com só o prazo total, seriam 90 s. A tradução usa `httpx.Timeout(connect=10.0, …)`. O padrão do undici é o mesmo no Node 22 de develop; conferir junto com o `user-agent` (pendência 1).
  - As demais fases do httpx (leitura, escrita, espera por conexão do pool) ficam maiores que 30 s, para que só o prazo total aja. O `headersTimeout` e o `bodyTimeout` do undici (300 s) ficam acima dos 30 s e não agem em develop.
  - O WhatsApp usa 10 s, com a mesma técnica.
- **Leitura do corpo, separada por método.** A regra decidida na revisão está na seção 3.2.1: nos três POST, a leitura fica fora do retry, como em develop; nos seis GET, a divergência é aceita.
- **Testes:** 2, 2b, 18, 18b, 18c e 19.

#### 3.1.3 `true`/`True` na query string

- **Onde:** `:460`, `` `?indicacaoRO=${indicacaoRO}&idPessoa=${idPessoa}` ``.
  - `indicacaoRO` vem de `state.temRegistroOcorrencia ?? false`, em `violenciaDomestica/graph.ts:272`. É a resposta da pessoa a "Você já registrou o Boletim de Ocorrência?".
- **`fetch`:** a interpolação de booleano em template literal gera `true` ou `false`.
- **Python ingênuo:** `f"{indicacao_ro}"` gera `True` ou `False`.
- **Efeito concreto:**
  - É esse parâmetro que decide a regra de órgão do Verde. Com RO, a consulta vai para o Juizado de Violência Doméstica ou para a DP única; sem RO, para NUDEM, núcleo de 1º atendimento ou DP única (`verde.ts:420-430`).
  - Se o Verde recusar `True` com 400, a consulta vira "sem órgão" (`:470`) e o fluxo encerra em `sem_orgao_disponivel`.
  - Se o Verde interpretar `True` como falso, a vítima com Boletim de Ocorrência é encaminhada ao órgão errado, **sem nenhum erro**.
- **Mesmo mecanismo, com `null`:**
  - Em `:547`, `` idPlantao.map((id) => `idPlantao=${id}`) ``.
  - O filtro de `:517` mantém itens com `id: null` (tabela 3.3). Em develop, isso gera `idPlantao=null`; com Python ingênuo, `idPlantao=None`.
  - Em `:460` e `:549`, `idPessoa` e `idAssistido` chegam como `0` quando ausentes (`violenciaDomestica/graph.ts:267`), então não são afetados.
- **O que a tradução faz:**
  - Monta as duas URLs à mão, com `"true" if b else "false"` e com um formatador que reproduz o template literal do JS para `None` (`"null"`) e para inteiros.
  - Não usa `params=` do httpx, que serializa booleano à sua maneira.
- **Testes:** 3 e 3b.

#### 3.1.4 Escape de URL

- **Onde:**
  - `:218`, `/processo/consultar/${encodeURIComponent(numero)}`.
  - `:291`, `/pessoa?cpf=${encodeURIComponent(cpf)}`.
  - `:372`, `/cep/${encodeURIComponent(cep)}`.
- **Origem dos valores:**
  - `numero`: texto livre da pessoa, de `pedirNumeroProcesso`, sem limpeza (`pessoaPresa/graph.ts:154-161`, `violenciaDomestica/graph.ts:96-102`). Na resposta a "quer tentar de novo?", passa por um filtro de formato que conta só os dígitos e mantém o texto original (`violenciaDomestica/graph.ts:37-39`).
  - `cpf`: texto livre (`identificarAssistido/graph.ts:44-51`) ou `dadosConhecidos.cpf` da Tykhe. O comentário em `:262-264` registra que o Verde aceita CPF com pontuação.
  - `cep`: o `enderecoDetalhado.cep` devolvido pelo próprio Verde (`violenciaDomestica/graph.ts:234`), ou texto livre (`coletarEndereco/graph.ts:24-27`).
- **`fetch`:** `encodeURIComponent` codifica tudo, exceto `A–Z a–z 0–9 - _ . ! ~ * ' ( )`, inclusive `/`, `?`, `#`, espaço e acento.
- **Python ingênuo:** `quote(s)` tem `safe="/"` como padrão e deixa `/` **sem codificar**.
- **Efeito concreto:**
  - Um número de processo digitado como `0001234-56.2024/8.19.0001`, ou com barra, vira `/processo/consultar/0001234-56.2024/8.19.0001`, que é **outro caminho** no Verde. O Verde devolve 404, e por `:228` isso vira `encontrado: false`.
  - Em violência doméstica, o fluxo pergunta "Não encontrei esse número de processo… Quer tentar de novo?" (`violenciaDomestica/graph.ts:118-123`) para um processo que existe.
  - No CPF (`:291`), um `#` ou `&` no texto livre cortaria a query string.
- **O que a tradução faz:** `quote(s, safe="!*'()")`. A equivalência com `encodeURIComponent` foi verificada em develop para:
  - `123.456.789-01` → `123.456.789-01`;
  - `0000000-00.0000.0.00.0000` → sem alteração;
  - `a b/c?d=é` → `a%20b%2Fc%3Fd%3D%C3%A9`;
  - `!*()~'_.-` → sem alteração.

  O teste também confere que o httpx não normaliza de novo o caminho já codificado (a URL enviada é igual, byte a byte, à montada).
- **Testes:** 4 e 4b.

### 3.1.5 Outras divergências do mesmo cliente

| Ponto | `fetch` (Node 22, develop) | `httpx` (padrão) | O que a tradução faz |
|---|---|---|---|
| Corpo JSON | `JSON.stringify`: descarta chave `undefined`, **também aninhada**; sem espaços; UTF-8 cru | `json.dumps`: escreve `null`, separadores com espaço, `ensure_ascii=True` | **Corrigido na tradução:** `undefined` é **chave ausente** no dicionário, e `None` é o `null` do JS, enviado como `null`. Nada é removido antes de serializar: `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`. A versão anterior desta spec mandava remover `None` recursivamente, o que estaria errado: um `null` que veio do próprio Verde, como `bairro: {"nome": null}` repassado ao cadastro, é enviado como `null` por develop. Referência calculada no Node: `{"logradouro":"Rua São João","numero":"10","bairro":null,"uf":"RJ"}` para `complemento` undefined e `bairro` null. Consequência para os módulos de cima: um campo que em develop é `undefined` precisa ser **chave ausente** no estado, e não `None` |
| Proxy e certificados do ambiente | Ignora `HTTP(S)_PROXY` | `trust_env=True` lê `HTTP(S)_PROXY`, `NO_PROXY` e `SSL_CERT_FILE` | `trust_env=False` |
| `user-agent` | `node` | `python-httpx/x` | **Igualado** (decisão da revisão): `user-agent: node` fixado no cliente, para o Verde e para o WhatsApp. Motivo: uma regra por `user-agent` no Verde daria 403, que `logHttpNaoOk` classifica como `auth_ou_infra`, e a investigação começaria pelo token. Valor capturado com o `fetch` do Node 24.21 local. **Valor provisório para o Node 22 de develop: `node`**, o mesmo padrão do undici embutido; a conferir com Node 22 antes do merge do módulo (ver pendências) |
| `accept-encoding` | `gzip, deflate` em http; o undici acrescenta `br` em https | `gzip, deflate` (`br` só com o pacote `brotli`) | Aceito como está: não muda semântica, o httpx descomprime o que anunciar |
| Outros implícitos | `accept: */*` quando não definido, `accept-language: *`, `sec-fetch-mode: cors` | `accept: */*` | `accept: */*` coincide (é o que o `POST /apenado` envia). **`accept-language: *` e `sec-fetch-mode: cors` são igualados** (decisão da revisão), pelo mesmo raciocínio do `user-agent`. O `sec-fetch-mode` é o mais estranho dos três para um cliente de servidor: uma regra de borda do Verde que reagisse a ele apareceria como 403, classificado em `auth_ou_infra` |
| Conexões | Pool global do undici, keep-alive (conexões por origem sem limite; ociosa fecha em 4 s, `keepAliveTimeout`) | Sem cliente compartilhado, uma conexão nova por chamada | Um `httpx.AsyncClient` por processo, criado na primeira chamada (`obter_cliente_http()`, memoizado) e fechado por `fechar_cliente_http()` no `finally` do lifespan de `app.py`, no mesmo padrão do checkpointer e das stores. Nada entra no startup: em develop, o `fetch` não tem inicialização. Os testes injetam o `httpx.MockTransport` substituindo o cliente memoizado por fixture, que também o fecha ao fim de cada teste (um event loop por teste no pytest-asyncio) `httpx.Limits(max_connections=None, max_keepalive_connections=None, keepalive_expiry=4.0)`, no lugar dos padrões do httpx (100 conexões, 20 em keep-alive, 5 s). Com o padrão, a 101ª chamada simultânea ao Verde esperaria por conexão, onde develop abre outra: cenário teórico, mas a igualdade custa uma linha. **Limite ausente que ninguém escolheu**, nem em develop nem aqui: o Verde é sistema da Defensoria com capacidade desconhecida, e hoje o teto prático de chamadas simultâneas vem do número de atendimentos simultâneos, não da biblioteca. Aceito por fidelidade, não por desenho (registrado no `MIGRACAO.md`) |
| Erro de rede | `fetch` rejeita (`TypeError`) ou `AbortError` no timeout | `httpx.HTTPError` ou `TimeoutError` | Os dois caem no mesmo `except` do retry, classificados como `auth_ou_infra` |

### 3.2 Retry de infra (`chamar_verde_com_retry`)

Até 3 tentativas, **sem espera entre elas**, como em develop. Em cada tentativa:

1. **2xx:** devolve `{ok: True, res}`.
2. **Status que não é 401, 403 nem ≥ 500** (por exemplo 404, 422): registra `warn` e devolve `{ok: False, res, falhaInfra: False}` **na 1ª tentativa, sem retry**.
3. **401, 403 ou ≥ 500:** registra `error` com `tentativa` e `tentativasRestantes`. Na 3ª tentativa, devolve `{ok: False, res, falhaInfra: True}`.
4. **Exceção** (rede ou timeout): registra `error` com `err`. Na 3ª tentativa, devolve `{ok: False, falhaInfra: True}`, sem `res`.

**Corpo que não é JSON.** Em develop, o `res.json()` roda **fora** do retry. Nos GET e no `/apenado`, um corpo 2xx que não seja JSON lança exceção, que sobe até o nó do grafo e vira 500 na rota. Isso se mantém nos nove casos, porque o parse do JSON fica fora do retry também em Python.

#### 3.2.1 Leitura do corpo: POST fora do retry, GET dentro (decisão da revisão)

O que muda entre as duas linguagens é **onde os bytes do corpo são lidos**. Em develop, isso acontece sempre fora do retry. O `client.post/get` do httpx lê dentro, a menos que a requisição seja feita em modo stream.

**Os três POST: leitura do corpo fora do retry, reproduzindo develop.** São eles `/apenado` (`:152`), `/encaminhamento/encaminhar` (`:624`) e `/pessoa` (`:701`). Se o timeout cai na leitura do corpo, o Verde já recebeu a requisição e provavelmente já processou. Reenviar significaria um encaminhamento duplicado ou uma segunda tentativa de cadastro, que é pior que o desfecho de develop.

A tradução usa `client.send(req, stream=True)` dentro do retry, que devolve ao chegar os cabeçalhos, como o `await fetch`. A leitura (`await res.aread()`) fica fora do retry, sob o mesmo prazo absoluto da tentativa que deu certo. O que acontece em develop quando a leitura falha (timeout, conexão cortada) não é igual nos três, e cada um é reproduzido:

| POST | Leitura em develop | Leitura falha no meio → desfecho em develop (reproduzido) |
|---|---|---|
| `/apenado` | `await resultado.res.json()`, sem `catch` (`:164`) | A exceção sobe e vira **500 na rota**. Um único POST enviado |
| `/encaminhamento/encaminhar` | `.json().catch(() => ({}))` (`:650`; no erro, `:637`) | A falha é engolida, e o corpo vira `{}`. Resultado `{sucesso: true, id: undefined}`; no grafo, `encaminhamentoId` fica ausente e o fluxo vai para `falhou` (`falha_encaminhamento`). **Não é 500.** Um único POST enviado |
| `/pessoa` | `.json().catch(() => ({}))` (`:723`; no erro, `:714`) | A falha é engolida, e o corpo vira `{}`. Resultado `{sucesso: false, erro: "Verde não devolveu idPessoa"}` (`:728`). **Não é 500.** Um único POST enviado |

Nota da verificação: a premissa da revisão de que "em develop isso vira 500 e para" vale só para o `/apenado`. Nos dois POST de escrita, o `.catch(() => ({}))` transforma a falha de leitura em desfecho de negócio. A decisão não muda (nenhum reenvio), mas o teste fixa o desfecho real, e não um 500.

**Os seis GET: divergência aceita e registrada.** Em `/processo`, `/pessoa?cpf=`, `/cep`, `/orgao/violencia-domestica`, `/plantao/vigente` e `/orgao/plantao/violencia-domestica`, a leitura fica dentro do retry, pelo caminho normal do httpx. Um timeout no meio do corpo, que em develop vira 500, em Python é retentado. Retentar uma leitura é inofensivo e, no pior caso, transforma um 500 em sucesso ou em `falhaInfra`. Fica registrado no `MIGRACAO.md` como divergência aceita.

**Idempotência no Verde (verificado).** O Swagger público do Verde (`https://homologacao.verde.rj.def.br/api/swagger.json`, Swagger 2.0, 54 caminhos, consultado em 2026-10-09) **não** documenta chave de idempotência em nenhum endpoint. Nenhum parâmetro de cabeçalho aparece além de `Authorization` e `X-Client-Id` nas rotas de token, e as palavras `idempot`, `request-id` e `correlation` não ocorrem no documento. Por isso, **não** há issue a abrir. Há uma assimetria entre os dois endpoints:
- `POST /integra/pessoa` documenta 422 "Pessoa já cadastrada anteriormente" ("O CPF deve ser válido e não pode estar cadastrado"). O Verde barra o cadastro duplicado pelo CPF. Um reenvio daria 422, não uma segunda pessoa.
- `POST /integra/encaminhamento/encaminhar` documenta só 201, 400 e 422 ("Usuário do site não encontrado", "É necessário definir o fluxo"), sem nenhuma proteção contra duplicidade. Um reenvio cria **outro** encaminhamento. Isso já aconteceu em produção pelo bug da #108 (`docs/integracao-verde.md`).

**Risco que já existe em develop e não muda.** O retry de develop reenvia os três POST em dois casos: timeout **antes** dos cabeçalhos e resposta 5xx. Nos dois, o Verde pode ter processado a requisição. Com o encaminhamento sem proteção, isso pode duplicar. A tradução reproduz esse comportamento, porque mudá-lo seria alterar comportamento. A melhoria (não retentar o encaminhamento depois que a requisição foi enviada, ou consultar antes de reenviar) vai para o `MIGRACAO.md`, fora do escopo.

### 3.3 Interpretação das respostas: `undefined`, `null` e objeto vazio

Em develop, as checagens distinguem "chave ausente" de `null` e tratam `{}` como verdadeiro. Em Python, `not {}` é `True`, e `get(...) is None` não diferencia ausente de `null`. A tradução usa um auxiliar explícito por regra:

| Local (develop) | Expressão | Regra em Python |
|---|---|---|
| apenado, pessoa `:170`, `:304` | `!corpo.dados \|\| corpo.dados.idPessoa === undefined` | Não encontrado se `dados` for ausente ou `null`, **ou** se a **chave** `idPessoa` estiver ausente. `idPessoa: null` conta como **encontrado**, com `idPessoa = None` |
| processo `:231` | `!corpo.dados \|\| corpo.dados.id === undefined` | Mesma regra, com a chave `id` |
| cep `:385` | `!corpo.dados` | Não encontrado só se `dados` for ausente ou `null`. `dados: {}` conta como **encontrado**, com todos os campos ausentes |
| cep `:333-339` | `campo && typeof campo === "object" ? campo.id : undefined` | Só lê `id` ou `nome` se o campo for um `dict` |
| cep `:394` | `logradouro ?? undefined` | `null` vira ausente |
| órgãos `:479`, `:577-581` | `o.id ?? 0`, `o.nome ?? ""` | `null` ou ausente viram `0` ou `""` |
| órgãos `:476` | `codigo === "CONTACTAR_CRC"` | Igualdade estrita de string |
| órgãos plantão `:566` | `if (corpo.codigo)` | Verdadeiro para string não vazia. Qualquer `codigo` não vazio vira `contactarCrc` |
| órgãos plantão `:575-576` | `dados` objeto ou lista | Lista → lista. Objeto não vazio → `[objeto]`. `null`, ausente ou falso → `[]` |
| plantão `:517` | `filter(p => p.id !== undefined)` | Mantém itens com `id: null` (chave presente). Descarta só os sem a chave |
| encaminhamento `:652` | `{ sucesso: true, id: corpo.dados?.id }` | `sucesso: True` mesmo sem `id`. Se `id` vier `null`, o estado guarda `None` (ver efeito no grafo, seção 5) |
| cadastro `:728` | `corpo.dados?.idPessoa === undefined` | Falha só se a **chave** estiver ausente. `idPessoa: null` é sucesso |
| encaminhamento e cadastro com erro `:637`, `:714` | `res?.json().catch(() => ({}))` | Corpo que não é JSON vira `{}`. Sem `res` (exceção de rede), `corpoErro` fica ausente |
| encaminhamento e cadastro com erro `:648`, `:721` | `mensagem ?? (falhaInfra ? "falha na chamada ao Verde (infra esgotada)" : "HTTP {status}")` | Textos idênticos. Sem `res`, o texto é `HTTP undefined`, que precisa ser reproduzido literalmente |

### 3.4 Modo mock

- **Quando:** `VERDE_JWT_TOKEN` vazio ou ausente, lido **uma vez, na importação do módulo**, como em develop (`verde.ts:17-19`). Os testes dependem disso.
- **O que se preserva:** sentinelas e valores devolvidos copiados **literalmente**, inclusive os textos `(mock)` e os ids `999999`, `888888`, `274`, `525`, `999`, `222`, `1233`, `333`, `19`, `9948` e `3643`.
- **Sentinelas:**
  - RG: `000000000`, `66666666666`, `22222222222`, `33333333333`, `44444444444`, `55555555555`.
  - Processo: `000000000`, `0000000-00.0000.0.00.0000`.
  - CPF: `00000000000`, `66666666666`.
  - CEP: `00000000`, depois de remover tudo o que não for `[0-9]`.
- **Dois momentos de leitura do ambiente, preservados (decisão da revisão):**
  - **Na importação, uma vez:** `VERDE_API_URL`, `VERDE_JWT_TOKEN` e `VERDE_CLIENT_ID` (`verde.ts:17-19`), e `WHATSAPP_API_URL`, `WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_ACCESS_TOKEN` (`whatsapp.ts:7-9`). Todas com `?? ""` (ou com a URL padrão), e nenhuma lança exceção no topo do módulo. Não há fail-fast a preservar; ler na importação é a tradução fiel (`os.environ.get(..., "")` no nível do módulo). A configuração de teste da fundação define o ambiente antes de qualquer importação do pacote.
  - **A cada chamada:** `MOCK_CEP_INCOMPLETO` (`:358`), `MOCK_PLANTAO_VIGENTE` (`:499`), `MOCK_ENCAMINHAMENTO_FALHA` (`:610`) e `MOCK_CADASTRO_FALHA` (`:690`), sempre comparadas com a string exata `"true"`. São os interruptores que permitem testar caminhos de falha em tempo de execução, então a leitura fica **dentro** da função (`os.environ.get("MOCK_…") == "true"`), nunca em constante de módulo.
- **Log:** cada chamada em modo mock registra `warn` com o contexto (`chatId`, `fluxoId`) e a mensagem `[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)`.
- **Regex:** `cep.replace(/\D/g, "")` vira `re.sub(r"[^0-9]", "", cep)`, e **não** `\D`, que em Python casa dígitos Unicode.

### 3.4.1 Credencial do Verde: estado em 2026-10-13

O comentário de `verde.ts:14-15` ("expira 2026-09-12 — precisa de credencial própria da Maria antes disso") está **desatualizado**. A renovação passou a ser automática, feita pelo workflow `verificar-token-verde.yml` (issues #113, #187 e #194, descritas em `docs/integracao-verde.md`). A aplicação só lê o token no boot. Estado pelas execuções do workflow (`gh run list`, 22 execuções de 2026-09-19 a 2026-10-09):

| Ambiente | Estado |
|---|---|
| **prod** | **Renovado.** Em 2026-09-28, o workflow renovou por refresh. Em 2026-09-29 e 09-30, o status voltou `revogado=True`. Desde 2026-10-01, há um token válido, emitido de novo, com `expiraEm=2026-11-01T09:28:22-03:00` (22,8 dias em 2026-10-09). A próxima janela de renovação automática abre por volta de 2026-10-25, 7 dias antes. A última renovação automática foi revogada em um dia |
| **release** | **Inválido.** `GET /autenticacao/token/status` responde 403 de 2026-09-28 a 10-04 e 401 `NAO_AUTORIZADO` desde 2026-10-05. Em 2026-09-22, o token de release expirava em 11,9 dias, por volta de 2026-10-04. O 403 começou no mesmo dia do refresh de prod; a coincidência está registrada, mas a causa não foi confirmada |
| workflow | **20 falhas seguidas**, todas as execuções de 2026-09-23 a 2026-10-12 (a de 10-13 ainda não tinha rodado na consulta). O último sucesso foi em 2026-09-22. Hoje ele falha só pelo release, mas a falha diária esconde qualquer problema novo de prod |

Efeito na migração:
- **Nenhum teste deste módulo depende do token.** Todos rodam em modo mock ou com `httpx.MockTransport`.
- **O release depende.** O plano de corte valida em release primeiro, e com o token inválido toda chamada real ao Verde dá 401, que vira `auth_ou_infra` e, depois de 3 tentativas, `falha_infra_verde`. Um token válido em release é **pré-requisito do corte**, e entra nas decisões em aberto da #208.
- O comentário vai traduzido e atualizado: aponta para o workflow e para `docs/integracao-verde.md`, sem data de expiração fixa.

### 3.5 WhatsApp

- **Envio:**
  - Sem `WHATSAPP_ACCESS_TOKEN` ou `WHATSAPP_PHONE_NUMBER_ID`, registra `warn` com o evento `whatsapp_envio_mock` e retorna. As variáveis são lidas na importação.
  - Com elas: `POST {WHATSAPP_API_URL}/{PHONE_NUMBER_ID}/messages` com `{"messaging_product":"whatsapp","to":para,"type":"text","text":{"body":texto}}`, timeout total de 10 s.
  - Status fora de 2xx: lê o texto. Se for JSON com `error`, registra `erroDetalhe: {codigo, tipo}`; se não for, omite `erroDetalhe`. Evento `whatsapp_envio_falhou`, nível `error`.
  - Exceção: evento `whatsapp_envio_erro`, com `erro` igual à mensagem da exceção.
  - **Nunca lança exceção.** Nunca registra `texto`, número de destino nem corpo bruto.
- **Extração** (`extrair_mensagem_whatsapp` e `extrair_status_whatsapp`):
  - Percorre `entry[]` e, dentro de cada um, `changes[]`. Em cada `change`, olha **só o 1º item** de `messages` ou `statuses`. Se ele não servir, passa ao próximo `change`, não ao próximo item.
  - O encadeamento opcional do JS (`?.`) não lança exceção nos níveis em que é usado (`payload`, `entry[]`, `changes[]`, `value`). **Corrigido na tradução:** o 1º item de `messages` e de `statuses` é lido **sem** `?.` (`whatsapp.ts:81` e `:115`), então um item `null` ali lança `TypeError` em develop, e a tradução reproduz isso.
  - A mensagem só vale se `type == "text"` e se `from` e `text.body` forem verdadeiros (string vazia descarta).
  - O status só vale se `status` for verdadeiro. `erroCodigo` e `erroTitulo` vêm de `errors[0]` quando `errors` é uma lista não vazia.
- **O que este módulo deixa para o `api` (ponte, `webhookWhatsapp.ts`):**
  - `conversasAtivas`: dicionário em memória `número → chatId`, com `chatId = "whatsapp:{numero}:{Date.now()}"` (milissegundos de época, inteiro).
  - `filaPorNumero`: serialização FIFO por número. A tarefa seguinte roda **mesmo se a anterior falhou** (`anterior.then(tarefa, tarefa)`). Em Python: um `asyncio.Lock` por número, que é FIFO. As chaves nunca são removidas, igual a develop.
  - Um único worker do uvicorn. Com mais de um, os dicionários divergem entre processos.
  - O estado zera a cada reinício. Isso já é aceito em develop (`webhookWhatsapp.ts:26-36`).

## 4. Casos de erro

| Situação | Comportamento esperado (igual a develop) |
|---|---|
| 404 ou 422 do Verde | Sem retry, `warn`, `encontrado: False` (ou `sucesso: False` com `HTTP 404`) |
| 401, 403 ou 5xx nas 3 tentativas | 3 linhas `error`. Apenado e pessoa devolvem `falhaInfra: True`. Processo, CEP, órgãos e plantão devolvem só "não encontrado" ou vazio, **sem** `falhaInfra` (`verde.ts:228`, `:382`, `:470`, `:514`, `:559`) |
| Timeout ou erro de rede nas 3 tentativas | 3 linhas `error` com `err`, e o mesmo desfecho da linha anterior |
| Erro na 1ª tentativa e sucesso na 2ª | Uma linha `error` e o resultado de sucesso |
| 2xx com corpo que não é JSON | Exceção propagada (500 na rota), salvo em encaminhamento e cadastro, onde vira `{}` |
| Timeout ou conexão cortada **lendo o corpo** de um POST | Nenhum reenvio. `/apenado`: 500 na rota. Encaminhamento: `sucesso: True` sem `id`, e o grafo vai para `falha_encaminhamento`. Cadastro: `sucesso: False`, `"Verde não devolveu idPessoa"` (seção 3.2.1) |
| Timeout ou conexão cortada **lendo o corpo** de um GET | Divergência aceita: em Python, conta como falha de infra e é retentado; em develop, era 500 |
| `encodeURIComponent` com surrogate isolado | Em JS lança `URIError`. Em Python, `quote` codificaria. Hoje não é alcançável, porque os valores vêm de JSON válido; registrado como divergência aceita |
| Falha no envio do WhatsApp | Só log. Nunca exceção |

## 5. O que não muda

- URLs, métodos, cabeçalhos explícitos, ordem e presença das chaves dos corpos.
- `TIMEOUT_VERDE_MS = 30_000`, `TENTATIVAS_RETRY_VERDE = 3` e nenhuma espera entre tentativas.
- `VERDE_API_URL` padrão `https://homologacao.verde.rj.def.br/api/integra`. `WHATSAPP_API_URL` padrão `https://graph.facebook.com/v21.0`.
- Sentinelas e valores de mock.
- O encaminhamento com `id` ausente ou `null` continua `sucesso: True`. No grafo, `encaminhamentoId` fica `None` e `depoisDeCriarEncaminhamento` compara `!== undefined`. Com a chave **ausente**, o fluxo vai para `falhou`. Com `null`, o fluxo vai para `concluir`, e a mensagem final sai com `Protocolo: null.`. Essa última parte é responsabilidade do módulo `fluxos`, mas a origem está aqui.
- Nenhum dado pessoal no log: o CPF, o RG, o texto do WhatsApp e o número de destino nunca são registrados.

## 6. Observabilidade

| Evento ou mensagem | Nível | Campos (camelCase, no primeiro nível; ausentes omitidos) |
|---|---|---|
| `[verde] {chamada}: HTTP não-ok` | `error` (`auth_ou_infra`) ou `warn` (`nao_encontrado`) | `chatId`, `fluxoId`, `status`, `tipoErro`, `evento:"verde_chamada"`, `chamada`, `resultado:"nao_ok"`, `duracaoMs`, e em infra `tentativa` e `tentativasRestantes` |
| `[verde] {chamada}: falha na chamada (tentativa {n})` | `error` | `chatId`, `fluxoId`, `err`, `evento`, `chamada`, `resultado:"erro"`, `duracaoMs`, `tentativa`, `tipoErro:"auth_ou_infra"` |
| `[verde] {chamada}: chamada concluída` | `info` | `chatId`, `fluxoId`, `evento`, `chamada`, `resultado:"sucesso"`, `duracaoMs`. Em encaminhamento e cadastro, também `corpo` |
| `[verde] encaminhamento: falhou, corpo de erro da Verde` e `[verde] cadastroPessoa: falhou, ...` | `error` | `corpo`, `status`, `evento`, `chamada`, `resultado:"nao_ok"`, `duracaoMs` |
| `[whatsapp] mensagem enviada` / `envio falhou` / `erro ao enviar mensagem` / modo mock | `info` / `error` / `error` / `warn` | `chatId`, `duracaoMs`, `evento`, `status`, `erroDetalhe`, `erro` |

Detalhes:
- `chamada` mantém os valores literais `apenado`, `processo`, `pessoa`, `cep`, `orgao-violencia-domestica`, `plantao-vigente`, `orgao-plantao-violencia-domestica`, `encaminhamento` e `cadastroPessoa`. O painel id 5 agrupa por `chamada` e `resultado`; o painel id 13, por `chamada`, `tipoErro` e `status`.
- `duracaoMs` é um inteiro em ms.
- `err` segue o serializador do pino: `{type, message, stack}`.
- O 1º log de sucesso é emitido **depois** do `res.json()`, exceto no órgão de plantão, que registra antes do parse (`verde.ts:560`). A ordem se mantém.

## 7. Testes que provam

**Traduzidos:** `verde.test.ts`, 8 testes de retry e classificação com requisição falsa injetada.

**Novos.** Todos com transporte falso do httpx (`httpx.MockTransport`), sem rede:
1. (3.1.1) `consultar_apenado_por_rg` com 302 para outra URL que responde 200 com `idPessoa` devolve `encontrado: True`, não `rg_nao_encontrado`.
1b. (3.1.1) `POST /encaminhamento/encaminhar` com 302 vira GET sem corpo; com 307, repete POST com o mesmo corpo. Em redirect para outra origem, o `authorization` é removido e o `x-client-id` é mantido.
2. (3.1.2) O `/apenado` com cabeçalhos aos 13,5 s (o caso da #196) é **encontrado**: o padrão de 5 s do httpx não age. Com cabeçalhos depois de 30 s, cada tentativa conta como falha de infra, e ao fim de 3 dá `falhaInfra: True`, como em develop.
2b. (3.1.2) Cada tentativa tem os próprios 30 s: duas tentativas lentas e uma rápida terminam em sucesso.
3. (3.1.3) `consultar_orgaos_violencia_domestica(True, 123)` envia exatamente `?indicacaoRO=true&idPessoa=123`, e com `False`, `indicacaoRO=false`.
3b. (3.1.3) `consultar_orgaos_plantao_violencia_domestica([1, None], 5)` envia `?idPlantao=1&idPlantao=null&idAssistido=5`, igual a develop.
4. (3.1.4) As URLs de processo, CPF e CEP para `123.456.789-01`, `0000000-00.0000.0.00.0000`, `a b/c?d=é`, `!*()~'_.-` e um número com `/` e `#` são iguais, byte a byte, às de `encodeURIComponent`. Os valores de referência foram calculados em develop.
4b. (3.1.4) Um número de processo com `/` chega ao Verde como **um** segmento de caminho (`%2F`), não como dois.
5. O corpo do cadastro, com `endereco` sem a chave `complemento` e com `bairro: None`, é igual byte a byte ao `JSON.stringify` de develop: sem `complemento` e com `"bairro":null`.
6. O corpo do encaminhamento mantém a ordem das chaves e omite `idLocalAtendimento` e `motivoUrgencia` quando ausentes.
7. O `POST /apenado` não envia `accept`. Os GET enviam `accept: application/json`.
8. Com `HTTPS_PROXY` definido no ambiente, a requisição **não** passa pelo proxy (`trust_env=False`).
9. Apenado com `dados: {}` é não encontrado. Com `dados: {"idPessoa": null}` é **encontrado**, com `idPessoa = None`.
10. CEP com `dados: {}` é **encontrado**, sem campos.
11. Plantão com `[{"id": null}, {"tipo": "x"}]` devolve só o primeiro item.
12. Órgão de plantão com `dados` em objeto único vira uma lista de 1. Com `codigo` não vazio, vira `contactarCrc`.
13. Encaminhamento com 2xx e `dados.id` ausente dá `sucesso: True` sem `id`. Com exceção de rede nas 3 tentativas, dá `erro: "falha na chamada ao Verde (infra esgotada)"`.
14. Sentinela de CEP com dígitos Unicode (`"٠٠٠٠٠٠٠٠"`) **não** é tratada como `00000000`.
15. `extrair_mensagem_whatsapp` com `entry: [null, 1, {"changes": "x"}]` devolve `None` sem lançar exceção. Com a 1ª mensagem do `change` não sendo de texto e a 2ª sendo, devolve `None` para esse `change`. Com o 1º item de `messages` ou de `statuses` igual a `null`, lança `TypeError`, como develop.
16. `enviar_mensagem_whatsapp` com 400 e corpo `{"error":{"code":131026,"type":"OAuthException","message":"... +5521..."}}` registra só `codigo` e `tipo`. Nenhuma linha de log contém o número.
22. Consulta de CPF com o transporte falso devolvendo 500 nas 3 tentativas e, em outro cenário, lançando timeout: nenhuma linha de log, nossa ou de biblioteca, contém o CPF consultado, com `configurar_logging_stdlib()` ativo como no `main.py`. Cobre o `err` das exceções, que pode carregar a URL.
23. Os parâmetros do cliente HTTP, inspecionados sem rede: `timeout.connect == 10.0`, as fases de leitura, escrita e pool acima de 30 s, `limits` sem máximo de conexões e com `keepalive_expiry == 4.0`, `follow_redirects` e `trust_env`. Falha se alguém voltar aos padrões do httpx.
17. Os logs de `verde_chamada` têm as chaves e os níveis da seção 6. Uma chave ausente, como `fluxoId` fora de um run, não aparece como `null`.
18. (3.2.1) `criar_encaminhamento_violencia_domestica` com 201 cujo corpo para de chegar até estourar os 30 s: o transporte falso registra **exatamente um** POST, e o resultado é `sucesso: True` sem `id` (que no grafo vai para `falha_encaminhamento`). Não há exceção.
18b. (3.2.1) `cadastrar_pessoa` no mesmo cenário: **um** POST e `{sucesso: False, erro: "Verde não devolveu idPessoa"}`.
18c. (3.2.1) `consultar_apenado_por_rg` no mesmo cenário: **um** POST e exceção propagada.
19. (3.2.1) `consultar_pessoa_por_cpf` com corpo cortado no meio na 1ª tentativa e íntegro na 2ª: o resultado é **encontrado**, depois de dois GET e uma linha `error`. A divergência aceita fica fixada no teste.
20. Todas as requisições ao Verde e ao WhatsApp saem com `user-agent: node`, `accept-language: *` e `sec-fetch-mode: cors`.
21. Com o mesmo processo e o módulo já importado, `MOCK_ENCAMINHAMENTO_FALHA=true` definido entre duas chamadas muda a segunda para `falha simulada (mock)`. O mesmo vale para as outras três variáveis `MOCK_`. Mudar `VERDE_JWT_TOKEN` depois da importação **não** tira o módulo do modo mock.

## 8. Critérios de aceite

- [ ] Os 8 testes traduzidos e os 29 novos passam, sem rede (23 numerados, mais 1b, 2b, 3b, 4b, 18b e 18c).
- [ ] Cada uma das quatro divergências da seção 3.1 tem pelo menos um teste que falharia com a tradução ingênua.
- [ ] Nenhum dos três POST é reenviado quando a falha acontece lendo o corpo (testes 18, 18b e 18c).
- [ ] Cliente `httpx.AsyncClient` único, com `follow_redirects=True`, `trust_env=False` e os cabeçalhos `user-agent: node`, `accept-language: *` e `sec-fetch-mode: cors`, `httpx.Timeout(connect=10.0)` com as demais fases acima de 30 s, e `httpx.Limits(max_connections=None, max_keepalive_connections=None, keepalive_expiry=4.0)`. Criado na primeira chamada e fechado por `fechar_cliente_http()`, que entra em `FINALIZADORES` de `app.py` (criado no módulo persistencia).
- [ ] Teste 23: os parâmetros do cliente (timeout por fase e limites), inspecionados sem rede, como `tests/shared/test_pool.py`.
- [ ] `httpx` passa de dependência de desenvolvimento (fundação) para dependência de runtime no `pyproject.toml`, com o `uv.lock` atualizado.
- [ ] **Logs de dependência (regra do `MIGRACAO.md`):** para cada dependência nova deste módulo, o PR responde o que ela registra por padrão, em que logger e em que nível, e confirma que nada com dado pessoal passa pela ponte da fundação (bibliotecas só de WARNING para cima). Aqui: `httpx` (INFO `HTTP Request: <método> <URL completa>`, com `?cpf=` no Verde) e `httpcore` (DEBUG). Teste 22 cobre o caminho das exceções.
- [ ] Nenhuma variável `MOCK_` lida em constante de módulo.
- [ ] Nenhuma URL com parâmetro booleano montada por `params=`.
- [ ] Nenhuma checagem de presença em resposta do Verde feita com `not dados` ou `.get(...) is None` onde o original distingue ausente de `null` (revisão contra a tabela 3.3).
- [ ] Sentinelas e valores de mock idênticos aos de develop (revisão por diff dos literais).
- [ ] Eventos e campos de log da seção 6 idênticos, inclusive os valores de `chamada`.
- [ ] `ruff`, `ruff format --check`, `mypy` (strict no projeto inteiro, configuração da fundação) e `pytest` verdes, e os jobs `test` e `imagem` do CI verdes.
- [ ] Decisões registradas na #208 (comentário 10, já publicado) e no `MIGRACAO.md` (a fundação já registrou as decisões desta spec; o módulo acrescenta só o que mudar na implementação).

## Decisões da revisão (2026-10-09)

1. **Leitura do corpo separada por método** (seção 3.2.1): nos POST, fora do retry, reproduzindo develop; nos GET, a divergência é aceita. O Verde não tem chave de idempotência, então nenhuma issue foi aberta.
2. **Cabeçalhos implícitos igualados:** `user-agent: node` (provisório, ver pendência 1), `accept-language: *` e `sec-fetch-mode: cors`. O `accept-encoding` segue como está.
3. **Ambiente:** as variáveis de credencial são lidas na importação, e as `MOCK_` a cada chamada.
4. O restante foi aprovado, inclusive os testes da versão anterior e a tabela 3.1.5.

## Releitura contra a fundação (2026-10-13)

Spec escrita antes da fundação e relida contra o que o PR #213 entregou. O que mudou:
1. **`shared/types.py`:** a releitura achou cinco campos tipados como `int` que o Verde devolve como `null`; a correção acabou na própria fundação, antes do merge, e com um sexto campo que a releitura tinha deixado passar (`DadosProcesso.id`, mesma regra da tabela 3.3, `verde.ts:231`). Este módulo não altera o arquivo.
2. **Ciclo de vida do cliente HTTP:** criado na primeira chamada e fechado no `finally` do lifespan de `app.py`, que agora existe; não depende mais do módulo `api` (tabela 3.1.5).
3. **`httpx` vira dependência de runtime:** na fundação, ele entrou só no grupo de desenvolvimento.
4. **Pendência do Node 22:** o Docker não roda na máquina da fundação; alternativa registrada.
5. mypy strict vale para o projeto inteiro; jobs `test` e `imagem` obrigatórios.

\1 a ponte do logging padrão da fundação deixa passar só WARNING ou mais para bibliotecas, então o INFO do `httpx` (que traria a URL com `?cpf=`) não chega ao log; o logger serializa `err` como o pino (`{type, message, stack}`) e omite `None`; `contexto_atual()` devolve só as chaves presentes.

## O que a tradução encontrou (2026-10-13)

Esta spec foi escrita por leitura de código e relida contra a fundação e contra o persistencia. A tradução linha a linha ainda encontrou três pontos, todos corrigidos acima:

1. **`dados` como objeto, ou item `null` na lista, gera 500 em develop.** `(corpo.dados ?? []).map(...)` (`verde.ts:479`) e `.filter(...)` (`:517`) lançam `TypeError` quando `dados` não é array, e `o.id` lança quando um item é `null`. Um `for` em Python iteraria as chaves do dicionário em silêncio. A tradução lança `TypeError` nos mesmos casos (teste 12b).
2. **A extração do WhatsApp lança em um caso:** o 1º item `null` de `messages` ou `statuses` (seção 3.5, teste 15).
3. **`None` no corpo enviado não é removido:** `undefined` é chave ausente, e `None` é `null` (tabela 3.1.5, teste 5). A versão anterior desta spec estava errada nesse ponto.

Para acessar respostas com a semântica de JS (ausente × `null`, `{}` verdadeiro, `TypeError` em `null.campo`), a tradução usa um auxiliar único, `integracoes/_js.py`, em vez de `dict.get` espalhado.

**Verificação por mutação.** Para cada divergência, a tradução ingênua foi aplicada no código e o teste correspondente foi rodado: redirect (`follow_redirects=False`), prazo de conexão (`connect=5.0`), `True` na query string, escape com `quote` padrão, leitura do corpo do POST dentro do retry (encaminhamento e apenado) e remoção recursiva de `None`. **Os sete testes falharam com a mutação e voltaram a passar com o código correto.**

**Calibragem confirmada:** a releitura contra o persistencia achou o prazo de conexão do undici; a tradução achou mais três. É a mesma proporção do persistencia: leitura de código não acha tudo, e a issue do módulo é atualizada antes do PR.

## Releitura contra o persistencia (2026-10-13)

Spec relida contra o que o módulo persistencia (#216, PR #218) entregou e contra o padrão nomeado nele: **parâmetro com nome familiar e semântica diferente entre bibliotecas** (comentário 12 da #208). Cada parâmetro do cliente HTTP foi conferido nos dois lados:

| Parâmetro | `fetch`/undici (develop) | httpx (padrão) | Situação |
|---|---|---|---|
| Redirect | segue até 20 | não segue | já tratado (3.1.1) |
| Prazo total | 30 s por tentativa (`AbortSignal`) | não existe; prazos por fase, de 5 s | já tratado (3.1.2) |
| **Prazo para abrir a conexão** | **10 s** (`connectTimeout` do undici), medido | 5 s, ou o que for configurado | **novo:** `connect=10.0` |
| Leitura de cabeçalhos e corpo | 300 s (abaixo deles age o `AbortSignal` de 30 s) | 5 s por leitura | já tratado: fases acima de 30 s |
| Conexões simultâneas | sem limite por origem | 100 | **novo:** `max_connections=None`. Fidelidade, não desenho: ninguém escolheu esse limite ausente, nem em develop |
| Conexão ociosa | 4 s (`keepAliveTimeout`) | 5 s | **novo:** `keepalive_expiry=4.0` |
| Proxy do ambiente | ignora | lê `HTTP(S)_PROXY` | já tratado (`trust_env=False`) |

O que mudou em relação à versão anterior:
1. **Prazo de conexão de 10 s** (3.1.2 e critério de aceite). É o terceiro caso do padrão neste projeto, depois do `prepare_threshold` e do `timeout` do pool, e só apareceu porque a releitura conferiu os parâmetros um a um, nos dois lados.
2. **Limites de conexão** iguais aos do undici (tabela 3.1.5).
3. **Fechamento do cliente** em `FINALIZADORES` de `app.py`, que o persistencia criou.
4. **Logs:** o `httpx` e o `httpcore` já estão em `BIBLIOTECAS_COM_NIVEL_FIXO` desde a fundação. O teste 22, que cobre o caminho das exceções, continua necessário.
5. **Token do Verde:** estado atualizado para 2026-10-13. Nada mudou: release com 401 e prod válido até 01/11.

**Expectativa:** a spec de persistencia previu três divergências e a tradução achou quatro (comentário 12 da #208). Esta spec foi escrita do mesmo jeito, por leitura de código, e deve ser lida como ponto de partida; o que a tradução encontrar entra na issue do módulo antes de o PR abrir.

## Pendências

1. **`user-agent` no Node 22.** O valor `node` foi capturado com Node 24.21. A tentativa com `npx node@22` não devolveu saída. **Valor provisório: `node`.** Conferir com Node 22 antes do merge do módulo; se for diferente, o ajuste é uma linha. `docker run node:22-alpine` **não serve na máquina da fundação**, que não tem virtualização. Alternativa: o binário portátil do Node 22 (zip oficial de nodejs.org, sem instalar), rodando o mesmo servidor de captura de cabeçalhos.
2. **Token de release inválido** (seção 3.4.1). Não bloqueia este módulo, mas é pré-requisito do corte, e está registrado nas decisões em aberto da #208 (item 3).
