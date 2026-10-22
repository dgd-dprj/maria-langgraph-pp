# Contrato com a Tykhe

A Tykhe é o único consumidor esperado desta API — chamada servidor-a-servidor, autenticada por Bearer token fixo (`API_KEY`). Rotas em `src/maria/api/atendimentos.py`, `src/maria/api/orquestrador.py` e `src/maria/api/basicas.py` (`GET /fluxos`). Spec completo (OpenAPI) em `GET /docs`.

![Diagrama de sequência do contrato](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/contrato-tykhe.png)

## Descoberta

`GET /fluxos` — lista os `flowId` disponíveis (uuid fixo por fluxo, ver `src/maria/fluxos/__init__.py`). A Tykhe usa isso pra saber qual `flowId` mandar no `POST /atendimentos`.

## Ciclo de vida de um atendimento

| Rota | Quando usar |
|---|---|
| `POST /atendimentos` | Cria um atendimento novo — `chatId` (atribuído pela Tykhe) + `flowId` obrigatórios. `dadosConhecidos` (opcional) pré-preenche campos que a Tykhe já sabe (ex: `cpf`), pra não perguntar de novo. |
| `GET /atendimentos/:chatId` | Consulta o estado atual, sem avançar nada. |
| `POST /atendimentos/respostas` | Envia uma resposta, avança o fluxo pra próxima pergunta (ou conclui). `chatId` no corpo (não na URL) — o servidor resolve o `flowId` sozinho a partir do `chatId`. |
| `POST /atendimentos/orquestrador` | Quando a Tykhe não sabe o `flowId`: manda o relato livre (`mensagem`) e a Maria identifica o fluxo e cria o atendimento, redireciona para um tipo que a Tykhe atende, ou faz perguntas de desambiguação (a pessoa responde na mesma rota, em `resposta`). Ver "Como distinguir os desfechos do orquestrador". |

## Campos das requisições

Obrigatório = sem ele a API responde 400. O formato do `chatId` está na seção `chatId`, mais abaixo.

### `POST /atendimentos`

| Campo | Obrigatório | Descrição |
|---|---|---|
| `chatId` | sim | Identificador da conversa, atribuído pela Tykhe. |
| `flowId` | sim | uuid do fluxo (ver `GET /fluxos`). Fluxo inexistente dá 404. |
| `dadosConhecidos` | não | Objeto com o que a Tykhe já sabe (ex: `cpf`), pra não perguntar de novo. |

### `POST /atendimentos/orquestrador`

| Campo | Obrigatório | Descrição |
|---|---|---|
| `chatId` | sim | O mesmo `chatId` em todas as rodadas da conversa. |
| `mensagem` | na 1ª chamada | Relato livre da pessoa. |
| `resposta` | nas chamadas seguintes | Resposta à pergunta de desambiguação, no lugar de `mensagem`. Texto não vazio: vazio dá 400. |
| `dadosConhecidos` | não | Como no `POST /atendimentos`. Só vale se o relato levar a um fluxo da Maria (vai para o atendimento criado); nos redirecionamentos e na desambiguação não tem efeito. |

Sem `mensagem` e sem `resposta`, a API responde 400.

### `GET /atendimentos/:chatId`

| Parâmetro | Onde | Obrigatório | Descrição |
|---|---|---|---|
| `chatId` | caminho | sim | O `chatId` do atendimento. Sem corpo. Atendimento inexistente dá 404. |

### `POST /atendimentos/respostas`

| Campo | Obrigatório | Descrição |
|---|---|---|
| `chatId` | sim | O `chatId` do atendimento. |
| `resposta` | sim | `"true"`/`"false"` pra `sim_nao`, texto livre pras demais. |

### `dadosConhecidos` (requisição) e `dadosColetados` (resposta)

`dadosConhecidos` é o que a Tykhe **manda**; `dadosColetados` é o que a Maria **devolve**. O `dadosColetados` só vem na resposta de um fluxo da Maria identificado, e pode vir vazio (`{}`); não vem nos redirecionamentos nem nas perguntas de desambiguação do orquestrador.

**Idempotência**: `POST /atendimentos` 2x no mesmo `chatId` nunca reinicia o fluxo — devolve o estado atual (é assim que a Tykhe pode reenviar/reconectar sem medo de apagar o progresso da conversa).

## Shape da resposta (`RespostaAtendimento`)

