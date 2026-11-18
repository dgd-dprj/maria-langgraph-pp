# Scripts

Utilitários pontuais em `scripts/` — nenhum roda como parte do serviço em produção, e nenhum entra na imagem.

Os dois scripts Python que usam o banco rodam a partir da raiz do repositório, com o ambiente do projeto (`uv sync` antes):

```bash
uv run python scripts/coletar_arvore_perguntas_verde.py
uv run python scripts/seed_fluxos_planejados.py
```

> **Sem checkpointer (#255, decisão da Nicole, 2026-11-17).** Os dois scripts não inicializam mais o checkpointer do LangGraph, como a importação dos fluxos fazia em develop: não criam tabelas de checkpoint, a saída não tem o aviso do MemorySaver, e qualquer falha (inclusive o banco inalcançável) sai com a mensagem seed falhou: ou crawl falhou: e código 1. No Windows, o libpq não percebe a conexão recusada e pode ficar esperando sem limite: confira o DATABASE_URL antes.

## `coletar_arvore_perguntas_verde.py` (issue #20)

Varre a árvore de perguntas/assuntos do Verde (`GET /integra/assunto/consultar-item-arvore` categoria por categoria, até achar os "assuntos" finais em `GET /integra/assunto/{idAssunto}`), salvando tudo em `perguntas` + `assuntos_verde` (`src/maria/shared/perguntas_db.py`).

- **Quando rodar**: sob demanda, se a árvore de assuntos do Verde mudar (é a única forma de refrescar `perguntas`/`assuntos_verde`).
- **Não incremental** — recrawleia (limpa e reinsere) cada `flowId` visitado a cada rodada.
- **Precisa**: `DATABASE_URL` + `VERDE_JWT_TOKEN`/`VERDE_CLIENT_ID` reais no `.env` — sem modo mock, é coleta de dado real.
- **Troca numa transação (#251, decisão da Nicole, 2026-11-18)**: cada categoria é varrida em memória, sem tocar no banco. No fim, as categorias que deram certo trocam de árvore numa transação só. Uma categoria que falhou **fica com a árvore anterior**, aparece no resumo ("categorias com falha (a árvore anterior foi mantida): …"), e o script **sai com código 1**. Se a própria troca falhar no banco, nenhuma árvore muda, e a saída é crawl falhou:. Em develop, a categoria era apagada antes da varredura e a falha saía com código 0. Cada chamada ao Verde tem prazo de 20 s, como no script de develop (o serviço usa 30 s, #196).

## `conferir_token_verde.py` (issue #298)

Confere se o Verde aceita o token do segredo de um ambiente. **Só leitura**: chama `GET /autenticacao/token/status` e nunca o `refresh`, que invalida o token antigo na hora e é exclusivo do `verificar-token-verde.yml`. Roda nos workflows de deploy e no `verificar-token-verde.yml`, no runner do GitHub, só com a biblioteca padrão (`python3`, sem `uv sync`):

```bash
python3 scripts/conferir_token_verde.py --ambiente release --segredo segredo.json
```

`segredo.json` é o `SecretString` do `maria-langgraph-pp-<ambiente>/app`. Sai com código 1 quando o Verde não aceita o token, e o log nunca traz o token. Testes sem rede em `tests/scripts/test_conferir_token_verde.py`.

## `seed_fluxos_planejados.py` (issue #26)

Migração **única**, já rodada — populou `fluxos_planejados` com os 74 registros que antes viviam fixos no código (71 vieram de `GET /integra/assunto/categorias`, 3 só existiam na planilha de palavras-chave).

### Origem dos dados

> **Registro histórico (issue #26).** Os 74 registros viviam hardcoded em `src/fluxos/catalogo.ts`, na versão TypeScript, removido depois da migração para a tabela.

### Uso

- **Por que ainda existe**: é a **única cópia restante** dos dados originais (nome, descrição, palavras-chave, id de categoria do Verde, mensagem fixa) — sem ela, recriar `fluxos_planejados` do zero (banco novo, recuperação de desastre) não teria fonte.
- **Os dados** ficam em `scripts/dados/fluxos_planejados.json`, transcritos do seed de develop @ `1157a6d`. **Desde a #253, este JSON é a fonte**: uma mudança de dado entra por PR nele. A conferência contra o `.ts` de develop (o teste de extração, com a fixture e o leitor do literal; ver a spec 08) foi aposentada em 2026-11-18, no mesmo PR da decisão; `tests/scripts/test_seed_dados.py` confere o próprio arquivo (ids únicos e tipos dos campos).
- **Precisa**: `DATABASE_URL` no ambiente/`.env`.
- **O arquivo vale (#253, decisão da Nicole, 2026-11-18).** Toda mudança de dado (nome, descrição, categoria, palavras-chave, mensagem fixa) entra **por PR** em `scripts/dados/fluxos_planejados.json`, e o seed leva ao banco. Não se edita a tabela à mão.
  - **Antes de gravar, o seed compara o banco com o arquivo.** Se algum registro estiver diferente, ele mostra cada registro e coluna (nos textos, o valor do banco e o do arquivo; nas palavras-chave, o que entra e o que sai), **não grava nada** e sai com `seed falhou:` e código 1.
  - **`--force`** (`uv run python scripts/seed_fluxos_planejados.py --force`) mostra a mesma diferença e sobrescreve, para quando a sobrescrita é intencional (por exemplo, depois de levar ao JSON a correção que alguém fez no banco).
  - **A gravação é uma transação só:** entram os 74 registros, ou nenhum. Um registro que só existe no banco não é tocado e aparece num aviso.
  - **Roda só à mão.** Nenhum deploy, subida de container ou passo de pipeline chama o seed. Por isso, a recusa com código 1 não trava nada sozinha: aparece para quem rodou.

## `logs-prod.sh`

Tail de log do CloudWatch em produção via polling manual (3s), formatado com `pino-pretty`.

- **Por que não usa `--follow`**: `aws logs tail --follow` travava/demorava na versão do CLI testada — poll manual sem `--follow` foi instantâneo.
- **Precisa**: Node.js (o `pino-pretty@13.1.3` roda pelo `npx`, e a primeira execução precisa de internet para baixá-lo) e o AWS CLI v2 com credencial configurada (a mesma usada pra qualquer comando `aws` local). O script confere os três antes de começar e diz o que falta.
- **Atenção (B3)**: o erro do `aws` é descartado, como em develop. Com a credencial vencida, o script não mostra erro, só nenhuma linha. Se nada aparecer, rode `aws sts get-caller-identity` para conferir a credencial.
- **Uso**: `./scripts/logs-prod.sh`.
