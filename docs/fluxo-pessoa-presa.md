# Fluxo: Pessoa Presa

`flowId`: `3df874f2-675a-4c43-9ec7-480f7c702f50` — código em `src/fluxos/pessoaPresa/`.

Quem busca informação/encaminhamento sobre alguém que está presa (geralmente um familiar).

![Diagrama do fluxo pessoa presa](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/pessoa-presa.png)

## Passo a passo

```
1. [opcional] "Pode me contar a situação com suas palavras?"        ← só se EXTRACAO_LIVRE_IA=true (desligado por padrão)
2. "Você tem o número do processo?"           (sim/não)
     sim → 3. "Qual o número do processo?"     (texto) → consulta Verde (informativo, não bloqueia)
     não → pula pro passo 4
4. "Qual o RG da pessoa presa?"                (texto)
     formato inválido (não só números) → pergunta de novo
     formato válido → consulta Verde (/apenado)
        não encontrado, < 3 tentativas → "Quer tentar de novo?" (sim/não/RG direto)
        não encontrado, 3ª tentativa    → HANDOFF: rg_nao_encontrado
        encontrado                       → 5. "Confirma que é <nome>?" (sim/não)
           não confirmado                 → HANDOFF: nome_nao_confirmado
           confirmado                     → 6. "Qual seu parentesco?" (texto, classificado por IA numa lista fechada)
                                              → SEM viaOrquestrador (Tykhe, issue #191): conclui DIRETO, nunca
                                                pergunta CPF do assistido — idêntico ao comportamento de antes
                                                da issue #183.
                                              → COM viaOrquestrador (issue #191): 7. [subgrafo
                                                `identificarAssistido`, issue #183] "Qual o seu CPF?"
                                                 → consulta Verde (/pessoa) — identifica quem está CONVERSANDO,
                                                   diferente do RG acima (que identifica o PRESO)
                                                 encontrado                     → "Confirma que seus dados são: <nome>?" (sim/não, issue #189)
                                                                                    confirmou    → conclui
                                                                                    NÃO confirmou → HANDOFF: assistido_nao_confirmado
                                                 não encontrado, esgotou (3x)   → [subgrafo `cadastroPessoa`, issue #183]
                                                                                    nome, data de nascimento, endereço
                                                                                    (subgrafo `coletarEndereco`, CEP-first)
                                                                                    → POST /integra/pessoa
                                                 cadastrou com sucesso          → "Confirma que seus dados são: <nome>?" (sim/não, issue #189)
                                                                                    confirmou    → conclui (com o idPessoa novo)
                                                                                    NÃO confirmou → HANDOFF: assistido_nao_confirmado
                                                 falhou                         → HANDOFF: falha_cadastro
```

