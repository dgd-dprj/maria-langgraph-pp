# Contrato com a Tykhe

A Tykhe é o único consumidor esperado desta API — chamada servidor-a-servidor, autenticada por Bearer token fixo (`API_KEY`). Rotas em `src/maria/api/atendimentos.py`, `src/maria/api/orquestrador.py` e `src/maria/api/basicas.py` (`GET /fluxos`). Spec completo (OpenAPI) em `GET /docs`.

![Diagrama de sequência do contrato](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/contrato-tykhe.png)

## Descoberta

`GET /fluxos` — lista os `flowId` disponíveis (uuid fixo por fluxo, ver `src/maria/fluxos/__init__.py`). A Tykhe usa isso pra saber qual `flowId` mandar no `POST /atendimentos`.

Um fluxo em teste (`em_teste=True`, #324) só aparece no release (`MARIA_AMBIENTE=release`). Na produção ele não está na lista, e `POST /atendimentos` com o `flowId` dele responde como a um id desconhecido (`404 {"erro":"fluxo não encontrado — ver GET /fluxos"}`). Hoje o único fluxo em teste é o do plano de saúde (NUDECON, #329): a produção lista 2 fluxos, e o release, 3.

## Ciclo de vida de um atendimento

| Rota | Quando usar |
|---|---|
| `POST /atendimentos` | Cria um atendimento novo — `chatId` (atribuído pela Tykhe) + `flowId` obrigatórios. `dadosConhecidos` (opcional) pré-preenche campos que a Tykhe já sabe (ex: `cpf`), pra não perguntar de novo. |
| `POST /atendimentos/orquestrador` | Cria o atendimento a partir de um relato livre e escolhe o fluxo sozinho. 1ª chamada com `mensagem`; continuação da desambiguação com `resposta` (ver "Como distinguir os desfechos do orquestrador"). |
| `GET /atendimentos/:chatId` | Consulta o estado atual, sem avançar nada. `chatId` vai no caminho. |
| `POST /atendimentos/respostas` | Envia uma resposta, avança o fluxo pra próxima pergunta (ou conclui). `chatId` no corpo (não na URL) — o servidor resolve o `flowId` sozinho a partir do `chatId`. |

**Idempotência**: `POST /atendimentos` 2x no mesmo `chatId` nunca reinicia o fluxo — devolve o estado atual (é assim que a Tykhe pode reenviar/reconectar sem medo de apagar o progresso da conversa).

## Shape da resposta (`RespostaAtendimento`)

```jsonc
{
  "resposta": "texto da pergunta atual, ou mensagem final",
  "tipoResposta": "texto" | "sim_nao" | "opcoes" | "link_imagem",
  "opcoes": ["Sim", "Não"],          // só quando tipoResposta:"sim_nao" (ou "opcoes")
  "status": "em_andamento" | "concluido" | "handoff_humano" | "expirado" | "redirecionado",
  "destino": "atendimento_humano" | "agendamento" | "email_enviado" | "sessao_expirada",  // só em atendimento encerrado, opcional
  "flowId": "uuid — diz qual schema esperar em `metadados`",
  "metadados": { /* específico por fluxo — ver docs/fluxo-*.md */ },
  "dadosColetados": { "cpf": "..." },  // cross-fluxo, opcional (plano de saúde p/ outra pessoa: + solicitante e outraPessoa, #448)
  "tokensGastos": { "input": 0, "output": 0, "total": 0 },  // só quando concluido/handoff_humano
  "assuntosPendentes": [{ "nome": "a pessoa presa", "urgente": false, "flowId": "uuid" }],  // só no release, só com outro assunto no relato (#435)
  "_links": {
    "self": { "href": "/atendimentos/<chatId>" },
    "responder": { "href": "/atendimentos/respostas", "method": "POST" }  // só quando em_andamento
  }
}
```

### Regras de leitura pra quem consome

- **`status: "redirecionado"` (issue #225, só em `POST /atendimentos/orquestrador`)**: o relato é de um tipo de caso que a própria Tykhe atende. A Maria **não cria atendimento**; o corpo traz `tipoCaso` (`saude`, `novo-processo`, `andamento-processo`, `agendamentos`, `ajuda-app`, `outros`, `sair`), `resposta` (frase de transição, a Tykhe decide se exibe) e `tokensGastos`. Nunca traz `flowId`, `metadados` nem `_links.responder`. Relato não identificado também cai aqui, com `tipoCaso: "outros"`. Exemplo: `{"resposta":"Entendi. Vou te encaminhar para o atendimento de questões de saúde.","tipoResposta":"texto","status":"redirecionado","tipoCaso":"saude","tokensGastos":{"input":812,"output":64,"total":876},"_links":{"self":{"href":"/atendimentos/abc123"}}}`.
- **`destino` (issue #288, só em atendimento encerrado)**: diz **para onde a pessoa vai**; o `status` diz **que terminou**. `atendimento_humano` acompanha o `handoff_humano` (o `status` e o `metadados.motivoHandoff` continuam como sempre, o `motivoHandoff` é o porquê); `agendamento` vem no fluxo de violência doméstica concluído; `sessao_expirada` acompanha o `expirado`. `email_enviado` (issue #402) vem no plano de saúde concluído no Rio, para a Tykhe saber que os dados **já foram enviados** por e-mail ao departamento (a Maria chama a Lambda da #345 ao concluir e só devolve esse destino depois que a função confirmou o envio, #405; a Tykhe não envia nada). Se o envio falhar, a conversa encerra em `handoff_humano` com `motivoHandoff: falha_envio_email`; se o e-mail saiu mas a função não conseguiu anexar alguma imagem da carteirinha (`anexosFalhos` > 0 na resposta dela, #423), a conversa encerra em `handoff_humano` com `motivoHandoff: imagens_nao_anexadas` (o e-mail com os dados já foi enviado; a equipe pede as imagens); O antigo `unidade_informada` (plano de saúde, fora do Rio) **saiu em 2026-11-06 (#439)**: o fluxo não verifica mais o município nem trabalha com endereço. Fluxo concluído sem destino definido (hoje, pessoa presa) **não traz o campo**. Também vem no corpo do `409` de atendimento encerrado, que repete o estado final. É opcional: a Tykhe pode testar `destino` para escolher o ramo, e o `handoff_humano` continua sendo devolvido.
- **`status` decide o resto do shape**: `em_andamento` sempre tem `tipoResposta`/`opcoes?`/`_links.responder`; `concluido`/`handoff_humano`/`expirado` nunca tem `_links.responder` (não tem mais nada pra responder) e sempre tem `tokensGastos`.
- **`status: "expirado"` (issue #166)**: atendimento parado por mais de `TTL_INATIVIDADE_HORAS` (default 24h) — antes de chegar aqui, a Tykhe recebe uma pergunta `tipoResposta: "sim_nao"` perguntando se a pessoa quer continuar de onde parou. Se ela responder `"false"` (não quer), o atendimento vira `expirado` e o `chatId` fica bloqueado (`409` em qualquer chamada nova nele) — pra continuar, a Tykhe precisa criar um atendimento novo com `chatId` diferente. Se responder `"true"` (quer continuar), a resposta original que ela tinha mandado (a que disparou a pergunta de confirmação) é processada normalmente, sem perdê-la. Issue #227: a confirmação aceita a mesma tolerância das outras perguntas `sim_nao` ("sim"/"não" digitados, sem diferenciar acento ou maiúscula, mais "quero continuar"/"recomeçar"). Uma resposta que não é nem sim nem não **não expira** o atendimento: a pergunta de confirmação volta de novo (`status: "em_andamento"`, `tipoResposta: "sim_nao"`), com a resposta original ainda guardada.
- **Plano de saúde sem verificação de município (issue #439)**: o fluxo começa direto em "O atendimento é para você?" (`sim_nao`), com qualquer `dadosConhecidos`. A Maria **não verifica mais o município** (sem `GET /cep`, sem regra do Rio): o CEP deixou de ser exigido, e a Tykhe pode mandar o fluxo de qualquer município. O endereço continua vindo da Tykhe em `dadosConhecidos.endereco` (de quem fala) e aparece no resumo e no e-mail ao NUDECON; ausente, aparece como "não informado", sem encerrar. Para outra pessoa, o endereço é o do cadastro do Verde. Saíram os motivos `municipio_nao_identificado` e `fora_do_rio` e o destino `unidade_informada`.
- **Atendimento para outra pessoa (plano de saúde, issue #433, fase 1 da #347)**: a resposta "não" (`false`) a "O atendimento é para você?" deixa de encerrar. A Maria pergunta **"Qual o CPF da pessoa que será atendida?"** (`tipoResposta: texto`; aceita com ou sem pontuação), consulta o Verde (`GET /integra/pessoa?cpf=`) e segue o fluxo normal (imagens, situação, renda, resumo, confirmação e e-mail ao NUDECON), com os dados **dela**, do cadastro do Verde, no resumo e no e-mail no lugar dos de quem pede (campo que o Verde não trouxe aparece como "não informado"). **Desde a #444**, o e-mail ao NUDECON também leva quem pediu, nas linhas "Solicitante - Nome" e "Solicitante - CPF" (de `dadosConhecidos`; ausente vira "não informado", sem encerrar); o resumo mostrado a quem pede não muda, e para quem fala por si nada muda. O que o Verde devolve decide o caminho (#446): **200** usa os dados dele; **404** (sem cadastro) faz a Maria **pedir os dados dela na conversa**, um por vez, sem repetir a pergunta do CPF; **400** ("CPF inválido") repete a pergunta do CPF; **422** (mais de uma pessoa), 401/403/5xx e falha de rede vão à equipe, sem coletar. A coleta pergunta, nesta ordem: nome completo, data de nascimento (dd/mm/aaaa), estado civil (`tipoResposta: opcoes`: Solteiro(a), Casado(a), União estável, Divorciado(a), Viúvo(a), Separado(a)), profissão, RG (opcional: "não tenho"), endereço (CEP primeiro, pelo subgrafo `coletar_endereco`, **sem verificar o município**), telefone com DDD, WhatsApp ("mesmo" usa o telefone; "não tenho" pula), e-mail (opcional) e o parentesco com quem fala (`opcoes`, lista de pessoa presa). Os dados informados entram no resumo e no e-mail, com "Atendimento para: outra pessoa (dados informados, sem cadastro no Verde)" e a linha "Parentesco com quem pediu"; a pessoa **não** é cadastrada no Verde. Cada campo aceita até 3 respostas inválidas. Falhas vão para `handoff_humano` com `destino: atendimento_humano` e `metadados.motivoHandoff`: `cpf_outra_pessoa_invalido` (formato inválido, ou 400 do Verde, 3 vezes), `dados_outra_pessoa_invalidos` (3 respostas inválidas no mesmo campo da coleta) e `falha_infra_verde` (Verde fora do ar ou com mais de uma pessoa; sem repetir). **Os motivos `outra_pessoa` e `cpf_outra_pessoa_nao_encontrado` deixaram de existir.** Os dados da outra pessoa (do Verde ou informados) e os do solicitante voltam em `dadosColetados` (#448, veja abaixo), e **nunca** em `metadados` nem em log.
- **Vários assuntos no mesmo relato (multi-fluxo, fase 1a, issue #435, só no release)**: quando o relato traz mais de um assunto ("meu irmão tá preso e o plano negou a cirurgia da minha mãe"), o orquestrador:
  1. **Propõe a ordem e pergunta "Pode ser assim?"**, no mesmo formato da desambiguação: `status: "em_andamento"`, **sem `flowId`**, `_links.responder.href` = `/atendimentos/orquestrador`. A diferença é `tipoResposta: "sim_nao"` com `opcoes: ["Sim", "Não"]`, para montar os botões. A resposta da pessoa volta como `{ chatId, resposta }` na mesma rota; vale `"true"`/`"false"` ou o texto dela ("pode", "não", "o do meu filho"). A ordem padrão é saúde, violência doméstica, pessoa presa e depois o resto, com o urgente antes.
  2. **Com "Não" e três assuntos ou mais,** pergunta "Qual você quer resolver primeiro?" (`tipoResposta: "texto"`, também sem `flowId`). A resposta que a Maria não entende segue a ordem proposta, sem perguntar de novo.
  3. **Atende só o primeiro assunto**, como hoje: abre o fluxo da Maria (a 1ª pergunta vem com "Combinado. Vamos começar pela …" antes) ou redireciona com `tipoCaso`. O fluxo aberto recebe como relato só o trecho do relato sobre o assunto dele.
  4. **Lista os outros em `assuntosPendentes`**, na resposta que abre o fluxo ou redireciona, e de novo na resposta final do fluxo (`concluido` ou `handoff_humano`). Cada item tem `nome` (o nome simples usado nas mensagens), `urgente` e `flowId` (assunto de um fluxo da Maria) **ou** `tipoCaso` (assunto da Tykhe). O trecho do relato não vai no campo.

  5. **Guarda o que a pessoa já disse (issue #442).**
     - Cada item de um fluxo da Maria pode trazer `dadosConhecidos`: o que o trecho daquele assunto já diz (por exemplo, `parentesco: "Tio(a)"` para "meu sobrinho foi preso") e, na resposta final do 1º assunto, o `cpf` informado nele.
     - **Ao abrir o próximo assunto, a Tykhe repassa esse objeto em `dadosConhecidos`** (`POST /atendimentos` com o `flowId` do item e um `chatId` novo), e o fluxo não pergunta de novo o que já sabe.
     - Nunca vai o texto do relato.
  6. **Os `dadosConhecidos` da 1ª chamada ficam guardados (issue #442).** A resposta à pergunta da ordem ou à desambiguação pode voltar só com `{ chatId, resposta }`: o fluxo aberto depois usa os dados da 1ª chamada. Se a Tykhe mandar de novo, valem os dela. Isso vale também na produção, para a desambiguação.

  **É só acréscimo:** a Tykhe que ignora `assuntosPendentes` atende o primeiro assunto, como hoje, e o campo não aparece quando o relato tem um assunto só, nem na produção. **A combinar com a Tykhe:** mostrar os botões na pergunta da ordem e, no fim do primeiro assunto, seguir com o próximo da lista (`flowId`: `POST /atendimentos` com um `chatId` novo; `tipoCaso`: o fluxo da Tykhe).
- **`tipoResposta: "link_imagem"` (issue #398, só no fluxo Problemas com plano de saúde)**: a pergunta pede **uma imagem**; o campo `tipoImagem` diz qual (`carteirinha_frente`, depois `carteirinha_verso`; lista provisória até a #335). A Tykhe pede a foto à pessoa e responde em `resposta` com a **URL de baixar** a imagem: `https://downloads.tykhe.dev/arquivos/<idDoArquivo>?token=<tokenDoArquivo>` (só `https` e só esse host, sem usuário nem senha na URL). Resposta que não é uma URL assim repete a pergunta; na 3ª tentativa o atendimento encerra em `handoff_humano` com `motivoHandoff: imagens_pendentes`. `imagensRecebidas: true` em `dadosConhecidos` pula as perguntas. Na resposta `concluido`, `dadosColetados.imagens` traz `carteirinhaFrente` e `carteirinhaVerso` (as URLs), (a Maria já as usa para chamar a função de e-mail do NUDECON, #405; a Tykhe **não** precisa repassá-las). **Os links são segredo** (o token vai na URL): a Maria nunca os grava em log nem em `metadados`.
- **Como montar o fim do fluxo e as imagens na Tykhe (issue #402, fluxo 71; desde a #430 a 1ª pergunta do plano de saúde é "o atendimento é para você?", `sim_nao`, sem a pergunta do canal)**:
  1. **Fim da conversa:** decidir por `status` (`concluido`, `handoff_humano`, `expirado`) e usar `destino` só para escolher o ramo (`email_enviado`: só mostrar a `mensagemFinal` e encerrar, sem chamar a Lambda). Fluxo concluído sem `destino` (por exemplo, a pessoa presa) também é fim: testar só "`destino` existe" o deixa esperando uma entrada que daria 409.
  2. **Valor de `{{Imagem-1}}`:** a Maria só aceita em `resposta` a **URL de baixar** (`https://downloads.tykhe.dev/arquivos/<id>?token=<token>`). O nó de entrada do tipo arquivo da Tykhe precisa guardar essa URL, e não o nome nem o texto do arquivo. **A conferir no teste com a Tykhe** (resposta fora desse formato repete a pergunta e, na 3ª vez, vai para `handoff_humano`).
  3. **`resposta` vazia:** o `POST /atendimentos/<chatId>/resposta` com `resposta` vazia devolve `400 resposta obrigatório`. O fluxo deve tratar esse erro (caminho de erro do nó de API para o atendimento humano) e não reenviar o vazio.
  4. **Guardar `tipoImagem` e as URLs:** `tipoImagem` vem em cada pergunta `link_imagem` (use para dizer qual foto pedir). Na resposta `concluido`, não é preciso guardar nem repassar `dadosColetados.imagens`: desde a #405 quem chama a Lambda é a Maria. Se guardar, não registrar as URLs em log (o token vai na URL).
- **`tipoResposta: "sim_nao"`**: a resposta esperada é literalmente `"true"`/`"false"` (não `"Sim"`/`"Não"` em texto — embora o backend tolere isso também: "sim"/"s"/"não"/"n" sem diferenciar acento ou maiúscula, regra única em `src/maria/shared/respostas.py`). `opcoes` sempre vem `["Sim", "Não"]` nesse caso, útil pra montar botões.
- **`metadados` muda de shape por `flowId`** — sempre presente (mesmo vazio `{}` na 1ª pergunta), mas os campos dependem de qual fluxo. Ver `docs/fluxo-pessoa-presa.md` / `docs/fluxo-violencia-domestica.md`, ou o schema exato em `src/maria/fluxos/<fluxo>/api.py`.
- **`resposta` no `concluido`/`handoff_humano`** é a mensagem final pro usuário — pode variar por motivo de handoff (alguns fluxos customizam por desfecho, `mensagemFinal` no state).
- **HTTP status sempre 200** nas respostas de sucesso (mesmo criando um atendimento novo — decisão deliberada: "201 correto" foi trocado por "200 sempre" a pedido explícito da Tykhe, evita trabalho extra do lado deles). Erros reais: `400` (faltou campo obrigatório), `404` (fluxo ou atendimento não existe), `409` (chatId já usado por outro flowId, ou atendimento já concluído sem nada pendente).

### Como distinguir os desfechos do orquestrador

`status` sozinho não basta: o fluxo identificado e a pergunta de desambiguação vêm os dois com `status: "em_andamento"`. Conferido com respostas reais no teste com a Tykhe (2026-10-19):

| Desfecho | `status` | Como reconhecer | O que fazer |
|---|---|---|---|
| Redirecionado | `redirecionado` | traz `tipoCaso`; sem `flowId` | encaminhar pelo `tipoCaso` |
| Desambiguação | `em_andamento` | **sem `flowId`**; `_links.responder.href` = `/atendimentos/orquestrador` | mostrar `resposta` e mandar o texto da pessoa como `{ chatId, resposta }` na mesma rota |
| Ordem dos assuntos (#435, só no release) | `em_andamento` | igual à desambiguação, com `tipoResposta: "sim_nao"` e `opcoes` | igual à desambiguação; com os botões, mandar `"true"`/`"false"` |
| Fluxo da Maria identificado | `em_andamento` | **com `flowId`**; `_links.responder.href` = `/atendimentos/respostas` | mostrar `resposta` (a 1ª pergunta do fluxo); as respostas seguintes vão para `POST /atendimentos/respostas` |

Raro: `status: "handoff_humano"` com `motivoHandoff: "nao_identificado"`, só numa inconsistência interna do catálogo.

### Campos do corpo das requisições

Mesma informação do `GET /docs`. "Obrigatório" vale para a Tykhe; a API responde 400 sem o campo.

| Rota | Campo | Obrigatório | Descrição |
|---|---|---|---|
| `POST /atendimentos/orquestrador` | `chatId` | sim (dispensado só com `APP_ENV=test`) | Mesmo valor em todas as rodadas |
| | `mensagem` | um dos dois | Relato livre, na 1ª chamada |
| | `resposta` | um dos dois | Resposta à desambiguação; não pode ser vazia |
| | `dadosConhecidos` | não | Objeto com o que a Tykhe já sabe (hoje só `cpf`); repassado ao fluxo identificado |
| `POST /atendimentos` | `flowId` | sim | Id do fluxo (`GET /fluxos`) |
| | `chatId` | sim (dispensado só com `APP_ENV=test`) | |
| | `dadosConhecidos` | não | Igual ao do orquestrador |
| `POST /atendimentos/respostas` | `chatId` | sim | O servidor resolve o fluxo a partir dele |
| | `resposta` | sim | `"true"`/`"false"` para `sim_nao`; texto livre nas demais |
| `GET /atendimentos/:chatId` | `chatId` (caminho) | sim | Até 100 caracteres; acima, 414 |

`dadosColetados` é só de saída: traz o `cpf` quando existe, apenas na resposta do fluxo da Maria identificado (nunca no `redirecionado` nem na desambiguação). **No plano de saúde para outra pessoa (#448)** traz também `solicitante` (`nome`, `cpf`: quem está falando, o de `dadosConhecidos`) e `outraPessoa` (`cpf`, `nome`, `dataNascimento`, `endereco`, `telefone`, `whatsapp`, `email`, `estadoCivil`, `profissao`, `rg`, `parentesco` e `origem`: `verde` ou `informado`; campo vazio não aparece), em toda resposta a partir do momento em que o dado existe. O `cpf` de cima continua o de quem fala: guarde cada bloco numa variável própria e nunca grave o CPF digitado como o da pessoa atendida na variável que alimenta `dadosConhecidos.cpf`. Para quem fala por si, nada muda. **Privacidade:** o dado de terceiro volta na resposta da API, no mesmo canal de onde vem o cadastro do solicitante; a Maria não o grava em log nem em `metadados`. Rotas protegidas respondem 401 (`{"error": "missing authorization header"}` ou `"invalid authorization header"`) sem o Bearer correto.

### `chatId`

Texto não vazio, sem formato fixo. Na prática: **até 100 caracteres** (acima disso, o `GET /atendimentos/<chatId>` responde 414) e **sem `/`, `?`, `#` nem espaço**, porque o `chatId` vai no caminho da consulta e nos `_links`. Um `chatId` por conversa; o mesmo `chatId` em todas as rodadas da conversa. Fora de `APP_ENV=test`, é obrigatório (400 sem ele).

## O que NÃO é exposto pra Tykhe

- Texto real da conversa não fica em log nenhum acessível externamente (ver `docs/arquitetura.md`, seção Observabilidade) — só o que está no `metadados`/`resposta` da própria resposta HTTP.
- Detalhes de erro/infra do Verde (401, 5xx) nunca vazam pro contrato com a Tykhe — sempre virou uma pergunta de retry ou um `handoff_humano` com motivo de negócio, nunca um erro técnico bruto.
