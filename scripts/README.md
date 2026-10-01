# Scripts

Utilitários pontuais em `scripts/` — nenhum roda como parte do serviço em produção.

## `coletarArvorePerguntasVerde.ts` (issue #20)

Varre a árvore de perguntas/assuntos do Verde (`GET /integra/assunto/consultar-item-arvore` categoria por categoria, até achar os "assuntos" finais em `GET /integra/assunto/{idAssunto}`), salvando tudo em `perguntas` + `assuntos_verde` (`shared/perguntasDb.ts`).

- **Quando rodar**: sob demanda, se a árvore de assuntos do Verde mudar (é a única forma de refrescar `perguntas`/`assuntos_verde`).
- **Não incremental** — recrawleia (limpa e reinsere) cada `flowId` visitado a cada rodada.
- **Precisa**: `DATABASE_URL` + `VERDE_JWT_TOKEN`/`VERDE_CLIENT_ID` reais no `.env` — sem modo mock, é coleta de dado real.
- **Uso**: `pnpm coletar:arvore-perguntas-verde`.

## `seedFluxosPlanejados.ts` (issue #26)

Migração **única**, já rodada — populou `fluxos_planejados` com os 74 registros que antes viviam hardcoded em `src/fluxos/catalogo.ts` (removido depois da migração; 71 vieram de `GET /integra/assunto/categorias`, 3 só existiam na planilha de palavras-chave).

- **Por que ainda existe**: é a **única cópia restante** dos dados originais (nome, descrição, palavras-chave, id de categoria do Verde) — sem esse arquivo, recriar `fluxos_planejados` do zero (banco novo, disaster recovery) não teria fonte.
- **Precisa**: `DATABASE_URL` no ambiente/`.env`.
- **Uso**: `pnpm seed:fluxos-planejados`.

## `logs-prod.sh`

Tail de log do CloudWatch em produção via polling manual (3s), formatado com `pino-pretty`.

- **Por que não usa `--follow`**: `aws logs tail --follow` travava/demorava na versão do CLI testada — poll manual sem `--follow` foi instantâneo.
- **Precisa**: credencial AWS configurada (mesma usada pra qualquer comando `aws` local).
- **Uso**: `./scripts/logs-prod.sh`.
