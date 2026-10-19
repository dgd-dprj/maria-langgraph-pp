# Índice de issues da migração (cópia)

> **Cópia.** O índice canônico é o comentário da #208: https://github.com/dgd-dprj/maria-langgraph-pp/issues/208#issuecomment-6222948856. Se os dois divergirem, vale o comentário. Esta cópia é atualizada junto com ele, sempre que uma issue é aberta, muda de estado ou de escopo, ou um PR de módulo é mergeado.

**Gerado em:** 2026-10-19 (atualizado depois do merge do PR 1 do api, #247, da abertura da #248 e da #249, e com o PR 2 do api pronto na branch).

**Comando:** `gh issue list --repo dgd-dprj/maria-langgraph-pp --state all --limit 300 --json number,title,state`. Os PRs vêm de `gh pr view <número>`. A coluna **Situação** é preenchida à mão a partir do `MIGRACAO.md` e das specs.

**Este comentário é o índice canônico.** `docs/migracao/INDICE-ISSUES.md` e `migracao-specs/INDICE-ISSUES.md` são cópias. Ele é atualizado sempre que uma issue é aberta, muda de estado ou de escopo, ou um PR de módulo é mergeado.

## Como ler a coluna Situação

A coluna **GitHub** é o estado da issue. A coluna **Situação** diz onde o código está. **"Fechada" no GitHub não significa que a correção chegou à `migration`.**

| Situação | Significado |
|---|---|
| **Mergeada na migration** | O código (tradução, ou correção trazida de develop) está na branch `migration` |
| **Corrigida em develop, pendente na migration** | Develop tem a correção; a `migration` ainda não, e o módulo que a traz está indicado |
| **Aprovada, aguardando janela** | Correção aprovada para depois do fim da migração, na base em Python (régua da #208: durante a migração, o Python reproduz develop) |
| **Aguardando decisão** | Alguém precisa decidir; quem decide está indicado |
| **Aguardando dado externo** | Falta informação de fora do repositório (Tykhe, CloudWatch, banco de produção) |
| **Em andamento** | Módulo com branch aberta |
| **A abrir** | Módulo ainda sem issue |

## 1. Módulos da migração

| # | Issue | Título curto | Tipo | GitHub | Situação |
|---|---|---|---|---|---|
| — | #208 | Migração de TypeScript para Python (issue-mãe) | governança | Aberta | Em andamento: régua, decisões e registros |
| 1 | #209 | Fundação | módulo | Fechada | **Mergeada na migration** (PR #213) |
| 2 | #216 | persistencia | módulo | Fechada | **Mergeada na migration** (PR #218) |
| 3 | #219 | integracoes | módulo | Fechada | **Mergeada na migration** (PR #221) |
| 4 | #223 | ia | módulo | Fechada | **Mergeada na migration** (PR #224; duas correções de tradução, mensagem vazia e `enum`, no PR #245) |
| 5 | #233 | subgrafos | módulo | Fechada | **Mergeada na migration** (PR #235) |
| 6 | #241 | fluxos | módulo | Fechada | **Mergeada na migration** (PR #243) |
| 7 | #244 | orquestrador | módulo | Fechada | **Mergeada na migration** (PR #245). Conferência diferencial: 80 cenários, 79 iguais e 1 divergência aceita |
| 8 | #246 | api (rotas, inclusive `/atendimentos/orquestrador`) | módulo | Aberta | **Em andamento.** **PR 1 (#247) mergeado na migration em 2026-10-18** (merge `23b63e3`): pipeline, `/fluxos`, `POST /atendimentos`, `POST /atendimentos/orquestrador`, `/docs` e o guia de rodar localmente. **A issue continua aberta porque falta o PR 2**, pronto na branch `refactor/246-api-python` (2026-10-19), aguardando confirmação para abrir o PR: `GET /atendimentos/:chatId`, `POST /atendimentos/respostas` (com o TTL) e o bridge do WhatsApp; 50 fixtures byte a byte, conferência com 313 cenários e mutação 27 de 28. Guia conferido em pasta limpa e modo B testado com o Bedrock em 2026-10-19 |
| 9 | — | scripts | módulo | — | A abrir |
| 10 | — | documentacao | módulo | — | A abrir |
| 11 | — | corte | módulo | — | A abrir |

## 2. Defeitos e achados de develop

| Issue | Título curto | Tipo | Módulo afetado | GitHub | Situação |
|---|---|---|---|---|---|
| #196 | Timeout do Verde vira falso "não encontrado" | defeito de develop | integracoes | Fechada | **Mergeada na migration** (corrigida em develop antes da base; traduzida no integracoes) |
| #210 | Erro 500 devolve a mensagem interna da exceção | defeito de develop | api | Aberta | **Aprovada, aguardando janela** |
| #211 | Erro 400 de validação sem motivo para a Tykhe | defeito de develop | api | Aberta | **Aprovada, aguardando janela** |
| #212 | Saída da IA sem validação; lista de parentescos | defeito de develop | ia, fluxos | Aberta | **Aguardando decisão de implementação em develop.** A lista de 8 valores alinhada ao SIPEN foi decidida (Ícaro, 2026-10-16) e entra em develop primeiro; depois fica pendente na migration. A validação (passos 1 e 2) espera a janela |
| #214 | `develop` e `main` sem proteção de branch | infra / governança | repositório | Aberta | **Aguardando decisão** (administração do repositório) |
| #215 | Chave do LangSmith injetada sem uso | infra | fundação, infra | Aberta | **Aguardando decisão** (tracing) |
| #217 | TTL descartava a resposta guardada | defeito de develop | persistencia, api | Aberta | **Mergeada na migration** (correção #226 de develop trazida no PR #243; verificada contra PostgreSQL 16.15) |
| #220 | Corpo da resposta do Verde no log | defeito de develop (dado pessoal) | integracoes, subgrafos, fluxos | Aberta | **Aguardando dado externo** (medição no CloudWatch); a correção espera a janela |
| #222 | Com o Bedrock fora, o embedding leva 13 min | defeito de develop | persistencia, ia | Aberta | **Aguardando decisão** (produto: prazo) |
| #225 | Catálogo do orquestrador com os tipos da Tykhe | funcionalidade de develop | fluxos, orquestrador, api | Aberta | **Corrigida em develop (PR #242), pendente na migration só no bridge do WhatsApp** (PR 2 do api). Fluxos e orquestrador mergeados no PR #245; a rota do orquestrador (`redirecionado`/`tipoCaso`), no PR #247 |
| #227 | "Sim" digitado encerrava o atendimento no TTL | defeito de develop | api | Aberta | **Corrigida em develop (PR #234), pendente na migration** (PR 2 do api, rota de respostas). As funções `normalizar_resposta` e `resposta_eh_nao` já estão na migration |
| #228 | TTL da #166 nunca disparou em produção | defeito de develop | api | Aberta | **Aguardando dado externo** (Tykhe: política de `chatId`) |
| #230 | Tokens contados até 6× | defeito de develop | subgrafos, fluxos | Aberta | **Aprovada, aguardando janela** (e medição) |
| #231 | Cadastro volta para a Tykhe sem o endereço | defeito de develop | subgrafos | Aberta | **Aprovada, aguardando janela** |
| #232 | Falha de infra no CEP vira "não encontrado" | defeito de develop | integracoes, subgrafos | Aberta | **Aprovada, aguardando janela** |
| #236 | Nome do titular exposto a quem digita o CPF ou o RG | **LGPD** | subgrafos, fluxos | Aberta | **Aguardando decisão** (proteção de dados). Prioridade máxima |
| #237 | `enderecoDetalhado` inteiro vai à Tykhe | defeito de develop | integracoes, fluxos | Aberta | **Aguardando dado externo** (Tykhe: campos necessários) |
| #238 | Encaminhamento criado e a pessoa ouve que falhou | defeito de develop | fluxos | Aberta | **Aguardando decisão** (prazo, pela gravidade) |
| #239 | Falha de infra nos órgãos manda ligar 129 | defeito de develop | integracoes, fluxos | Aberta | **Aprovada, aguardando janela** (e revisão das 9 chamadas ao Verde) |
| #240 | `dadosConhecidos` aceita qualquer canal | defeito de develop | api | Aberta | **Aguardando dado externo** (Tykhe: lista de campos). Relacionada à D-5 do api (`tokensGastos` fora do formato) |
| #248 | Falha ao chamar o Bedrock vira "não identificado" sem alerta | defeito de develop (observabilidade) | ia, orquestrador, corte (Grafana) | Aberta | **Aguardando decisão** (desfecho para a pessoa atendida e limiar do alerta). Mesmo padrão das #196, #232 e #239; incidente anterior na #200. Aberta em 2026-10-19, depois do teste do modo B |
| #249 | Com o #242, trabalhista e BPC/LOAS perdem a orientação "não atuamos, procure…" | defeito de develop (orientação errada à pessoa atendida) | orquestrador, fluxos | Aberta | **Aguardando decisão, com prazo: antes do próximo release de develop para `main`.** Produção (`main`) ainda dá a orientação certa da #22. Alcance pelo seed: 2 dos 74 planejados têm mensagem fixa (o banco de produção não foi consultado). Caso trabalhista executado; LOAS lido |

## 3. PRs de develop que a migração precisa trazer

| PR | Título curto | Módulo afetado | Situação |
|---|---|---|---|
| #226 | Corrige a #217 | persistencia | **Mergeada na migration** (PR #243) |
| #229 | Padrão de evidência e diagramas em issues | documentacao | **Corrigida em develop, pendente na migration** (módulo documentacao) |
| #234 | Corrige a #227 | api | **Corrigida em develop, pendente na migration** (PR 2 do api); `respostas.py` completo já na migration |
| #242 | Implementa a #225 | fluxos, orquestrador, api | **Corrigida em develop, pendente na migration só no bridge do WhatsApp** (PR 2 do api); a rota do orquestrador entrou no PR #247 |

**Pendências que ainda não têm issue:**
- lista de parentescos nova em develop (#212);
- A4 do orquestrador (pergunta real compartilhada sem uso; precisa do banco de produção);
- **aguardando dado externo:** contagem do relato vazio e da falha da classificação, que mudam de desfecho sem decisão no próximo release (`handoff_humano` → `outros`). A consulta está [na #208](https://github.com/dgd-dprj/maria-langgraph-pp/issues/208#issuecomment-6223132977); se a contagem mostrar que acontece, vira issue de produto.
