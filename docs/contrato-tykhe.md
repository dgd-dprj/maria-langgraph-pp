# Contrato com a Tykhe

A Tykhe é o único consumidor esperado desta API — chamada servidor-a-servidor, autenticada por Bearer token fixo (`API_KEY`). Endpoints em `src/rotas/atendimentos.ts` e `src/rotas/fluxos.ts`. Spec completo (OpenAPI) em `GET /docs`.

![Diagrama de sequência do contrato](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/contrato-tykhe.png)

## Descoberta

`GET /fluxos` — lista os `flowId` disponíveis (uuid fixo por fluxo, ver `src/fluxos/index.ts`). A Tykhe usa isso pra saber qual `flowId` mandar no `POST /atendimentos`.

## Ciclo de vida de um atendimento

| Rota | Quando usar |
|---|---|
| `POST /atendimentos` | Cria um atendimento novo — `chatId` (atribuído pela Tykhe) + `flowId` obrigatórios. `dadosConhecidos` (opcional) pré-preenche campos que a Tykhe já sabe (ex: `cpf`), pra não perguntar de novo. |
| `GET /atendimentos/:chatId` | Consulta o estado atual, sem avançar nada. |
| `POST /atendimentos/respostas` | Envia uma resposta, avança o fluxo pra próxima pergunta (ou conclui). `chatId` no corpo (não na URL) — o servidor resolve o `flowId` sozinho a partir do `chatId`. |

**Idempotência**: `POST /atendimentos` 2x no mesmo `chatId` nunca reinicia o fluxo — devolve o estado atual (é assim que a Tykhe pode reenviar/reconectar sem medo de apagar o progresso da conversa).

## Shape da resposta (`RespostaAtendimento`)

```jsonc
{
  "resposta": "texto da pergunta atual, ou mensagem final",
  "tipoResposta": "texto" | "sim_nao" | "opcoes",
  "opcoes": ["Sim", "Não"],          // só quando tipoResposta:"sim_nao" (ou "opcoes")
  "status": "em_andamento" | "concluido" | "handoff_humano" | "expirado",
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

- **`status` decide o resto do shape**: `em_andamento` sempre tem `tipoResposta`/`opcoes?`/`_links.responder`; `concluido`/`handoff_humano`/`expirado` nunca tem `_links.responder` (não tem mais nada pra responder) e sempre tem `tokensGastos`.
- **`status: "expirado"` (issue #166)**: atendimento parado por mais de `TTL_INATIVIDADE_HORAS` (default 24h) — antes de chegar aqui, a Tykhe recebe uma pergunta `tipoResposta: "sim_nao"` perguntando se a pessoa quer continuar de onde parou. Se ela responder `"false"` (não quer), o atendimento vira `expirado` e o `chatId` fica bloqueado (`409` em qualquer chamada nova nele) — pra continuar, a Tykhe precisa criar um atendimento novo com `chatId` diferente. Se responder `"true"` (quer continuar), a resposta original que ela tinha mandado (a que disparou a pergunta de confirmação) é processada normalmente, sem perdê-la.
- **`tipoResposta: "sim_nao"`**: a resposta esperada é literalmente `"true"`/`"false"` (não `"Sim"`/`"Não"` em texto — embora o backend tolere isso também, ver "tolerâncias" nos docs de cada fluxo). `opcoes` sempre vem `["Sim", "Não"]` nesse caso, útil pra montar botões.
- **`metadados` muda de shape por `flowId`** — sempre presente (mesmo vazio `{}` na 1ª pergunta), mas os campos dependem de qual fluxo. Ver `docs/fluxo-pessoa-presa.md` / `docs/fluxo-violencia-domestica.md`, ou o schema exato em `src/fluxos/*/api.ts`.
- **`resposta` no `concluido`/`handoff_humano`** é a mensagem final pro usuário — pode variar por motivo de handoff (alguns fluxos customizam por desfecho, `mensagemFinal` no state).
- **HTTP status sempre 200** nas respostas de sucesso (mesmo criando um atendimento novo — decisão deliberada: "201 correto" foi trocado por "200 sempre" a pedido explícito da Tykhe, evita trabalho extra do lado deles). Erros reais: `400` (faltou campo obrigatório), `404` (fluxo ou atendimento não existe), `409` (chatId já usado por outro flowId, ou atendimento já concluído sem nada pendente).

## O que NÃO é exposto pra Tykhe

- Texto real da conversa não fica em log nenhum acessível externamente (ver `docs/arquitetura.md`, seção Observabilidade) — só o que está no `metadados`/`resposta` da própria resposta HTTP.
- Detalhes de erro/infra do Verde (401, 5xx) nunca vazam pro contrato com a Tykhe — sempre virou uma pergunta de retry ou um `handoff_humano` com motivo de negócio, nunca um erro técnico bruto.