```jsonc
{
  "resposta": "texto da pergunta atual, ou mensagem final",
  "tipoResposta": "texto" | "sim_nao" | "opcoes",
  "opcoes": ["Sim", "Não"],          // só quando tipoResposta:"sim_nao" (ou "opcoes")
  "status": "em_andamento" | "concluido" | "handoff_humano" | "expirado" | "redirecionado",
  "flowId": "uuid — diz qual schema esperar em `metadados`",
  "metadados": { /* específico por fluxo — ver docs/fluxo-*.md */ },
  "dadosColetados": { "cpf": "..." },  // cross-fluxo, opcional
  "tokensGastos": { "input": 0, "output": 0, "total": 0 },  // só quando concluido/handoff_humano
  "_links": {
    "self": { "href": "/atendimentos/<chatId>" },
    "responder": { "href": "/atendimentos/respostas", "method": "POST" }  // só quando em_andamento
  }
}
```

### Regras de leitura pra quem consome

- **`status: "redirecionado"` (issue #225, só em `POST /atendimentos/orquestrador`)**: o relato é de um tipo de caso que a própria Tykhe atende. A Maria **não cria atendimento**; o corpo traz `tipoCaso` (`saude`, `novo-processo`, `andamento-processo`, `agendamentos`, `ajuda-app`, `outros`, `sair`), `resposta` (frase de transição, a Tykhe decide se exibe) e `tokensGastos`. Nunca traz `flowId`, `metadados` nem `_links.responder`. Relato não identificado também cai aqui, com `tipoCaso: "outros"`. Exemplo: `{"resposta":"Entendi. Vou te encaminhar para o atendimento de questões de saúde.","tipoResposta":"texto","status":"redirecionado","tipoCaso":"saude","tokensGastos":{"input":812,"output":64,"total":876},"_links":{"self":{"href":"/atendimentos/abc123"}}}`.
- **`status` decide o resto do shape**: `em_andamento` sempre tem `tipoResposta`/`opcoes?`/`_links.responder`; `concluido`/`handoff_humano`/`expirado` nunca tem `_links.responder` (não tem mais nada pra responder) e sempre tem `tokensGastos`.
- **`status: "expirado"` (issue #166)**: atendimento parado por mais de `TTL_INATIVIDADE_HORAS` (default 24h) — antes de chegar aqui, a Tykhe recebe uma pergunta `tipoResposta: "sim_nao"` perguntando se a pessoa quer continuar de onde parou. Se ela responder `"false"` (não quer), o atendimento vira `expirado` e o `chatId` fica bloqueado (`409` em qualquer chamada nova nele) — pra continuar, a Tykhe precisa criar um atendimento novo com `chatId` diferente. Se responder `"true"` (quer continuar), a resposta original que ela tinha mandado (a que disparou a pergunta de confirmação) é processada normalmente, sem perdê-la. Issue #227: a confirmação aceita a mesma tolerância das outras perguntas `sim_nao` ("sim"/"não" digitados, sem diferenciar acento ou maiúscula, mais "quero continuar"/"recomeçar"). Uma resposta que não é nem sim nem não **não expira** o atendimento: a pergunta de confirmação volta de novo (`status: "em_andamento"`, `tipoResposta: "sim_nao"`), com a resposta original ainda guardada.
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
| Fluxo da Maria identificado | `em_andamento` | **com `flowId`**; `_links.responder.href` = `/atendimentos/respostas` | mostrar `resposta` (a 1ª pergunta do fluxo); as respostas seguintes vão para `POST /atendimentos/respostas` |

Raro: `status: "handoff_humano"` com `motivoHandoff: "nao_identificado"`, só numa inconsistência interna do catálogo.

### `chatId`

Texto não vazio, sem formato fixo. Na prática: **até 100 caracteres** (acima disso, o `GET /atendimentos/<chatId>` responde 414) e **sem `/`, `?`, `#` nem espaço**, porque o `chatId` vai no caminho da consulta e nos `_links`. Um `chatId` por conversa; o mesmo `chatId` em todas as rodadas da conversa. Fora de `APP_ENV=test`, é obrigatório (400 sem ele).

## O que NÃO é exposto pra Tykhe

- Texto real da conversa não fica em log nenhum acessível externamente (ver `docs/arquitetura.md`, seção Observabilidade) — só o que está no `metadados`/`resposta` da própria resposta HTTP.
- Detalhes de erro/infra do Verde (401, 5xx) nunca vazam pro contrato com a Tykhe — sempre virou uma pergunta de retry ou um `handoff_humano` com motivo de negócio, nunca um erro técnico bruto.
