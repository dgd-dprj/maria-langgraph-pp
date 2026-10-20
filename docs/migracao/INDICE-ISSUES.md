# Índice de issues da migração (cópia)

> **Cópia.** O índice canônico é o comentário da #208: https://github.com/dgd-dprj/maria-langgraph-pp/issues/208#issuecomment-6222948856. Se os dois divergirem, vale o comentário. Esta cópia é atualizada junto com ele, sempre que uma issue é aberta, muda de estado ou de escopo, ou um PR de módulo é mergeado.

**Gerado em:** 2026-10-20 (atualizado com a abertura da #255 e da #256 e a conferência completa do módulo scripts, #252).

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
| 8 | #246 | api (rotas, inclusive `/atendimentos/orquestrador`) | módulo | Fechada | **Mergeada na migration** (PR #247, merge `23b63e3`; PR #250, merge `0bd610d`, 2026-10-19). Fluxo completo por HTTP: classificar, criar, responder às perguntas até a conclusão, consultar o atendimento, TTL e bridge do WhatsApp. 50 fixtures byte a byte; conferência com 343 + 313 cenários; bridge não testado com a Meta de verdade |
| 9 | #252 | scripts | módulo | Aberta | **Em andamento.** Spec 08 aprovada em 2026-10-19; branch `refactor/252-scripts-python`. Tradução feita: os 74 planejados extraídos e verificados contra o literal de develop (6 de 6 mutações pegas), o seed e a coleta. Conferência contra develop: 64 cenários, 62 idênticos e 2 com a diferença prevista na D-4. Falta o `logs-prod.sh` (D-3), o README, as mutações do seed e da coleta, e o PR. Achados: B1 (#251), B2 (#253), B3 (`logs-prod.sh` silencioso sem credencial), B4 (aspa solta numa palavra-chave, cosmético) e B5 (#255) |
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
| #225 | Catálogo do orquestrador com os tipos da Tykhe | funcionalidade de develop | fluxos, orquestrador, api | Aberta | **Mergeada na migration** (PR #242 de develop trazido nos PRs #245, #247 e #250; o bridge do WhatsApp entrou no #250) |
| #227 | "Sim" digitado encerrava o atendimento no TTL | defeito de develop | api | Aberta | **Mergeada na migration** (correção #234 de develop trazida no PR #250, rota de respostas) |
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
| #249 | Com o #242, trabalhista e BPC/LOAS perdem a orientação "não atuamos, procure…" | defeito de develop (orientação errada à pessoa atendida) | orquestrador, fluxos | Aberta | **Aguardando decisão, com prazo: antes do próximo release de develop para `main`.** Produção (`main`) ainda dá a orientação certa da #22. Alcance pelo seed: 2 dos 74 planejados têm mensagem fixa (o banco de produção não foi consultado). Caso trabalhista executado; LOAS lido. **Colisão com o seed (#253):** corrigir `mensagem_fixa` só no banco some no próximo seed; registrado nas duas issues em 2026-10-19. As opções 1 e 3 reativam a busca vetorial (#256) |
| #251 | Coleta da árvore do Verde apaga a categoria antes de varrer e sai com código 0 quando falha | defeito de develop (ferramenta de manutenção) | scripts | Aberta | **Aguardando decisão** (corrigir em develop ou na base em Python). Mesmo padrão da #196: falha de infraestrutura vira "categoria sem árvore". Lido; a conferência do scripts (#252) executa. Efeito na conversa hoje deve ser nenhum (catálogo do #242); volta se os planejados voltarem ao catálogo (#249) |
| #253 | Seed de `fluxos_planejados` sobrescreve o banco: correção de mensagem fixa feita no banco (#249) some na próxima execução | dívida técnica (fonte do dado) | scripts | Aberta | **Aguardando decisão:** qual é a fonte do dado, o arquivo do seed ou o banco. Proposta: o arquivo, com o seed recusando sobrescrever divergência. Colide com a #249. Lido; o banco de produção não foi consultado |
| #255 | Importar os fluxos inicializa o checkpointer: scripts criam tabelas de checkpoint e morrem sem o próprio prefixo de erro | dívida técnica (efeito colateral de importação) | scripts, fluxos | Aberta | **Aguardando decisão** (corrigir em develop ou na base em Python). Mesmo tema do ponto 1 da #208 (await no topo do módulo). A fundação Python já desfez o acoplamento; os scripts Python reproduzem o efeito explicitamente, pela régua. Executado em develop: a linha de log extra e a morte sem prefixo; lido: o CREATE TABLE de checkpoint |
| #256 | A busca vetorial do orquestrador não roda com o catálogo de 9 opções, e o boot indexa mesmo assim | dívida técnica (caminho inativo em produção) | orquestrador, persistencia | Aberta | **Aguardando decisão, junto com a #249.** Com 9 opções e k=10, o catálogo inteiro vai para a IA sem embedding (executado: 0 chamadas ao Bedrock nos dois lados); o boot indexa 9 descrições (lido). Se a #249 devolver os planejados, a busca volta de uma vez; pede medir a cobertura antes. Na migração: traduzida e conferida, não exercitada em execução real |

## 3. PRs de develop que a migração precisa trazer

| PR | Título curto | Módulo afetado | Situação |
|---|---|---|---|
| #226 | Corrige a #217 | persistencia | **Mergeada na migration** (PR #243) |
| #229 | Padrão de evidência e diagramas em issues | documentacao | **Corrigida em develop, pendente na migration** (módulo documentacao) |
| #234 | Corrige a #227 | api | **Mergeada na migration** (PR #250) |
| #242 | Implementa a #225 | fluxos, orquestrador, api | **Mergeada na migration** (PRs #245, #247 e #250) |

**Pendências que ainda não têm issue:**
- lista de parentescos nova em develop (#212);
- A4 do orquestrador (pergunta real compartilhada sem uso; precisa do banco de produção);
- **aguardando dado externo:** contagem do relato vazio e da falha da classificação, que mudam de desfecho sem decisão no próximo release (`handoff_humano` → `outros`). A consulta está [na #208](https://github.com/dgd-dprj/maria-langgraph-pp/issues/208#issuecomment-6223132977); se a contagem mostrar que acontece, vira issue de produto.
