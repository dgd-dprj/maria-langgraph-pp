# Índice de issues da migração

Catálogo das issues ligadas à migração de TypeScript para Python (#208) e aos achados da leitura de develop.

- **Fonte:** `gh issue list --repo dgd-dprj/maria-langgraph-pp --state all --limit 100`, levantado em 2026-10-14. Os PRs vêm de `gh pr view`.
- **Estado:** o do GitHub nessa data. "Fechada" não quer dizer que a correção chegou à `migration`; a coluna de situação diz onde cada uma está.
- **Atualizar:** rodar o comando de novo e conferir as colunas de estado e de situação.

## 1. Tradução por módulo e governança

| # | Issue | Tipo | Módulo | Estado | PR | Resumo |
|---|---|---|---|---|---|---|
| — | [#208](https://github.com/dgd-dprj/maria-langgraph-pp/issues/208) | [TECH] | governança | Aberta | — | Issue-mãe: régua, decisões, ordem dos módulos e registros da migração |
| 1 | [#209](https://github.com/dgd-dprj/maria-langgraph-pp/issues/209) | [TECH] | fundação | Fechada | [#213](https://github.com/dgd-dprj/maria-langgraph-pp/pull/213) | Projeto Python, logger, pool, checkpointer, CI e imagem |
| 2 | [#216](https://github.com/dgd-dprj/maria-langgraph-pp/issues/216) | [TECH] | persistencia | Fechada | [#218](https://github.com/dgd-dprj/maria-langgraph-pp/pull/218) | As quatro stores Postgres e em memória, e os embeddings |
| 3 | [#219](https://github.com/dgd-dprj/maria-langgraph-pp/issues/219) | [TECH] | integracoes | Fechada | [#221](https://github.com/dgd-dprj/maria-langgraph-pp/pull/221) | Cliente do Verde e do WhatsApp com a semântica do `fetch` |
| 4 | [#223](https://github.com/dgd-dprj/maria-langgraph-pp/issues/223) | [TECH] | ia | Fechada | [#224](https://github.com/dgd-dprj/maria-langgraph-pp/pull/224) | As seis funções do Bedrock, sem validação, e o retry dos embeddings |
| 5 | [#233](https://github.com/dgd-dprj/maria-langgraph-pp/issues/233) | [TECH] | subgrafos | Fechada | [#235](https://github.com/dgd-dprj/maria-langgraph-pp/pull/235) | `identificar_assistido`, `cadastro_pessoa` e `coletar_endereco` |
| 6 | [#241](https://github.com/dgd-dprj/maria-langgraph-pp/issues/241) | [TECH] | fluxos | Aberta | — | Violência doméstica, pessoa presa e padrão. Tradução feita na branch (74 testes de develop + 74 novos; diferencial com 584 cenários). Achados revisados e D-1 aceito como divergência (2026-10-16); PR para a `migration` a abrir |
| 7 | — | — | orquestrador | sem issue | — | A abrir; a #225 pode mudar o escopo |
| 8 | — | — | api | sem issue | — | A abrir; notas prontas (TTL do #234, `resume=""`, canais por ambiente) |
| 9 | — | — | scripts | sem issue | — | A abrir |
| 10 | — | — | documentacao | sem issue | — | A abrir; recebe o #229 de develop |
| 11 | — | — | corte | sem issue | — | A abrir |

## 2. Defeitos e achados da leitura de develop

A coluna **Aguarda** diz quem precisa decidir ou agir antes de a issue andar. "Janela" quer dizer correção aprovada para depois do fim da migração, na base em Python (régua da #208).

| Issue | Tipo | Módulo afetado | Estado | Aguarda | Resumo |
|---|---|---|---|---|---|
| [#196](https://github.com/dgd-dprj/maria-langgraph-pp/issues/196) | [TECH] | integracoes | Fechada | — | Timeout do Verde gerava falso "não encontrado". Referência do padrão das #232 e #239 |
| [#210](https://github.com/dgd-dprj/maria-langgraph-pp/issues/210) | [BUG] | api | Aberta | Janela | Erro 500 devolve ao cliente a mensagem interna da exceção |
| [#211](https://github.com/dgd-dprj/maria-langgraph-pp/issues/211) | [ENHANCEMENT] | api | Aberta | Janela | Erro 400 de validação devolve corpo vazio, sem motivo para a Tykhe |
| [#212](https://github.com/dgd-dprj/maria-langgraph-pp/issues/212) | [BUG] | ia, fluxos | Aberta | **Ícaro** (lista do SIPEN) | Saída da IA sem validação; a lista de parentescos diverge do SIPEN (só 2 de 15 coincidem) |
| [#214](https://github.com/dgd-dprj/maria-langgraph-pp/issues/214) | [BUG] | governança do repositório | Aberta | Administração do repositório | `develop` e `main` sem proteção de branch |
| [#215](https://github.com/dgd-dprj/maria-langgraph-pp/issues/215) | [TECH] | fundação, infra | Aberta | Decisão sobre o tracing | Chave do LangSmith injetada nos containers sem uso |
| [#217](https://github.com/dgd-dprj/maria-langgraph-pp/issues/217) | [BUG] | persistencia, api | Aberta | Merge do fluxos (#241) | TTL descartava a resposta guardada. Corrigida em develop pelo #226; trazida na branch do fluxos (`2403bab`) |
| [#220](https://github.com/dgd-dprj/maria-langgraph-pp/issues/220) | [BUG] | integracoes, subgrafos, fluxos | Aberta | Janela + medição no CloudWatch | Corpo da resposta do Verde no log e mensagem do Verde mostrada à pessoa |
| [#222](https://github.com/dgd-dprj/maria-langgraph-pp/issues/222) | [BUG] | persistencia, ia | Aberta | **Produto** (prazo) | Com o Bedrock fora, o embedding leva de 12,5 a 14,7 min e até 147 requisições |
| [#227](https://github.com/dgd-dprj/maria-langgraph-pp/issues/227) | [BUG] | api | Aberta | Tradução do api | "Sim" digitado encerrava o atendimento no TTL. Corrigida em develop pelo #234 |
| [#228](https://github.com/dgd-dprj/maria-langgraph-pp/issues/228) | [TECH] | api | Aberta | **Tykhe** (política de `chatId`) | O TTL da #166 nunca disparou em produção; hipótese: `chatId` novo a cada volta |
| [#230](https://github.com/dgd-dprj/maria-langgraph-pp/issues/230) | [BUG] | subgrafos, fluxos | Aberta | Janela + medição | Tokens contados até 6× em violência doméstica com cadastro; erro desigual entre fluxos |
| [#231](https://github.com/dgd-dprj/maria-langgraph-pp/issues/231) | [BUG] | subgrafos | Aberta | Janela | Quem acabou de se cadastrar volta para a Tykhe sem o endereço; o encaminhamento não é afetado |
| [#232](https://github.com/dgd-dprj/maria-langgraph-pp/issues/232) | [BUG] | integracoes, subgrafos | Aberta | Janela | Falha de infra no CEP vira "não encontrado"; mesmo desfecho da #196, com mais desgaste |
| [#236](https://github.com/dgd-dprj/maria-langgraph-pp/issues/236) | [BUG][LGPD] | subgrafos, fluxos | Aberta | **LGPD** (proteção de dados) | Nome do titular exposto a quem digita o CPF ou o RG; em violência doméstica, também o município do órgão. Prioridade máxima |
| [#237](https://github.com/dgd-dprj/maria-langgraph-pp/issues/237) | [TECH] | integracoes, fluxos | Aberta | **Tykhe** (campos necessários) | `enderecoDetalhado` completo vai à Tykhe, mas o tipo declara só o CEP |
| [#238](https://github.com/dgd-dprj/maria-langgraph-pp/issues/238) | [BUG] | fluxos | Aberta | Decisão de prazo (gravidade) | Encaminhamento criado no Verde e a pessoa ouve que falhou; já aconteceu com todos os encaminhamentos |
| [#239](https://github.com/dgd-dprj/maria-langgraph-pp/issues/239) | [BUG] | integracoes, fluxos | Aberta | Janela + revisão das 9 chamadas ao Verde | Falha de infra na consulta de órgãos vira "ligue 129"; terceiro caso do padrão |
| [#240](https://github.com/dgd-dprj/maria-langgraph-pp/issues/240) | [TECH] | api | Aberta | **Tykhe** (lista de campos) | `dadosConhecidos` aceita qualquer canal; `encaminhamentoId` pré-preenchido mostra protocolo falso |

**Outra issue de develop que afeta módulos ainda não traduzidos:**

| Issue | Tipo | Módulo afetado | Estado | Aguarda | Resumo |
|---|---|---|---|---|---|
| [#225](https://github.com/dgd-dprj/maria-langgraph-pp/issues/225) | [FEATURE] | orquestrador, api | Aberta | Implementação em develop | Catálogo do orquestrador reduzido a 9 opções, com status `redirecionado` para a Tykhe |

## 3. PRs recentes de develop que impactam a migração

São pull requests, e não issues. Pela régua, o que entra em develop antes de um módulo ser traduzido é traduzido com ele. O que entra depois é trazido para a `migration` em commit próprio.

| PR | Tipo | Módulo afetado | Estado | Situação na migração | Resumo |
|---|---|---|---|---|---|
| [#226](https://github.com/dgd-dprj/maria-langgraph-pp/pull/226) | fix | persistencia | Mergeado em develop (2026-10-14) | Trazido na branch do fluxos (`2403bab`); SQL ainda não executado contra Postgres, o que acontece no CI do PR | Corrige a #217: a resposta guardada é devolvida ao confirmar o TTL |
| [#229](https://github.com/dgd-dprj/maria-langgraph-pp/pull/229) | docs | documentacao | Mergeado em develop (2026-10-14) | A trazer no módulo documentacao | Padrão de evidência em issues, diagramas Mermaid no texto, formulário `bug.yml` |
| [#234](https://github.com/dgd-dprj/maria-langgraph-pp/pull/234) | fix | api (e fluxos sem mudança de comportamento) | Mergeado em develop (2026-10-14) | Entra na tradução do api; nos fluxos, só a importação de `respostaEhSim` muda | Corrige a #227: confirmação de TTL aceita "sim" e repete a pergunta quando não reconhece |
