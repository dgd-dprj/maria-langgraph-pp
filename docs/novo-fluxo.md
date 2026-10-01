# Como adicionar um fluxo novo

Cada fluxo é uma pasta autocontida em `src/fluxos/<nome>/` — adicionar um novo não toca nos outros, só registra em `src/fluxos/index.ts`.

## 1. Criar a pasta

```
src/fluxos/<nome>/
  state.ts   # Annotation.Root com o estado do grafo (ver pessoaPresa/state.ts como referência)
  graph.ts   # StateGraph: nós, interrupt() pra cada pergunta, addConditionalEdges pra decisão
  api.ts     # metadadosSchema, extrairMetadados, MENSAGEM_CONCLUIDO, MENSAGEM_HANDOFF
```

- `state.ts` — todo campo que o grafo precisa lembrar entre pausas (`interrupt()`) vira uma `Annotation`. Ver `src/fluxos/pessoaPresa/state.ts`/`violenciaDomestica/state.ts`.
- `graph.ts` — o desenho do grafo É a documentação executável do fluxo de negócio (ver `docs/arquitetura.md`, seção "Por que LangGraph"). Cada nó que precisa perguntar algo à pessoa usa `interrupt()`; decisões usam `addConditionalEdges`. Termina em `statusFinal: "concluido"` ou handoff (ver os 2 fluxos implementados como referência de estrutura).
- `api.ts` — expõe pro resto do sistema: `metadadosSchema` (JSON Schema do que esse fluxo aceita em `dadosConhecidos`), `extrairMetadados(values)` (valida/normaliza esse objeto), `MENSAGEM_CONCLUIDO`/`MENSAGEM_HANDOFF` (textos default — fluxo pode ter mensagens de handoff mais específicas também, ver `MENSAGEM_HANDOFF_SEM_NUMERO_PROCESSO` em pessoaPresa como exemplo).

Fluxo sem implementação própria ainda (categoria só cadastrada em `fluxos_planejados`, issue #26) usa o grafo compartilhado `src/fluxos/padrao/graph.ts` automaticamente — não precisa criar nada até decidir implementar de verdade.

## 1.1. Precisa de lógica reaproveitável entre fluxos? Use um subgrafo

`src/subgrafos/<nome>/` — peça de `StateGraph` reaproveitável, SEM `flowId` próprio, **nunca** chamada direto via HTTP, só embutida como nó dentro de um fluxo (ou de outro subgrafo — `cadastroPessoa` embute `coletarEndereco` dentro dele, subgrafo aninhado). Ver `src/subgrafos/identificarAssistido/`, `src/subgrafos/cadastroPessoa/` (issue #171) e `src/subgrafos/coletarEndereco/` (issue #176) como referência.

```
src/subgrafos/<nome>/
  state.ts   # mesmos NOMES de campo que o fluxo pai que vai embutir — LangGraph
              # compartilha canal automaticamente quando o nome bate, sem nó de
              # "tradução". Sem api.ts (sem metadadosSchema/HTTP próprio).
  graph.ts   # StateGraph normal, mas .compile() SEM checkpointer próprio — a
              # persistência é herdada do checkpointer do grafo PAI. Passar um
              # checkpointer aqui criaria uma 2ª camada desconectada do
              # thread_id real da conversa.
```

No fluxo pai:

```ts
import { grafo as meuSubgrafo } from "../../subgrafos/meuSubgrafo/graph.js";

// campos que o subgrafo escreve (ex: `nome`, `cadastroErro`) precisam existir
// no state.ts do fluxo pai também, com o MESMO nome — senão o subgrafo não
// tem onde escrever quando embutido.

const grafo = new StateGraph(MeuFluxoState)
  // ...
  .addNode("meuSubgrafo", meuSubgrafo) // embute o grafo compilado como nó
  .addConditionalEdges("meuSubgrafo", depoisDoSubgrafo, { /* ... */ })
  // ...
```

Quando pausar/retomar (`interrupt()`) acontece DENTRO do subgrafo, funciona de forma transparente — mesmo `chatId`/checkpoint da árvore toda, sem esforço extra.

## 2. Registrar em `src/fluxos/index.ts`

```ts
export const ID_MEU_FLUXO = "<uuid fixo>"; // gerar 1x, nunca mudar depois (é o flowId público)

export const fluxosPorId: Record<string, FluxoConfig> = {
  // ...existentes...
  [ID_MEU_FLUXO]: {
    nome: "meu-fluxo",
    descricao: "Texto curto em pt-BR descrevendo pra quem/qual situação esse fluxo serve — usado pelo orquestrador (ia/classificarFluxos.ts) pra classificação automática.",
    grafo: grafoMeuFluxo as unknown as GrafoAtendimento,
    metadadosSchema: metadadosSchemaMeuFluxo,
    extrairMetadados: extrairMetadadosMeuFluxo,
    mensagemConcluido: MENSAGEM_CONCLUIDO_MEU_FLUXO,
    mensagemHandoff: MENSAGEM_HANDOFF_MEU_FLUXO,
    // idCategoriaAssuntoVerde: opcional — só se existir categoria equivalente no catálogo do Verde (evita duplicar em fluxos_planejados).
  },
};
```

## 3. Testes

- `graph.test.ts` — invoca o grafo direto (sem HTTP), cobre a lógica de decisão isolada.
- `http.test.ts` — via `app.inject()`, cobre conteúdo/texto de pergunta específico deste fluxo (mecânica genérica de rota já é coberta por `test/app.test.ts`, não duplicar aqui).

Ver `docs/testes.md` pra convenção geral.

## 4. Documentação

- `docs/fluxo-<nome>.md` — mesmo formato de `docs/fluxo-pessoa-presa.md`: passo a passo, tabela de regras de negócio, diagrama (ver seção "Diagrama explicativo" em `docs/padroes-issues.md`/`docs/padroes-pull-request.md` — gerar com o agente `diagram-specialist`, nunca commitar a fonte).
- Linkar o novo doc no `README.md`.

## 5. PR

Uma issue + uma branch (`feat/<numero>-<nome-do-fluxo>`) + um PR, seguindo `CONTRIBUTING.md`.