`identificarAssistido`/`cadastroPessoa` (que embute `coletarEndereco`) são os mesmos subgrafos reaproveitáveis de violência doméstica (issues #171/#176/#178) — aqui aplicados depois do RG/parentesco em vez de antes, mesmo racional (ver `docs/novo-fluxo.md`). RG do PRESO e CPF do ASSISTIDO identificam pessoas diferentes; nada na lógica de RG/processo/parentesco muda.

### `viaOrquestrador` — por que a Tykhe nunca pergunta CPF do assistido (issue #191)

Mesmo racional de `docs/fluxo-violencia-domestica.md`: a Tykhe consome este fluxo direto via `POST /atendimentos` com `flowId` explícito, contrato que já existia antes da issue #183. `viaOrquestrador` (setado só por `rotas/orquestrador.ts`, nunca pela Tykhe) decide se `identificarAssistido`/`cadastroPessoa` rodam depois do parentesco — sem esse sinal, o fluxo pula os 2 subgrafos inteiros e conclui direto, exatamente como era antes da #183.

## Regras de negócio (o que decide handoff vs conclusão)

A conclusão (`concluir()`, `graph.ts`) checa, nesta ordem:

1. **Sem número de processo** (`temProcesso === false`) → `handoff_humano`, motivo `sem_numero_processo`. Mesmo com RG/nome/parentesco todos ok — sem processo não tem como acompanhar a situação de verdade (issue #49).
2. **Processo com origem não suportada** (`dadosProcesso.origem !== "SEEU"`) → `handoff_humano`, motivo `origem_processo_nao_suportada`. Só processos de origem **SEEU** são resolvidos pelo bot; qualquer outra origem (ou processo não encontrado) cai aqui (issue #51).
3. **Situação/tipo de preso/regime fora do permitido** → `handoff_humano`, motivo `dados_pessoa_nao_atendidos` (issue #57):
   - `situacao` precisa estar em: `ATIVO`, `RESDOM`, `TRABALHO EXTRAMURO`, `BAIXA HOSPITALAR`, `VPF`, `VPF/TRABALHO EXTRAMURO`, `VPF/ATIVIDADE EDUCACIONAL`, `ABERTO/DOMICÍLIO COVID-19` (comparado sem prefixo `"EM "`, que o Verde usa de forma inconsistente).
   - `tipoPreso` precisa ser `CONDENADO` (não `PROVISÓRIO`).
   - `regime` precisa ser `FECHADO` ou `SEMIABERTO` (não `ABERTO`).
4. **Tudo ok** → `concluido`.

Outros motivos de handoff, fora dessa função:
- `rg_nao_encontrado` — esgotou as 3 tentativas de consulta ao Verde (RG do preso).
- `nome_nao_confirmado` — achou a pessoa mas a pessoa que está perguntando disse que não é ela.
- `falha_cadastro` (issue #183, só no caminho `viaOrquestrador`) — CPF do assistido esgotou as 3 tentativas **e** o cadastro novo no Verde (subgrafo `cadastroPessoa`) também falhou. Roda DEPOIS da conclusão normal do RG/processo/parentesco — não confundir com os motivos acima, que são sobre o PRESO.
- `assistido_nao_confirmado` (issue #189, só no caminho `viaOrquestrador`) — achou o assistido por CPF **ou** cadastrou com sucesso, mas ele negou que os dados são dele. Diferente de `falha_cadastro` (que é sobre o `POST /integra/pessoa` em si falhar) e de `nome_nao_confirmado` (que é sobre o PRESO, via RG).

## Tolerâncias (achadas ao vivo, ver comentários no código)

- **Sim/não tolerante** — aceita `"true"`/`"sim"`/`"s"`/`"yes"` (com/sem acento) como "sim", não só o literal `"true"` que o contrato prevê. A Tykhe às vezes repassa o texto que o usuário digitou/clicou, não o valor normalizado (issue achada 2026-08-31).
- **RG digitado direto na confirmação de retry** (issue #54) — na pergunta "quer tentar de novo?", se a resposta já é um RG válido (só números), usa direto como novo RG, sem perguntar "qual o RG?" de novo.
- **Extração livre por IA** (desligada por padrão, `EXTRACAO_LIVRE_IA=true` liga) — deixa a pessoa contar tudo de uma vez ("processo tal, RG tal, sou mãe dele") e extrai `temProcesso`/`numeroProcesso`/`rg`/`parentesco` de uma vez, pulando as perguntas correspondentes.

## Dados do Verde usados

- `POST /apenado` (por RG) — `idSeap`, `idPessoa`, `nome`, `situacao`, `tipoPreso`, `regime`. RG não encontrado vem como `"dados": {}` (objeto vazio, não `null`).
- `GET /processo/consultar/{numero}` — `id`, `origem`, `instancia`, `nomeAssunto`, `nomeOrgaoJulgador`, `movimentos` (com `traducao` em linguagem simples, pronta do Verde).
- `GET /pessoa?cpf=` e `POST /integra/pessoa` (issue #183, mesmos usados por `identificarAssistido`/`cadastroPessoa`) — identifica/cadastra o ASSISTIDO, não o preso.

Ver `docs/integracao-verde.md` pros detalhes de cada chamada.
