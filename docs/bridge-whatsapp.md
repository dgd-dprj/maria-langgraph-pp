# Bridge WhatsApp (Meta Cloud API) → orquestrador

Issue #198. Canal alternativo pra testar o orquestrador com um usuário real digitando no WhatsApp, **sem envolver a Tykhe** — são integrações separadas: este bridge fala só com `POST /atendimentos/orquestrador` e `POST /atendimentos/respostas` (via `app.inject`, mesmo processo), nunca com nenhuma rota/contrato específico da Tykhe.

Rota pública (fora do bloco protegido por Bearer de `app.ts` — é a Meta quem chama, não um cliente autenticado nosso):

- `GET /webhook/whatsapp` — verificação do webhook exigida pela Meta na configuração do app (responde `hub.challenge` se `hub.verify_token` bater com `WHATSAPP_VERIFY_TOKEN`, senão 403).
- `POST /webhook/whatsapp` — recebe mensagem de texto do WhatsApp Cloud API.

## Decisão de roteamento (`src/rotas/webhookWhatsapp.ts`)

`chatId` é sempre `whatsapp:${numeroDoRemetente}` — estável por número, mesma ideia do `thread_id` de qualquer outro atendimento.

1. `store.buscarFlowId(chatId)` (mesma tabela de sempre, `shared/atendimentosDb.ts`) já tem um flowId pra esse chatId? → manda a mensagem pra `POST /atendimentos/respostas` (o atendimento já foi identificado, é só continuação normal do fluxo).
2. Sem flowId ainda: checa o **estado do próprio grafo do orquestrador** (`grafoOrquestrador.getState({configurable:{thread_id:"orquestrador:"+chatId}})`, mesma técnica já usada em `POST /atendimentos/respostas` pra saber se tem `interrupt()` pendente) — se tem `next.length > 0`, é resposta a uma pergunta de desambiguação (`{chatId, resposta}`); senão é a 1ª mensagem mesmo (`{chatId, mensagem}`).

Não existe tabela própria de "conversa em andamento" — a decisão inteira deriva de estado que já existe (tabela de atendimentos + checkpoint do LangGraph), sem duplicar bookkeeping.

## Envio da resposta (`src/integracoes/whatsapp.ts`)

`POST {WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages` (Graph API), texto simples — sem botão interativo nessa v1 (`tipo: "opcoes"`/`"sim_nao"` viram texto com as opções listadas embaixo da pergunta). Mesmo padrão de fallback mock dos outros `integracoes/*` (`verde.ts`): sem `WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID`, só loga aviso e não tenta enviar — não quebra o fluxo local.

Nunca loga o texto da mensagem nem o número em claro (CLAUDE.md — dado sensível em texto plano) — só `chatId`, status HTTP e duração.

## Variáveis de ambiente

| Var | O que é |
|---|---|
| `WHATSAPP_API_URL` | Base da Graph API (default `https://graph.facebook.com/v21.0`) |
| `WHATSAPP_PHONE_NUMBER_ID` | Id do número de teste/produção no app da Meta |
| `WHATSAPP_ACCESS_TOKEN` | Token de acesso do app (Meta for Developers → WhatsApp → Configuração da API) |
| `WHATSAPP_VERIFY_TOKEN` | Segredo próprio nosso (não vem da Meta) — configurado igual dos dois lados na hora de cadastrar o webhook no app da Meta |

## Fora de escopo (v1)

- Botões interativos / templates aprovados da Meta.
- Qualquer mudança na integração Tykhe — contrato dela (`docs/contrato-tykhe.md`) permanece intocado.
- Validação de assinatura (`X-Hub-Signature-256`) do payload recebido — pendente, ver observação de segurança na issue #198 se for pra produção de verdade (hoje é só número de teste).
