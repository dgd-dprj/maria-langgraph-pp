# Guia de teste em homologação: a Maria em Python no release

> **Corrigido em 2026-10-26: a equipe está testando na produção (`main`, serviço `api`), pela Tykhe, e não no release.** Isso muda três coisas para quem usa este guia:
> - **os atendimentos de teste ficam misturados aos de cidadãos** na produção. Os dois chegam pela Tykhe, com o mesmo formato de `chatId`, e o log da Maria não separa um do outro (#208);
> - **o horário combinado vale para o PR de release** (`develop` → `main`), que reinicia a produção, e não para os merges em `develop`;
> - **a produção também consulta o Verde de homologação** (#286), então a regra de usar só dados inventados ou os de teste da homologação continua valendo.
>
> O resto do guia foi escrito para o release e fica como está, para registro.

> **O release usa o Verde de homologação** (verificado em 2026-10-22, #286). As gravações do teste ficam na homologação, e isso está autorizado. Use só dados inventados ou os de teste da homologação.
>
> **Onde a Maria grava no Verde**, para saber o que cada caso deixa registrado:
> - **o cadastro de pessoa:** quando o CPF não é encontrado 3 vezes, a Maria pede nome, data de nascimento e endereço. **O registro é criado logo depois do último dado de endereço;**
> - **o encaminhamento de violência doméstica:** **o registro é criado logo depois do "Sim" em "Confirma que seus dados são…?"**.
>
> **Atenção:** essa pergunta de confirmação **só existe quando a conversa começa por um relato livre** (o orquestrador). Se o fluxo da Tykhe abrir violência doméstica **direto**, por um menu e sem relato, a Maria não pede confirmação: **encontrado o CPF, ela cria o encaminhamento em seguida**.

Este guia é para a equipe que vai testar a Maria no ambiente de homologação (o release), depois da troca da versão TypeScript pela versão em Python (2026-10-21, #268).

**Há dois canais, e eles são integrações separadas:**
- **o número de teste da própria Maria no WhatsApp**, que passa pela ponte da Maria (`docs/bridge-whatsapp.md`);
- **a Tykhe**, que tem o próprio canal e chama a API da Maria direto, com um `chatId` atribuído por ela.

Neste guia, "WhatsApp" é o número de teste da Maria, e "Tykhe" é o fluxo da Tykhe.

**O foco do teste é o ambiente, e não a tradução.** Leia a seção 1 antes de começar: ela diz o que já foi conferido e onde vale olhar.

## 1. O que já foi conferido e o que falta

### Já conferido: a lógica dos dois fluxos

Em **20/10**, os fluxos de **violência doméstica** e de **pessoa presa** foram percorridos **até o fim**, nas duas versões (TypeScript e Python), contra o **Verde de homologação**. O teste incluiu consulta de pessoa, CEP, cadastro de pessoa, órgãos de violência doméstica, plantão e encaminhamento. **O resultado foi idêntico nas duas versões**: as mesmas perguntas, os mesmos desfechos e os mesmos dados enviados ao Verde. Os detalhes estão no `MIGRACAO.md`, seção "Teste local contra a homologação do Verde".

Em **21/10**, no próprio release, a classificação e a entrada nos fluxos foram conferidas pela API, nos 4 casos do roteiro. A IA classificou certo.

**Por isso, uma diferença de comportamento entre a Maria antiga e a nova, numa conversa que passou do começo do fluxo, é improvável.** Se algo der errado, a primeira suspeita é o ambiente.

### O que falta: o ambiente do release

Nada disso foi exercitado ainda **no release**:

| O quê | Por que importa | Como aparece para quem testa |
|---|---|---|
| **O token do Verde** no segredo do release | Sem um token válido, toda consulta ao Verde falha | Ver a seção 4: parece um encaminhamento normal |
| **A rede do release até o Verde** | O release nunca consultou o Verde desde a troca de versão (0 chamadas até 21/10) | Igual ao token: a mesma mensagem de encaminhamento |
| **O banco do release com uma conversa no meio de um fluxo** | Cada resposta da pessoa retoma a conversa do ponto em que parou, a partir do banco | A Maria repete uma pergunta, volta ao começo ou diz que não consegue continuar |

**Os dois fluxos estão conferidos no release só até a primeira pergunta:** violência doméstica até "Você é a vítima?", e pessoa presa até a entrada no fluxo. Tudo o que vem depois é o que este teste precisa cobrir.

### O que o deploy confere sozinho (#298)

Depois de cada deploy, o último passo do workflow (`deploy-release.yml`; `deploy-prod.yml` a partir do próximo release para `main`) lê o segredo do ambiente e chama `GET /autenticacao/token/status` no Verde, **só de leitura**. **O deploy termina com falha** se o Verde responder diferente de 200, ou disser que o token está `revogado` ou `expirado`. O log mostra o status HTTP, o `codigo` do Verde e os campos `expirado`, `revogado` e `expiraEm`, **nunca o token**. O código é o `scripts/conferir_token_verde.py`, o mesmo que o `verificar-token-verde.yml` usa para ler o status.

**O que isso cobre:** o token do segredo do release ser aceito pelo Verde, que é a linha "O token do Verde" da tabela acima.

**O que continua sendo teste humano:** a rede **do container** até o Verde (a consulta sai do runner do GitHub, não da Maria), o banco com a conversa no meio de um fluxo, e tudo o que a Tykhe faz com as respostas. Um deploy verde **não** prova que a Maria consegue consultar o Verde.

### Nunca conferido em lugar nenhum

- **Pessoa presa até `concluido`.** Exige um número de processo de origem SEEU de teste no Verde de homologação. Os testes de 20/10 terminaram em encaminhamento para a equipe ("sem número do processo").
- **CPF que já existe na homologação** no caminho de violência doméstica. Falta um CPF de teste já cadastrado.

Se o Ícaro tiver esses dados de teste, estes são os casos de maior valor.

## 2. Antes de começar

Confirme com a Nicole que estes pré-requisitos estão feitos:

- [ ] **O token do Verde válido foi gravado no segredo do release, e o `api-release` recebeu um deploy depois disso** (Ícaro). Sem isso, os fluxos falham na primeira consulta ao Verde, e o teste não diz nada.
- [ ] **A ordem das condições no fluxo da Tykhe foi corrigida** (testar `StatusFluxo` = `redirecionado` antes de `TipoFluxo`). Sem isso, todo caso redirecionado mostra "Falha. Diferente de 200" depois da mensagem certa. É um problema conhecido do fluxo da Tykhe, e não da Maria.
- [ ] **Os dados de teste** (com o Ícaro):
  - um RG de pessoa presa que existe no Verde de homologação;
  - se houver, um número de processo de origem SEEU, e um CPF já cadastrado;
  - CPFs inventados, com dígito verificador válido, para o caminho de cadastro.

- [x] **Confirmado qual Verde o release usa:** o de homologação (verificado em 2026-10-22, #286).

**Use só dados de teste.** O Verde de homologação tem pessoas cadastradas para teste, e nunca uma pessoa real. Os cadastros e encaminhamentos feitos no teste ficam gravados na homologação, e isso está autorizado.

## 3. Os casos

Para cada caso, anote o horário de início e fim (com minutos) e o canal (WhatsApp ou fluxo da Tykhe). **Rode cada caso pelos dois canais, se possível.**

### Caso A. Violência doméstica, pelo Sim, até o encaminhamento (o mais importante)

1. Relato livre de violência doméstica (inventado).
2. "Você é a vítima de violência doméstica?" → **Sim**.
3. Processo → responda **Não** (ou informe um número de teste).
4. Boletim de ocorrência → **Sim** em uma rodada e **Não** em outra.
5. CPF → um **CPF inventado** (não existe na homologação). A Maria pede de novo; depois de 3 tentativas, ela começa o **cadastro**: nome, data de nascimento, CEP, número e complemento.
6. "Confirma que seus dados são…?" → **Sim**.

**Esperado:** uma mensagem de encaminhamento com o **nome de um órgão** e um **número de protocolo**.

Repita com um **CPF que já existe** na homologação, se houver. A Maria deve pedir a confirmação do nome e seguir sem cadastro.

> **Este caso grava duas vezes na homologação:** o cadastro no passo 5 (com CPF inventado) e o encaminhamento no passo 6.

### Caso B. Pessoa presa, até o desfecho

1. Relato livre sobre um familiar preso (inventado).
2. Número do processo → **Sim** e um número de teste (SEEU, se houver), ou **Não**.
3. RG da pessoa presa → o **RG de teste**.
4. "Confirma que é <nome>?" → **Sim**.
5. Parentesco → por exemplo, "sou a mãe".
6. CPF de quem está conversando → um CPF inventado (e o cadastro, como no caso A) ou um já cadastrado.

**Esperado:**
- sem número de processo: "Já confirmei os dados da pessoa presa, mas como você não tem o número do processo, vou encaminhar seu atendimento pra equipe localizar isso e dar continuidade.";
- com um processo SEEU e a situação aceita: "Show! Já confirmei os dados da pessoa presa. Vou seguir com o encaminhamento a partir daqui."

> **Este caso só grava se cair no cadastro** (passo 6 com um CPF que não existe). Pessoa presa não cria encaminhamento no Verde.

### Caso C. A conversa parada no meio

Repita o caso A, mas **pare por 10 a 15 minutos** depois de informar o CPF e só então continue.

**Esperado:** a Maria retoma do ponto exato em que parou, sem repetir perguntas.

Este caso confere o banco do release com uma conversa no meio de um fluxo.

### Caso D. Mensagem depois do fim

Depois de terminar os casos A e B (e o de controle "não sou a vítima"), mande mais uma mensagem na mesma conversa.

**O esperado depende do canal:**

| Canal | Esperado |
|---|---|
| WhatsApp (número de teste da Maria) | **A conversa reabre sozinha, com um atendimento novo.** A ponte esquece a conversa encerrada, e a mensagem seguinte começa do zero, como um relato novo. Isso está no código, mas nunca foi conferido no release |
| Tykhe | **Não sabemos.** A API responde 409 ("atendimento já foi concluído") ou repete o desfecho anterior, conforme a rota que o fluxo da Tykhe chama. O que a Tykhe faz com isso (encerra, mostra o erro, abre um atendimento novo) nunca foi verificado. A documentação da ponte diz que a Tykhe abre um `chatId` novo por conta própria, mas isso também não foi verificado |

**Anote exatamente o que aparece para você em cada canal.** O que a equipe observar responde duas perguntas em aberto:
- **#280:** a API diz "atendimento já foi concluído" também depois de um encaminhamento para atendente humano. O que a pessoa vê na Tykhe?
- **A reabertura pela Tykhe:** a pessoa consegue começar um atendimento novo, ou fica presa na conversa encerrada?

### Casos de controle (rápidos)

| Caso | Esperado |
|---|---|
| Violência doméstica, "Você é a vítima?" → **Não** | "Esse atendimento é destinado apenas para quem é vítima da violência. Vou encaminhar você para um atendente humano." |
| Pedido de pensão alimentícia | Encaminhado à Tykhe: "Entendi. Vou te encaminhar para o atendimento de abertura de um novo caso." |
| Relato vago, entre pessoa presa e violência doméstica | Uma pergunta de esclarecimento, e depois o fluxo certo |

## 4. Como reconhecer uma falha do ambiente

> **"Funcionou" pode significar "falhou em silêncio".** Não é só o token vencido que passa despercebido. Na Maria, uma **falha de infraestrutura vira resposta de negócio**: em vez de um erro, a pessoa recebe uma mensagem que também aparece num caso normal, ou a conversa segue como se a consulta tivesse dado certo. É um padrão do código herdado, registrado na **#239**: **só 2 das 9 chamadas ao Verde** (a de apenado e a de pessoa) distinguem falha de infraestrutura de resposta de negócio, e mesmo essas duas terminam num encaminhamento com mensagem comum. A correção está planejada para depois da migração. **Por isso, um teste que chega ao fim sem mensagem de erro não prova que o Verde respondeu.** Só os logs, pelo horário, dizem isso.

**Quando a consulta ao Verde falha por causa do ambiente** (token, rede ou o Verde fora do ar), **a Maria não mostra um erro.** Ela encaminha a pessoa para atendimento humano com uma mensagem que **também aparece em situações normais**:

| Fluxo | Mensagem | Aparece normalmente quando |
|---|---|---|
| Violência doméstica | "Vou encaminhar seu atendimento para um atendente humano." | a pessoa não confirma os próprios dados |
| Pessoa presa | "Não consegui confirmar os dados da pessoa presa. Vou encaminhar seu atendimento pra equipe verificar com mais calma." | a situação do preso não é atendida, ou a pessoa não confirma os próprios dados |

**Sinal de falha do ambiente:** uma dessas mensagens aparece **logo depois de você informar o CPF ou o RG**, sem antes a Maria dizer que não encontrou nada nem perguntar se você quer tentar de novo. Com o token vencido, é aí que o fluxo para, porque essa é a primeira consulta ao Verde que interrompe a conversa.

**Mais adiante, em violência doméstica:**

| Mensagem | O que pode ser |
|---|---|
| "Não encontrei um órgão disponível pra encaminhar seu caso agora. Por favor, ligue 129…" | Não há órgão para o caso, **ou** a consulta de órgãos falhou por infraestrutura. A Maria hoje não distingue os dois (#239) |
| "…tive um problema técnico ao registrar o encaminhamento…" | Falha ao registrar o encaminhamento. É sempre um problema: registre |
| "Não consegui localizar nem cadastrar seus dados no sistema…" | O cadastro no Verde falhou. É sempre um problema: registre |

**Algumas consultas falham sem aviso nenhum** (#239): a do número do processo, a do CEP e a do plantão. A conversa segue como se nada tivesse acontecido, e só os logs mostram essas falhas.

**Não registre nada disso como "a Maria não achou a pessoa".** Registre com o horário exato. Pelo horário, dá para conferir nos logs se a consulta ao Verde falhou por autenticação ou infraestrutura.

### Durante uma manutenção do Verde

> **Registrado em 2026-10-23 (#308):** a equipe do Verde vai fazer manutenção preventiva, **sem data confirmada**. Durante a manutenção, as consultas ao Verde falham, e a Maria mostra as mesmas mensagens das tabelas acima.

- **Antes de começar uma rodada de teste,** confirme com o Ícaro se há manutenção anunciada para aquele horário.
- **Se o teste cair dentro de uma manutenção anunciada,** não registre como defeito. Anote o horário e "durante a manutenção do Verde", e repita o caso depois que ela terminar.
- **Fora de uma manutenção anunciada,** a falha continua valendo: registre com o horário exato, como acima.
- **Para quem confere nos logs:** manutenção costuma aparecer como erro de serviço (5xx) ou tempo esgotado. **Uma recusa de autenticação (401) não é manutenção**: é o token do Verde, vencido, revogado ou trocado sem o container ter sido reiniciado. Em 2026-10-22 e 23, a falha em produção foi 401 do começo ao fim.

## 5. O que não é defeito novo

Estes comportamentos já são conhecidos e já têm issue. Não precisam ser registrados de novo:

| Comportamento | Issue |
|---|---|
| A pensão vai para "abertura de um novo caso", e não para a orientação de procurar o sindicato | #249 |
| O texto da pergunta de esclarecimento muda de uma vez para outra (é gerado pela IA) | — (esperado) |
| "Falha. Diferente de 200" depois de um encaminhamento à Tykhe | correção no fluxo da Tykhe (seção 2) |
| A mensagem depois do fim diz "concluído" mesmo após o encaminhamento para um atendente | #280 (mas anote o que aparece; ver o caso D) |
| Consultas ao Verde falhando durante uma manutenção anunciada do Verde | — (anote o horário e repita depois; ver a seção 4) |

## 6. Como registrar o resultado

Para cada caso, registre:

- o **caso** (A, B, C, D ou de controle) e o **canal**;
- o **horário** de início e fim, com minutos;
- **até onde a conversa chegou** (a última pergunta respondida) e **o texto exato da última mensagem** da Maria;
- **o que você esperava**, se for diferente.

Não precisa copiar o CPF, o RG nem o nome que aparecer. O horário e o passo bastam para achar a conversa nos logs.

### Os relatos que você escreveu

Em todo caso que começa com um relato livre (A, B, C e os de controle), anote também, **nesta ordem**:

1. **Antes de enviar o relato, para onde você espera que a Maria mande:** violência doméstica, pessoa presa, um assunto da Tykhe (por exemplo, "abertura de um novo caso") ou "acho que ela vai perguntar".
2. **O relato**, exatamente como você escreveu. Sempre inventado: nunca use a história de uma pessoa real.
3. **Depois da resposta, para onde a Maria mandou:** o fluxo, o encaminhamento à Tykhe com o assunto, ou a pergunta de esclarecimento e para onde a conversa foi depois dela.

**Não mude a anotação do passo 1 depois de ver a resposta.** Anotar antes evita que a resposta da Maria influencie o que você esperava. Se mudar de ideia, anote isso à parte.

Não precisa escrever relatos a mais: basta anotar os que você já escreveu para os casos. Essas anotações viram a base de relatos rotulados que a **#256** usa para medir se a Maria classifica certo. A base é montada a partir das suas anotações, e não dos logs.

**Os testes entram no painel de acompanhamento (Visor Maria)** do release como atendimentos normais. Informe as datas e horários do teste a quem acompanha o painel.

## 7. Para quem dá suporte ao teste

Com o horário de um caso, conferir no CloudWatch, no grupo `/ecs/maria-langgraph-pp-release/api`, **só com contagens**:

- `filter evento = 'verde_chamada' | stats count(*) by resultado, tipoErro`: `sucesso` é o esperado; `auth_ou_infra` indica token ou rede;
- `filter level >= 40 | stats count(*) by msg`: avisos e erros no período.

Não é preciso ler o conteúdo das mensagens, e elas não devem ser lidas.
