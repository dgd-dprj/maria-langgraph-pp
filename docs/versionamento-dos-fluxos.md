# Versionamento dos fluxos (#542)

Cada mudança num fluxo vira uma linha na tabela `fluxos_versoes` (Postgres), para auditoria: o que mudou, quando, quem pediu e quem aprovou. A tabela só recebe `INSERT`.

## Como funciona

1. **PR para a `develop`.** O job `versao-dos-fluxos` da CI compara os fluxos do PR com os da `develop` (`python -m maria.versionamento manifesto`, análise estática, sem importar o código antigo). Se algum fluxo mudou, o corpo do PR precisa das seções `## Solicitado por` e `## Resumo da mudança`; sem elas, a CI falha. Código compartilhado (`shared`, `ia`, `subgrafos`, `integracoes`) que muda só gera aviso no resumo do job.
2. **Deploy** (push em `staging` ou `main`). `scripts/montar_versao_meta.py` junta, para os PRs da promoção, o solicitante, o resumo, quem aprovou e os arquivos; o JSON vai na imagem (`--build-arg VERSAO_META`, arquivo `/app/versao-meta.json`). A imagem sai com a tag do ambiente e com `sha-<commit>`.
3. **Startup da Maria.** Em segundo plano, a Maria calcula o hash de cada fluxo e compara com a última linha do ambiente. Diferente ou primeira vez: grava uma linha nova com o snapshot, o `alteracoes` (item, antes e depois), o resumo e a autoria (os PRs que mexeram na pasta do fluxo). Falha ao gravar só aparece no log; a Maria segue atendendo.

## O que entra no hash

Código das funções, classes e constantes da pasta do fluxo, textos entre aspas (perguntas, mensagens, prompts), chamadas do grafo (`add_node`, `add_edge`…) e os campos de `FluxoConfig` / `TipoTykhe`. Comentário, docstring e formatação não mudam o hash. O código compartilhado vira a entrada `compartilhado`; quando muda, as versões dos fluxos gravadas no mesmo startup levam `mudou_codigo_compartilhado = true`.

## Colunas de `fluxos_versoes`

`fluxo` (id), `nome_fluxo`, `hash`, `hash_anterior`, `ambiente`, `registrado_em`, `snapshot` (jsonb), `alteracoes` (jsonb), `resumo` e `resumo_origem` (`pr` ou `automatico`), `commit_sha`, `tag_imagem`, `pr_numero`, `pr_titulo`, `issue_origem`, `autor_commit`, `solicitante`, `aprovado_por`, `mudou_codigo_compartilhado`, `prs` (jsonb, todos os PRs que mexeram no fluxo). Nenhum dado pessoal nem segredo: só código e textos fixos do repositório.

## Consultar

```bash
DATABASE_URL=... uv run python -m maria.versionamento listar pessoa-presa --ambiente producao --detalhes
```

## Rollback (manual)

A tabela diz qual commit e qual imagem usar. Voltar tudo: redeployar a imagem `sha-<commit>`. Voltar só um fluxo: `git revert` dos commits da pasta dele, PR e deploy (se `mudou_codigo_compartilhado` for verdadeiro, confira os outros fluxos). Conversa em andamento retoma com o grafo do código novo: ver #543.
