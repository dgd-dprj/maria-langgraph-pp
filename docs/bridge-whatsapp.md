# Bridge WhatsApp (Meta Cloud API) → orquestrador

Issue #198. Canal alternativo pra testar o orquestrador com um usuário real digitando no WhatsApp, **sem envolver a Tykhe** — são integrações separadas: este bridge fala só com `POST /atendimentos/orquestrador` e `POST /atendimentos/respostas` (via `app.inject`, mesmo processo), nunca com nenhuma rota/contrato específico da Tykhe.

Rota pública (fora do bloco protegido por Bearer de `app.ts` — é a Meta quem chama, não um cliente autenticado nosso):

- `GET /webhook/whatsapp` — verificação do webhook exigida pela Meta na configuração do app (responde `hub.challenge` se `hub.verify_token` bater com `WHATSAPP_VERIFY_TOKEN`, senão 403).
- `POST /webhook/whatsapp` — recebe mensagem de texto do WhatsApp Cloud API.

## Decisão de roteamento (`src/rotas/webhookWhatsapp.ts`)

`chatId` é `whatsapp:${numero}:${timestampDaConversa}` — não é fixo por número pra sempre (ver "Achados do code review" abaixo). Um `Map` em memória (`conversasAtivas`) guarda qual chatId está aberto pra cada número.

1. `store.buscarFlowId(chatId)` (mesma tabela de sempre, `shared/atendimentosDb.ts`) já tem um flowId pra esse chatId? → manda a mensagem pra `POST /atendimentos/respostas` (o atendimento já foi identificado, é só continuação normal do fluxo).
2. Sem flowId ainda: checa o **estado do próprio grafo do orquestrador** (`grafoOrquestrador.getState({configurable:{thread_id:"orquestrador:"+chatId}})`, mesma técnica já usada em `POST /atendimentos/respostas` pra saber se tem `interrupt()` pendente) — se tem `next.length > 0`, é resposta a uma pergunta de desambiguação (`{chatId, resposta}`); senão é a 1ª mensagem mesmo (`{chatId, mensagem}`).

Não existe tabela própria de "atendimento em andamento" — essa decisão deriva de estado que já existe (tabela de atendimentos + checkpoint do LangGraph). O que É bookkeeping próprio do bridge é só "qual é a conversa ATUAL desse número" (ver abaixo).

Processamento por número é serializado (fila em memória, `filaPorNumero`) — evita 2 mensagens quase simultâneas do mesmo número (retry de webhook da própria Meta, ou 2 mensagens em sequência rápida) invocarem o grafo do orquestrador em dobro e mandarem resposta duplicada.

## Achados do code review da #198 (aplicados)

- **chatId fixo travava o número pra sempre**: `POST /atendimentos/respostas` devolve 409 pra sempre em atendimento já `concluido`/`handoff_humano`/`expirado` (`rotas/atendimentos.ts`), sem caminho de recuperação — a Tykhe contorna isso abrindo um `chatId` novo por conta própria, o bridge precisava da mesma coisa. `conversasAtivas` invalida a conversa atual assim que ela conclui/faz handoff (ou em qualquer erro) — próxima mensagem do número abre atendimento novo automaticamente. Em memória de propósito (reset no restart do processo é aceitável: só significa "próxima mensagem começa do zero").
- **`chatId` carrega o número em claro**: diferente do `chatId` da Tykhe (opaco, atribuído por ela), aqui `chatId` contém o telefone — e `chatId` é logado em toda parte como padrão de correlação (CLAUDE.md). Aceito por ora porque é só 1 número de teste conhecido; se este bridge sair do escopo "número de teste", vale trocar por um hash não reversível do número.

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
