import "dotenv/config";
import { montarApp } from "./app.js";
import { catalogoParaClassificacao } from "./fluxos/index.js";
import { aquecerCatalogo } from "./shared/embeddingsFluxos.js";

const app = await montarApp();
// host 0.0.0.0 — padrão do Fastify é 127.0.0.1, que funciona local mas não
// dentro de container (ALB conecta na interface real da task, não loopback).
app.listen({ port: 3001, host: "0.0.0.0" }, () => app.log.info("rodando em http://localhost:3001"));

// Issue #180 — dispara a indexação do catálogo de embeddings assim que o
// processo sobe, sem esperar a 1ª requisição real do orquestrador. Fire-
// and-forget: não atrasa o listen() nem o /health. Se uma requisição real
// chegar antes disso terminar, ela reaproveita a mesma indexação em
// andamento (garantirIndexado() é memoizado por processo).
catalogoParaClassificacao()
  .then(aquecerCatalogo)
  .catch((err) => app.log.error({ err }, "[embeddingsFluxos] falha ao pré-aquecer catálogo no boot"));
