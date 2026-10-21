# SDD — Módulo `subgrafos`

Parte de #208. Branch: `refactor/<issue>-subgrafos-python`, criada a partir de `migration` @ `6a417c3` (depois do ia). Fonte de comportamento: `develop` @ `4e695f2`.

| Origem (develop) | Destino (migration) |
|---|---|
| `src/subgrafos/identificarAssistido/{state,graph}.ts` (36 + 145 linhas) | `src/maria/subgrafos/identificar_assistido/{state,graph}.py` |
| `src/subgrafos/cadastroPessoa/{state,graph}.ts` (39 + 120) | `src/maria/subgrafos/cadastro_pessoa/{state,graph}.py` |
| `src/subgrafos/coletarEndereco/{state,graph}.ts` (35 + 160) | `src/maria/subgrafos/coletar_endereco/{state,graph}.py` |
| `src/subgrafos/coletarEndereco/graph.test.ts` (3 testes) | `tests/subgrafos/test_coletar_endereco.py` |

**Fora deste módulo:** os fluxos pai (`fluxos/pessoaPresa`, `fluxos/violenciaDomestica`), que embutem estes subgrafos e serão traduzidos no módulo `fluxos`; as funções do Verde (integracoes, já na `migration`) e o `preparar_pergunta` (ia, já na `migration`).

---

## 0. Caracterização feita antes desta spec

### 0.1 Tokens com subgrafo: a dobra se compõe, e o Python reproduz sem código extra

