# Scripts

Utilitários pontuais em `scripts/` — nenhum roda como parte do serviço em produção, e nenhum entra na imagem.

Os dois scripts Python rodam a partir da raiz do repositório, com o ambiente do projeto (`uv sync` antes):

```bash
uv run python scripts/coletar_arvore_perguntas_verde.py
uv run python scripts/seed_fluxos_planejados.py
```

> **Efeito ao iniciar, herdado de develop (#255).** Os dois scripts inicializam o checkpointer do LangGraph antes de qualquer outra coisa, como a importação dos fluxos fazia em develop:
> - sem `DATABASE_URL`, a primeira linha da saída é um aviso em JSON (`[checkpoint] DATABASE_URL ausente — usando MemorySaver`);
> - com `DATABASE_URL`, o script **cria as tabelas de checkpoint** (no schema `checkpoint_py`) no banco de destino;
> - com o banco inalcançável, o script morre com a pilha do psycopg, **sem** a mensagem `seed falhou:`/`crawl falhou:`. No Windows, o libpq não percebe a conexão recusada e pode ficar esperando sem limite: confira o `DATABASE_URL` antes.

## `coletar_arvore_perguntas_verde.py` (issue #20)

Varre a árvore de perguntas/assuntos do Verde (`GET /integra/assunto/consultar-item-arvore` categoria por categoria, até achar os "assuntos" finais em `GET /integra/assunto/{idAssunto}`), salvando tudo em `perguntas` + `assuntos_verde` (`src/maria/shared/perguntas_db.py`).

- **Quando rodar**: sob demanda, se a árvore de assuntos do Verde mudar (é a única forma de refrescar `perguntas`/`assuntos_verde`).
- **Não incremental** — recrawleia (limpa e reinsere) cada `flowId` visitado a cada rodada.
- **Precisa**: `DATABASE_URL` + `VERDE_JWT_TOKEN`/`VERDE_CLIENT_ID` reais no `.env` — sem modo mock, é coleta de dado real.
- **Atenção (#251)**: a categoria é apagada antes de ser varrida, sem transação. Se o Verde falhar no meio, ela fica com a árvore parcial ou vazia, e o script **sai com código 0** mesmo assim. Leia o resumo final: "N falha(s)" e a lista de categorias com falha. Cada chamada ao Verde tem prazo de 20 s, como no script de develop (o serviço usa 30 s, #196).

## `seed_fluxos_planejados.py` (issue #26)

Migração **única**, já rodada — populou `fluxos_planejados` com os 74 registros que antes viviam fixos no código (71 vieram de `GET /integra/assunto/categorias`, 3 só existiam na planilha de palavras-chave).

### Origem dos dados

> **Registro histórico (issue #26).** Os 74 registros viviam hardcoded em `src/fluxos/catalogo.ts`, na versão TypeScript, removido depois da migração para a tabela.

### Uso

- **Por que ainda existe**: é a **única cópia restante** dos dados originais (nome, descrição, palavras-chave, id de categoria do Verde, mensagem fixa) — sem ela, recriar `fluxos_planejados` do zero (banco novo, recuperação de desastre) não teria fonte.
- **Os dados** ficam em `scripts/dados/fluxos_planejados.json`, transcritos do seed de develop @ `1157a6d`. O teste `tests/scripts/test_seed_extracao.py` confere o arquivo contra o `.ts` original, guardado byte a byte em `tests/fixtures/scripts/`. **Não edite o JSON à mão**: uma mudança de dado entra no seed de develop, e a fixture, o id do blob esperado e o JSON mudam juntos.
- **Precisa**: `DATABASE_URL` no ambiente/`.env`.
- **Atenção (#253, colide com a #249)**: o seed **sobrescreve** nome, descrição, palavras-chave e `mensagem_fixa` dos 74 registros com o valor do arquivo, e grava `mensagem_fixa = NULL` nos 72 que não têm mensagem. **Uma edição feita à mão no banco some na próxima execução**, inclusive uma correção de mensagem fixa (a #249 provavelmente será resolvida assim). Rodar o seed num banco existente desfaz essas edições sem aviso. Até a #253 decidir qual é a fonte do dado, use o seed só em banco novo, ou leve a correção também para o seed.

## `logs-prod.sh`

Tail de log do CloudWatch em produção via polling manual (3s), formatado com `pino-pretty`.

- **Por que não usa `--follow`**: `aws logs tail --follow` travava/demorava na versão do CLI testada — poll manual sem `--follow` foi instantâneo.
- **Precisa**: Node.js (o `pino-pretty@13.1.3` roda pelo `npx`, e a primeira execução precisa de internet para baixá-lo) e o AWS CLI v2 com credencial configurada (a mesma usada pra qualquer comando `aws` local). O script confere os três antes de começar e diz o que falta.
- **Atenção (B3)**: o erro do `aws` é descartado, como em develop. Com a credencial vencida, o script não mostra erro, só nenhuma linha. Se nada aparecer, rode `aws sts get-caller-identity` para conferir a credencial.
- **Uso**: `./scripts/logs-prod.sh`.
