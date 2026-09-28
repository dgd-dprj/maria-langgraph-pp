# Fluxo: Violência Doméstica

`flowId`: `cabb2495-4e12-4f4a-9956-3d20649059bc` — código em `src/fluxos/violenciaDomestica/`. Categoria Verde equivalente: `idCategoriaAssuntoVerde = 10113`.

Vítima de violência doméstica buscando ajuda/proteção/encaminhamento jurídico.

![Diagrama do fluxo violência doméstica](https://maria-langgraph-pp-docs-185327115563.s3.amazonaws.com/diagramas/violencia-domestica.png)

## Passo a passo

```
1. "Você é a vítima de violência doméstica?"   (sim/não)
     não → HANDOFF: nao_e_vitima
     sim → 2.
2. "Existe algum processo relacionado ao seu caso?"   (sim/não/número direto)
     sim ou número direto → 3. "Qual o número do processo?" (se não veio direto) → consulta Verde (informativo)
        não encontrado, < 3 tentativas → "Quer tentar de novo?" (sim/não/número direto)
        esgotou (3 tentativas, ou respondeu "não")  → segue mesmo assim, NUNCA vira handoff (é só informativo)
     não → pula pro passo 4
4. "Você já registrou o Boletim de Ocorrência (RO) na delegacia?"   (sim/não)
5. [subgrafo `identificarAssistido`] "Qual o seu CPF?"   (texto — pulado se `cpf` já veio em dadosConhecidos)
     → consulta Verde (/pessoa)
     encontrado, SEM viaOrquestrador (Tykhe)      → 6. direto, sem confirmar nada (comportamento de antes da #189)
     encontrado, COM viaOrquestrador (issue #191) → "Confirma que seus dados são: <nome>?" (sim/não, issue #189)
                                                       confirmou              → 6.
                                                       NÃO confirmou          → HANDOFF: assistido_nao_confirmado
     não encontrado, < 3 tentativas      → "Quer tentar de novo o CPF?" (sim/não/CPF direto)
     não encontrado, esgotou (3x), SEM viaOrquestrador (Tykhe) → HANDOFF: cpf_nao_encontrado
                                                                   (comportamento de antes da issue #171 — NUNCA
                                                                   entra em cadastro, é a mesma pergunta que a
                                                                   Tykhe sempre fez)
     não encontrado, esgotou (3x), COM viaOrquestrador (issue #191) → [subgrafo `cadastroPessoa`, issue #171]
                                             "Qual o seu nome completo?" → "Qual a sua data de nascimento?"
                                             → [subgrafo `coletarEndereco`, issue #176]
                                                CEP → consulta Verde (/cep) → só pergunta o que a Verde
                                                não devolveu em texto (logradouro/bairro/município/UF podem
                                                vir prontos; número e complemento nunca vêm do CEP, sempre
                                                perguntados)
                                             → POST /integra/pessoa (cadastro novo, CPF reaproveitado, nunca perguntado de novo)
                                             cadastrou com sucesso → "Confirma que seus dados são: <nome>?" (sim/não, issue #189)
                                                confirmou              → 6. (com o idPessoa novo)
                                                NÃO confirmou          → HANDOFF: assistido_nao_confirmado
                                             falhou                → HANDOFF: falha_cadastro (NÃO finge sucesso)
6. consulta Verde (/cep) com o CEP do endereço → preenche idUf/idBairro/idMunicipio (não bloqueia se faltar)
   consulta Verde (/plantao/vigente) — plantão ativo agora?
   consulta órgão certo (plantão OU normal, conforme acima) pelo idPessoa + RO
     nenhum órgão encontrado (RO:true sem órgão) → HANDOFF: sem_orgao_disponivel
     órgão encontrado                             → 7.
7. cria o encaminhamento DE VERDADE no Verde (POST real, registro criado no sistema deles)
     falhou → HANDOFF: falha_encaminhamento (NÃO finge sucesso pro usuário)
     deu certo → CONCLUÍDO (mensagem com nome do órgão + protocolo)
```

`identificarAssistido`, `cadastroPessoa` e `coletarEndereco` (aninhado dentro de `cadastroPessoa`) são subgrafos reaproveitáveis (`src/subgrafos/`, ver `docs/novo-fluxo.md`) — embutidos como nó dentro deste fluxo, mesmo `chatId`/checkpoint.

### `viaOrquestrador` — por que a Tykhe nunca vê nada disso (issue #191)

A Tykhe consome este fluxo direto via `POST /atendimentos` com `flowId` explícito — contrato que já existia antes das issues #171/#189. Pra não alterar NADA desse contrato, um sinal novo no state (`viaOrquestrador`) decide se o comportamento novo (cadastro automático, confirmação de dados) ativa:

- **Setado `true`** só em um lugar: `rotas/orquestrador.ts`, ao criar o atendimento via `POST /atendimentos/orquestrador` (pra quem não sabe de antemão qual fluxo usar — não é a Tykhe).
- **Nunca setado** por quem chama `POST /atendimentos` direto — a Tykhe nunca manda esse campo, então o fluxo se comporta exatamente como antes dessas issues: CPF esgotado vira handoff direto (`cpf_nao_encontrado`), sem tentar cadastro nem perguntar confirmação.
- É o MESMO `flowId`, o MESMO grafo — só o roteamento pós-subgrafo (`depoisDeIdentificarAssistido`/`depoisDeCadastrarPessoa`) e a confirmação dentro dos subgrafos checam esse sinal.

## Regras de negócio

### Motivos de handoff

| Motivo | Quando |
|---|---|
| `nao_e_vitima` | Respondeu "não" na 1ª pergunta. |
| `sem_orgao_disponivel` | Pessoa encontrada, mas o Verde não achou nenhum órgão pra ela (só acontece com RO:true — sem RO sempre tem fallback). Vem com `mensagemCrc` pronta do Verde ("...ligar 129"). |
| `falha_cadastro` | Só no caminho `viaOrquestrador`: esgotou as 3 tentativas de CPF sem achar a pessoa **e** o cadastro novo no Verde (subgrafo `cadastroPessoa`, issue #171) também falhou — não confunde com `sem_orgao_disponivel` (que é pra pessoa já encontrada/cadastrada). |
| `cpf_nao_encontrado` | Só no caminho SEM `viaOrquestrador` (Tykhe): esgotou as 3 tentativas de CPF sem achar a pessoa — handoff direto, nunca tenta cadastro (issue #72, restaurado na #191). |
| `assistido_nao_confirmado` | Só no caminho `viaOrquestrador`: achou por CPF **ou** cadastrou com sucesso, mas a pessoa negou que os dados são dela (issue #189) — não confunde com `falha_cadastro` (que é sobre o `POST /integra/pessoa` em si falhar, não sobre confirmação). |
| `falha_encaminhamento` | Achou o órgão certo, mas o `POST /encaminhamento/encaminhar` de verdade falhou. Nunca inventa sucesso — manda pra atendente confirmar manualmente. |

### Quem decide o órgão: a Verde, não a Maria

`consultarOrgaosViolenciaDomestica(indicacaoRO, idPessoa)` manda só **RO (sim/não) + idPessoa** — o Verde resolve internamente pelo endereço cadastrado da pessoa (capital x outras cidades, DP x Juizado x NUDEM). Não tem comparação de município no nosso lado — isso morava aqui antes e foi removido quando confirmado que o Verde já decide isso de verdade (regra deles, documentada nas issues #8485/#10146 do Facilitador deles: sem RO cai em NUDEM > núcleo de 1º atendimento > DP única; com RO cai no Juizado de VD ou DP única competente).

### Plantão muda a regra de órgão

Antes de consultar órgão, o fluxo checa `GET /plantao/vigente` (sem parâmetro, plantões ativos agora). Se não vazio, usa `consultarOrgaosPlantaoViolenciaDomestica` (endpoint diferente, nem recebe RO) em vez da consulta normal.

### Urgência = já tem RO

`temRegistroOcorrencia: true` vira `urgencia: true` no `POST /encaminhamento/encaminhar` (com `motivoUrgencia` fixo) — muda a mensagem final ("vou encaminhar com urgência... sem necessidade de agendamento" vs. o texto padrão) e o `tipoEncaminhamento` exposto (`urgente`/`padrao`).

## Tolerâncias (achadas ao vivo)

- **Sim/não tolerante** — mesma tolerância de pessoa presa (`"sim"`/`"s"`/`"yes"`, com/sem acento).
- **Número de processo/CPF digitado direto** — tanto na pergunta inicial (`Existe algum processo?`, issue #110) quanto nas perguntas de retry (`Quer tentar de novo?`, issue #77): se o texto bate o formato esperado (processo = 20 dígitos, CPF = 11 dígitos), usa direto como o valor, pulando a pergunta seguinte.
- **CPF pré-preenchido** — se `dadosConhecidos.cpf` já veio no `POST /atendimentos` (contrato com a Tykhe), não pergunta CPF de novo. Só vale na 1ª tentativa (`tentativasCpf === 0`) — um retry sempre pergunta de novo, nunca reusa o CPF que já falhou.
- **CPF nunca é perguntado 2x** (issue #171) — o subgrafo `cadastroPessoa` reaproveita `state.cpf` já coletado por `identificarAssistido`, só pergunta nome, data de nascimento e endereço.
- **Endereço no cadastro** (issue #176) — achado ao vivo: pessoa cadastrada sem endereço pode não ter órgão disponível na consulta de violência doméstica, mesmo em casos que normalmente teriam fallback. `coletarEndereco` sempre roda depois da data de nascimento, antes do `POST /integra/pessoa`.
- **CEP-first no endereço** (issue #176) — `GET /cep/{cep}` pode devolver logradouro/bairro/município/UF prontos em texto, não só os ids; quando vem, `coletarEndereco` pula a pergunta daquele campo (mesmo racional de "não pergunta o que já sabe" do CPF pré-preenchido). Não é garantido pra todo CEP — achado ao vivo (issue #127) que alguns vêm incompletos (só UF, por exemplo); nesse caso volta a perguntar o que faltou. Número nunca vem do CEP (é do imóvel, não da rua) — sempre perguntado, junto com complemento (sempre opcional).

## Dados do Verde usados

- `GET /pessoa?cpf=` — `idPessoa`, `nome`, `nomeSocial`, `genero`, `endereco`, `enderecoDetalhado.cep`.
- `GET /cep/{cep}` — ids (`idUf`/`idBairro`/`idMunicipio`) e, quando cadastrados, texto (`uf`/`bairro`/`municipio`/`logradouro`) (issue #127; podem vir incompletos mesmo com o CEP existindo, quando a Verde não tem todo detalhe cadastrado — usado por `coletarEndereco`, issue #176, pra não perguntar de novo o que já veio).
- `GET /plantao/vigente` — lista de plantões ativos agora.
- `GET /orgao/violencia-domestica?indicacaoRO=&idPessoa=` (ou `/orgao/plantao/violencia-domestica` em horário de plantão) — órgão(s) de destino, em ordem de prioridade.
- `POST /encaminhamento/encaminhar` — cria o encaminhamento real.
- `POST /integra/pessoa` (issue #171, endereço na #176) — cadastra pessoa nova quando CPF não encontrado. Nome, CPF, data de nascimento e endereço completo.

Ver `docs/integracao-verde.md` pros detalhes de cada chamada (shapes de resposta, bugs já encontrados).