A caracterização anterior (comentário 3 da #208) mediu a dobra com **um** subgrafo. Nela, o que foi acumulado antes do subgrafo conta duas vezes. Faltava o caso **aninhado**: o `cadastroPessoa` embute o `coletarEndereco`, e o fluxo de violência doméstica passa pelo `identificarAssistido` antes do cadastro.

As medições usaram a semente `tokensGastos = {100, 50, 150}`, `NODE_ENV=test` (nenhum nó gera delta) e o Verde em modo mock:

| Caminho | develop (LangGraph JS 1.4.12) | Python (LangGraph 1.2.14) |
|---|---|---|
| Pai → `identificarAssistido` | 150 → **300** (2×) | 150 → **300** |
| Pai → `cadastroPessoa` (→ `coletarEndereco`) | 150 → **450** (3×) | 150 → **450** |
| Pai → `identificarAssistido` → `cadastroPessoa` (sequência de violência doméstica com cadastro) | 150 → **900** (6×) | 150 → **900** |

- **develop:** medido com os subgrafos reais (`grafo` de cada módulo), num pai com os canais compartilhados. No caso da sequência, o mock não encontra o CPF `00000000000`, a pessoa responde "não" para tentar de novo, e o cadastro segue com CEP completo do mock.
- **Python:** medido com subgrafos mínimos usando o `CanalTokensGastos` da fundação, sem nó gerando delta.

**Conclusão.** A dobra não é um detalhe de uma linha. Num atendimento de violência doméstica que passa pelo cadastro, **tudo o que foi acumulado antes do CPF conta seis vezes** em `tokens_*` e no log `atendimento_finalizado`, que alimenta o painel de tokens. O LangGraph Python faz a mesma soma sozinho, então a régua (reproduzir develop) se cumpre sem tratamento especial. O teste 9 fixa os três números.

### 0.2 Objeto aninhado com `undefined` sai do JSON enviado ao Verde

O `montarEndereco` (`coletarEndereco/graph.ts:109-121`) monta `endereco` com 7 chaves, e qualquer uma pode ser `undefined`; o `complemento` quase sempre é, porque o nó grava `undefined` literal quando a pessoa responde "não" (`:73`). Esse objeto vai inteiro no POST `/pessoa` (`cadastroPessoa/graph.ts:58`), e o `JSON.stringify` **remove** as chaves `undefined`.

No Python, o `cadastrar_pessoa` traduzido (`integracoes/verde.py:624-627`) manda o dicionário como está, e `None` vira `null`. **Se o subgrafo gravar `None` nesses campos, o Verde passa a receber `"complemento": null`.** Isso muda o payload de um cadastro de pessoa.

---

## 1. Contexto

São três subgrafos, compilados sem checkpointer próprio (`.compile()`) e usados como **nó** pelos fluxos pai (`.addNode("x", subgrafo)`). O estado é compartilhado com o pai **por nome de canal**, sem nó de tradução (`identificarAssistido/state.ts:7-11`).

| Subgrafo | Faz | Quem usa |
|---|---|---|
| `identificarAssistido` | Pede o CPF, consulta o Verde, permite até 3 tentativas e confirma os dados quando a pessoa veio pelo orquestrador | violência doméstica (sempre); pessoa presa (só `viaOrquestrador`) |
| `cadastroPessoa` | Pede nome e data de nascimento, embute `coletarEndereco`, cadastra no Verde (POST) e confirma | os dois fluxos, quando o CPF não é encontrado |
| `coletarEndereco` | Pede o CEP, consulta o Verde e pergunta só o que o CEP não trouxe | `cadastroPessoa` |

Nenhum arquivo de `src/subgrafos/` chama o logger. Os logs vêm do Verde e do `reescrever` (seção 6).

## 2. Contrato

```python
# src/maria/subgrafos/<nome>/graph.py
grafo: CompiledStateGraph  # mesmo nome exportado de develop (export { grafo })
```

- **Estado:** um `TypedDict(total=False)` por subgrafo, com os **mesmos nomes de canal em camelCase** de develop. Os nomes são o contrato com os pais e com o checkpoint, e não seguem a convenção de nomes Python. O `tokensGastos` usa `CanalTokensGastos` (fundação); os demais canais não têm reducer (`LastValue`).
- **Interrupts:** o payload é `{"pergunta": ..., "tipo": ...}`, e `"opcoes": ["Sim", "Não"]` aparece **só** nos do tipo `sim_nao`. Nos do tipo `texto`, a chave `opcoes` fica **ausente**, e não `None`.
- **Nós e arestas:** os mesmos nomes de develop, com a mesma topologia. O teste 1 compara a lista de nós e de arestas com a de develop.

## 3. Comportamento

### 3.1 Regra de estado (#208, comentário de 2026-10-14) e o seu limite

**Regra:** onde develop devolve, como atualização de estado, uma chave com valor `undefined`, o Python escreve `None`.

**Limite (aprovado em 2026-10-14, #208):** a regra vale para as **chaves do canal**. Dentro de um **objeto aninhado** gravado num canal, `undefined` vira **chave ausente**, porque é assim que o objeto chega a todo lugar onde é lido depois: o `JSON.stringify` do POST ao Verde e a serialização do checkpoint removem a chave. Em código, isso é o `AUSENTE` de `shared/_js.py` com `_js.definir`.

| Ocorrência | develop | Python |
|---|---|---|
| `perguntaAtualTokensTotal` em todo nó `prepararPergunta*` | `undefined` sempre que não há IA | `None` (já é assim no `preparar_pergunta` do ia) |
| `consultarCep` → `logradouro`, `bairro`, `municipio`, `uf` (`coletarEndereco/graph.ts:32-37`) | cada um pode ser `undefined` | `None` no canal; os nós seguintes testam `is not None`, como o `!== undefined` de develop |
| `pedirComplemento` → `complemento` (`:73`) | `undefined` literal quando "não" | `None` no canal |
| `montarEndereco` → `endereco` (`:109-121`) | objeto com chaves `undefined` | **dicionário só com as chaves que têm valor** (seção 0.2) |
| `cadastrarPessoa` → `dadosPessoa` (`cadastroPessoa/graph.ts:64`) | `{encontrado, idPessoa, nome}` | idem; `nome` só some se `pedirNome` não tiver rodado |
| `consultarPessoa` → `dadosPessoa` (`identificarAssistido/graph.ts:55`) | resultado do Verde | o resultado do `consultar_pessoa_por_cpf` traduzido, que já omite chaves ausentes |

Nós que devolvem `{}` (bypass, CEP não encontrado) continuam devolvendo `{}`: nada é escrito.

### 3.2 Normalização de texto: JS e Python divergem nas bordas

| Função | develop | Python (reprodução) |
|---|---|---|
| `respostaEhSim` (4 cópias idênticas: `identificarAssistido/graph.ts:23-30`, `cadastroPessoa/graph.ts:40-47` e os dois fluxos) | `normalize("NFD")` → remove `[̀-ͯ]` → `trim()` → `toLowerCase()`; verdadeiro só para `"true"`, `"sim"`, `"s"` e `"yes"` | **Uma** função em `shared/` (as cópias de develop são a mesma regra): `unicodedata.normalize("NFD")`, remoção de `[̀-ͯ]`, `trim_js` e `lower()` |
| `cpfFormatoValido` (`identificarAssistido/graph.ts:19-21`) | `replace(/\D/g, "")` com 11 caracteres; `\D` sem a flag `u` só reconhece `0-9` ASCII | `re.sub(r"[^0-9]", "", v)`, e não `\D`, que no Python aceita dígitos de outros alfabetos |
| `pedirComplemento` (`coletarEndereco/graph.ts:71-73`) | **sem** NFD: `trim().toLowerCase()` em `{"não", "nao", "n", ""}` | idem, sem NFD. Um "não" decomposto (`a` + U+0303) **não** casa e vira complemento literal, como em develop |
| `pedirUf` (`:106`) | `trim().toUpperCase()` | `trim_js(...).upper()` |

**`trim()` do JS × `strip()` do Python:** o JS remove U+FEFF (BOM) e não remove os caracteres de controle `\x1c` a `\x1f`; o `strip()` do Python faz o contrário nos dois casos. A tradução usa um `trim_js` em `shared/_js.py`, com o conjunto de espaços do ECMAScript (WhiteSpace e LineTerminator). O teste 4 cobre os dois casos.

### 3.3 Valores gravados crus (reproduzidos)

- **`cpf`:** gravado como a pessoa digitou. Em `pedirCpf`, sem nenhuma validação. No retry com CPF digitado direto, o valor fica pontuado (`identificarAssistido/graph.ts:81`).
- **`dataNascimento`:** sem validação, apesar do texto "(dd/mm/aaaa)". Vai ao Verde como veio.
- **`cep`:** sem validação no subgrafo.
- **`uf`:** só `trim` e caixa alta.

### 3.4 Bypass e tentativas (reproduzidos)

- **CPF conhecido:** o bypass vale só com `tentativasCpf` 0 (`:35-37`). O CPF vindo de `dadosConhecidos` conta como a tentativa 1.
- **`depoisDeConsultarPessoa`** (`:64-68`), nesta ordem: `encontrado` → `falhaInfra` → `tentativasCpf >= 3` → tentar de novo.
- **Confirmação** (`confirmaAssistido`): só pergunta quando `viaOrquestrador`. Se o Verde não trouxer `nome`, o texto vira "Confirma que seus dados são: você?" (`:98`).

## 4. Casos de erro

| Situação | Comportamento (igual a develop) |
|---|---|
| Verde com falha de infra na consulta de pessoa | `dadosPessoa.falhaInfra` → `"esgotado"` → END. O pai decide (`falha_infra_verde`) |
| Verde com falha de infra na consulta de CEP | **Não** sinaliza: o CEP é tratado como não encontrado, e todas as perguntas de endereço são feitas (`verde.ts:382`) |
| Cadastro recusado pelo Verde | `cadastroErro` = mensagem do Verde (ou `"erro desconhecido"`) → `"falhou"` → END. O pai mostra essa mensagem à pessoa (#220, seção 4) |
| Resposta de interrupt que não é string | Gravada como veio; o caminho HTTP sempre manda string (módulo `api`) |

## 5. O que não muda

Textos das perguntas (byte a byte), nomes de nós e de canais, a ordem das perguntas, os bypasses, o limite de 3 tentativas, o payload dos interrupts, o que vai ao Verde e a dobra de tokens.

## 6. Observabilidade

Nada é registrado diretamente. Pelas funções chamadas:
- **Verde:** `pessoa`, `cep` e `cadastroPessoa`. O `corpo` cru é registrado no cadastro (#220).
- **`reescrever`:** campo `campo`, com o nome do campo e não o conteúdo.

A tradução não acrescenta nenhum log.

## 7. Testes que provam

**Traduzidos:** os 3 de `coletarEndereco/graph.test.ts`:
- CEP completo pula logradouro, bairro, município e UF;
- CEP `00000000` pergunta tudo;
- `MOCK_CEP_INCOMPLETO` pergunta o que falta.

Em develop, o teste 3 restaura a variável com `process.env.X = original`, o que grava a **string** `"undefined"`. A tradução usa `monkeypatch`, e isso é registrado como defeito do teste, sem efeito no comportamento.

**Novos:**
1. **Topologia:** nós, arestas e destinos das condicionais de cada subgrafo iguais aos de develop (lista literal no teste).
2. **Interrupts:** o payload de cada `pedir*` tem `pergunta`, `tipo` e, só nos `sim_nao`, `opcoes == ["Sim", "Não"]`. Nos de `texto`, `"opcoes" not in payload`.
3. **`respostaEhSim`:**
   - verdadeiro para `"true"`, `"sim"`, `"Sim"`, `" s "`, `"SÍM"` e `"yes"`;
   - falso para `"sim."`, `"claro"`, `"1"` e `""`;
   - com `"﻿sim"`, verdadeiro, porque o `trim()` do JS remove o BOM.
4. **`trim_js`:** remove U+FEFF e U+00A0, e **não** remove `\x1c`.
5. **`cpfFormatoValido`:** `"123.456.789-01"` é válido; dígitos arábico-índicos (`"١٢٣٤٥٦٧٨٩٠١"`) são **inválidos**, como no JS.
6. **Complemento:**
   - `"não"`, `"nao"`, `" N "` e `""` gravam `complemento: None`;
   - `"não"` (decomposto) grava o texto literal;
   - `"Apto 101"` grava `"Apto 101"`.
7. **Regra de estado, em dois passos:** depois de um complemento preenchido e outro "não" no mesmo `thread_id`, o canal termina em `None`, e não com o valor anterior. O mesmo vale para `perguntaAtualTokensTotal`.
8. **Endereço no POST:** passando pelo `cadastrar_pessoa` real com o transporte falso do integracoes, o corpo enviado ao Verde **não tem** a chave `complemento` quando a pessoa respondeu "não", e não tem nenhum `null` dentro de `endereco` (seção 0.2).
9. **Tokens, em pai mínimo com os subgrafos reais:** semente 150 → **300** com `identificar_assistido`, **450** com `cadastro_pessoa` e **900** com os dois em sequência. Os números são de develop (seção 0.1). O teste leva um comentário dizendo que a dobra é defeito reproduzido de propósito, com referência à **#230**.
10. **Fluxo do CPF:** bypass com CPF conhecido; 3 tentativas e esgotado; "não" ao retry na 1ª tentativa dá esgotado; CPF digitado direto no retry consulta sem perguntar de novo e grava o valor pontuado; `falhaInfra` dá esgotado.
11. **Cadastro:** com sucesso, `dadosPessoa == {"encontrado": True, "idPessoa": 888888, "nome": ...}` (mock). Com `MOCK_CADASTRO_FALHA`, `cadastroErro == "falha simulada (mock)"` e END.
12. **Confirmação:** com `viaOrquestrador` e sem `nome`, o texto é exatamente "Confirma que seus dados são: você?".

**Mutações a executar antes do PR** (técnica do `MIGRACAO.md`):

| Mutação | Teste que precisa falhar |
|---|---|
| `strip()` no lugar de `trim_js` | 3, 4 |
| `\D` no lugar de `[^0-9]` | 5 |
| NFD também no complemento | 6 |
| Omitir `complemento` no canal em vez de `None` | 7 |
| `None` dentro de `endereco` em vez de omitir | 8 |
| `"opcoes": None` nos interrupts de texto | 2 |
| Somar só os deltas (sem dobra) num redutor "corrigido" | 9 |

## 8. Critérios de aceite

- [ ] Os 3 testes traduzidos e os 12 novos passam sem rede (Verde em modo mock ou transporte falso).
- [ ] Mutações da seção 7 executadas, com o resultado registrado no PR.
- [ ] Nomes de canal, de nó e textos de pergunta iguais aos de develop.
- [ ] `respostaEhSim` e `trim_js` em `shared/`, cada um numa única função.
- [ ] Nenhum `None` dentro de `endereco`; `None` nos canais onde develop grava `undefined`.
- [ ] Achados da seção 9 registrados (issue ou `MIGRACAO.md`, conforme a decisão).
- [ ] `ruff`, `ruff format --check`, `mypy` strict e `pytest` verdes; jobs `test` e `imagem` do CI verdes.

## 9. Achados (defeitos de develop, reproduzidos)

| # | Achado | Onde | Efeito |
|---|---|---|---|
| A1 → **#230** | **A dobra de tokens se compõe:** chega a 6× em violência doméstica com cadastro | seção 0.1 | O custo registrado desse fluxo é 6× o real, e o fator muda de fluxo para fluxo. Um erro desigual leva a priorizar otimização no lugar errado |
| A2 → **#231** | **O endereço coletado no cadastro não chega ao pai:** nenhum dos pais tem o canal `endereco`, e o `dadosPessoa` do cadastro não tem `enderecoDetalhado` | `cadastroPessoa/graph.ts:64` | Em violência doméstica, o `consultarCep` do pai (`violenciaDomestica/graph.ts:233-235`) não acha CEP para quem acabou de se cadastrar e devolve `{}`. Os ids de UF, bairro e município ficam vazios, embora o CEP tenha sido perguntado. **Esses ids só aparecem na resposta da API à Tykhe** (`fluxos/*/api.ts`). O encaminhamento não os usa, porque o Verde resolve o órgão pelo `idPessoa`, com o endereço que acabou de ser cadastrado. Efeito: a Tykhe recebe os dados de quem acabou de se cadastrar sem `enderecoDetalhado` |
| A3 → **#232** | Falha de infra no CEP não é sinalizada: o **mesmo mecanismo da #196**, porque apenado (`verde.ts:163`) e pessoa (`:301`) propagam `falhaInfra`, e o CEP (`:382`) descarta | `verde.ts:382` | Com o Verde fora durante o atendimento, termina em `handoff_humano` (motivo `falha_cadastro`), como a #196 terminava em handoff (`rg_nao_encontrado`). A gravidade é a mesma, com mais desgaste: quatro perguntas de endereço mais a falha do cadastro |
| A4 | "Confirma que seus dados são: você?" quando o Verde não traz o nome; no cadastro, a confirmação mostra só o nome | `identificarAssistido/graph.ts:98` | Texto estranho; a confirmação não cobre data de nascimento nem endereço |
| A5 | Nenhuma validação de CPF (em `pedirCpf`), data de nascimento, CEP ou UF | seção 3.3 | Dado inválido vai ao Verde |
| A6 | `respostaEhSim` copiada em 4 arquivos; o complemento normaliza diferente (sem NFD) | seção 3.2 | Regras que podem divergir com o tempo |
| A7 | Comentários desatualizados ou errados | `identificarAssistido/graph.ts:13`; `cadastroPessoa/graph.ts:12-14`; `verde.ts:681-684`; `pessoaPresa/graph.ts:447-451` | Leitura enganosa (não são traduzidos para o Python) |

## Decisões (2026-10-14)

1. **Limite da regra de estado, aprovado:** `None` nas chaves do canal, chave ausente dentro de objetos aninhados. O que decide é como o JS chega ao JSON e ao checkpoint (comentário na #208). Entra no `MIGRACAO.md` no primeiro commit da branch.
2. **Issues:**
   - **A1 → #230**, escrita pelo efeito: o custo registrado é 6× o real, e o erro é desigual entre fluxos;
   - **A2 → #231**, com a verificação de que o encaminhamento não é afetado;
   - **A3 → #232**: reavaliada, tem o mesmo mecanismo e o mesmo desfecho da #196 (handoff desnecessário por falha de infra), com mais desgaste para a pessoa;
   - **A4 a A6** vão para o `MIGRACAO.md` como melhorias fora do escopo;
   - **A7** fica só na spec.

## Dependências

- `migration` @ `6a417c3`: `preparar_pergunta` (ia), as funções do Verde (integracoes), `CanalTokensGastos` e `_js.py` (`shared`).
- A correção do #226 (TTL) não toca estes subgrafos.
- A #225 (catálogo do orquestrador) não muda os subgrafos. O `viaOrquestrador` continua vindo do pai.
