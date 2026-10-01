import { randomUUID } from "node:crypto";
import Fastify from "fastify";
import fastifySwagger from "@fastify/swagger";
import fastifySwaggerUi from "@fastify/swagger-ui";
import fastifyBearerAuth from "@fastify/bearer-auth";
import { registrarRotasAtendimento } from "./rotas/atendimentos.js";
import { registrarRotaFluxos } from "./rotas/fluxos.js";
import { registrarRotaOrquestrador } from "./rotas/orquestrador.js";
import { registrarRotaWebhookWhatsapp } from "./rotas/webhookWhatsapp.js";
import { logger } from "./shared/logger.js";
import { obterAtendimentosStore } from "./shared/atendimentosDb.js";
import { obterPerguntasStore } from "./shared/perguntasDb.js";
import { listarFluxosPlanejados } from "./shared/fluxosPlanejadosDb.js";

// Monta o Fastify sem chamar listen() — assim os testes usam app.inject()
// direto, sem precisar subir servidor de verdade numa porta. Quem quer
// rodar de verdade importa daqui e chama listen() (ver server.ts).
export async function montarApp() {
  // loggerInstance (não logger:true) — usa a MESMA instância pino de
  // shared/logger.ts, compartilhada com módulos que não têm req.log
  // (ia/, integracoes/, shared/checkpointer.ts — ver contexto.ts). Cada
  // linha sai em JSON, com `reqId` gerado automático (correlação por
  // REQUISIÇÃO — trocado pra UUID em vez do padrão sequencial "req-1"/
  // "req-2", que reseta a cada restart do processo e pode colidir/confundir
  // em logs agregados de múltiplas instâncias). Como uma conversa é várias
  // requisições separadas no tempo, incluímos `chatId` manualmente em todo
  // log — é ele que correlaciona TODAS as chamadas de uma mesma conversa
  // entre si (reqId sozinho não faz isso, é só por requisição individual).
  const app = Fastify({ loggerInstance: logger, genReqId: () => randomUUID() });

  // Issue #114 — migração de schema explícita no startup, mesmo racional
  // do checkpointer (shared/checkpointer.ts, já bloqueia via top-level
  // await no compile de cada fluxo): sem isso, CREATE/ALTER TABLE só
  // rodava na 1ª request de negócio que tocasse cada store (lazy),
  // deixando o deploy "saudável" (ECS/ALB healthy) MUITO antes do schema
  // estar pronto de verdade — achado ao vivo 2026-09-18/21, precisou forçar
  // manualmente via ecs run-task depois de 2 deploys. Health check só some
  // OK depois que isso terminar (listen() só roda depois de montarApp()
  // resolver, ver server.ts).
  await obterAtendimentosStore();
  const perguntasStore = await obterPerguntasStore();
  await perguntasStore.listarPerguntasPorFlow("00000000-0000-0000-0000-000000000000");
  await listarFluxosPlanejados();

  // Code-first (gera o spec a partir do schema de cada rota, não de um yaml
  // mantido à mão) — repo pequeno/experimental, sem o guard de CI que o back
  // principal tem (test/openapi.test.ts lá). Registra ANTES das rotas: o
  // plugin dynamic mode escuta o hook onRoute, que só pega rota declarada
  // depois dele estar no ar.
  await app.register(fastifySwagger, {
    openapi: {
      info: {
        title: "Maria — API (LangGraph nativo)",
        description:
          "Ponte Tykhe↔Verde pros fluxos de atendimento. Todo atendimento vive em /atendimentos — o campo flowId no body do POST de criação escolhe o fluxo (chamadas seguintes, GET e /respostas, resolvem sozinhas a partir do chatId); comece por GET /fluxos pra ver os ids disponíveis. Nível 3 de Richardson (HATEOAS) — siga os `_links` de cada resposta.",
        version: "0.2.0",
      },
      tags: [
        { name: "fluxos", description: "Descoberta de quais fluxos existem e seus ids" },
        { name: "atendimentos", description: "Ciclo de vida de um atendimento (thread do grafo), pra qualquer fluxo" },
      ],
      // declara o esquema de auth pro Swagger UI mostrar o botão "Authorize"
      // — sem isso dá pra ver a rota no /docs mas não dá pra testar direto
      // ali (ficaria sempre 401). Cada rota protegida marca `security` no
      // próprio schema pra herdar esse esquema.
      components: {
        securitySchemes: {
          bearerAuth: { type: "http", scheme: "bearer", description: "API_KEY — pedir no secret maria-langgraph-pp-prod/app" },
        },
      },
    },
  });
  await app.register(fastifySwaggerUi, { routePrefix: "/docs" });

  // GET /health — health check do target group do ALB (ECS). Sem side
  // effect, não toca em grafo/banco — só confirma que o processo responde.
  // Fica FORA do bloco protegido abaixo — o ALB não manda Bearer token.
  app.get("/health", { schema: { hide: true } }, async () => ({ status: "ok" }));

  // Rotas de negócio, protegidas por Bearer token — Tykhe é o único
  // consumidor esperado (chamada servidor-a-servidor). API_KEY obrigatório
  // (sem default silencioso — erra alto na subida se não setado, nunca sobe
  // a API "aberta" por engano). register() encapsulado: o hook de auth do
  // @fastify/bearer-auth só se aplica às rotas declaradas AQUI dentro, não
  // em /health nem /docs (fora deste bloco).
  const apiKey = process.env.API_KEY;
  if (!apiKey) throw new Error("API_KEY obrigatório (.env local ou secret em produção)");
  await app.register(async (protegido) => {
    await protegido.register(fastifyBearerAuth, { keys: new Set([apiKey]) });

    registrarRotaFluxos(protegido);
    registrarRotasAtendimento(protegido);
    registrarRotaOrquestrador(protegido);
  });

  // Issue #198 — webhook do WhatsApp Cloud API (Meta), pra testar o
  // orquestrador com um número de teste real. FORA do bloco protegido: é a
  // Meta quem chama essa rota, sem Bearer — autenticação própria é o
  // verify_token na verificação (GET) e o token de acesso do app da Meta no
  // envio de resposta (integracoes/whatsapp.ts). Recebe o apiKey pra fazer
  // as chamadas internas (app.inject) às rotas protegidas de atendimento
  // como um cliente autenticado normal, sem duplicar a lógica delas.
  await app.register(async (publico) => {
    registrarRotaWebhookWhatsapp(publico, apiKey);
  });

  return app;
}
