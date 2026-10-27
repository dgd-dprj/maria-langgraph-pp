# Como adicionar um fluxo novo

Cada fluxo é uma pasta autocontida em `src/maria/fluxos/<nome>/` — adicionar um novo não toca nos outros, só registra em `src/maria/fluxos/__init__.py`. O nome da pasta é em `snake_case` (é um pacote Python); o nome público do fluxo, no registro, continua em `kebab-case` (`pessoa-presa`).

## 1. Criar a pasta

```
src/maria/fluxos/<nome>/
  __init__.py  # vazio
  state.py     # TypedDict com os canais do grafo (ver pessoa_presa/state.py como referência)
  graph.py     # StateGraph: nós, interrupt() pra cada pergunta, add_conditional_edges pra decisão
  api.py       # extrair_metadados_<nome>, MENSAGEM_CONCLUIDO, MENSAGEM_HANDOFF
```

- `state.py` — uma classe `TypedDict` com `total=False`: todo campo que o grafo precisa lembrar entre pausas (`interrupt()`) vira uma chave. Os nomes dos canais ficam em `camelCase` (`statusFinal`, `mensagemFinal`): são os mesmos nomes que a API devolve e que a versão TypeScript gravava. Além dos campos do fluxo, todo fluxo tem `statusFinal`, `mensagemFinal`, os três `perguntaAtual*` (escritos pelo `preparar_pergunta`) e `tokensGastos: CanalTokensGastos` (`src/maria/shared/tokens_acumulados.py`). Ver `src/maria/fluxos/pessoa_presa/state.py` e `src/maria/fluxos/violencia_domestica/state.py`.
- `graph.py` — o desenho do grafo É a documentação executável do fluxo de negócio (ver `docs/arquitetura.md`, seção "Por que LangGraph"). Cada pergunta é um par de nós: "preparar" (chama `preparar_pergunta`, de `src/maria/ia/reescrever.py`, 1 vez) e "pedir" (lê `perguntaAtualTexto` e pausa em `interrupt({"pergunta": ..., "tipo": "sim_nao" | "texto"})`; a resposta de uma pergunta sim/não vira booleano com `resposta_eh_sim`, de `src/maria/shared/respostas.py`) — ver `docs/ia.md`, seção `reescrever.py`, sobre por que a IA não pode ficar no nó que pausa. Decisões usam `add_conditional_edges`. O grafo termina gravando `statusFinal` (`"concluido"` ou `"handoff_humano"`). O construtor fica no nível do módulo e **não é compilado na importação**: o módulo termina com a fábrica, que compila na primeira chamada com o checkpointer da aplicação:

  ```python
  _fabrica = FabricaGrafo(_construtor)  # de maria.fluxos._fabrica
  criar_grafo = _fabrica.criar  # usado só pelo langgraph.json (Studio)


  def obter_grafo() -> GrafoCompilado:
      return _fabrica.obter()
  ```

- `api.py` — expõe pro resto do sistema: `extrair_metadados_<nome>(values)` (monta os `metadados` da resposta a partir do estado; a ordem das chaves é a ordem do JSON) e `MENSAGEM_CONCLUIDO`/`MENSAGEM_HANDOFF` (textos padrão — o fluxo pode ter mensagens de handoff mais específicas, gravadas em `mensagemFinal`; ver `MENSAGEM_HANDOFF_SEM_NUMERO_PROCESSO` em `pessoa_presa/api.py`). Não há schema de metadados por fluxo: a rota declara `dadosConhecidos` e `metadados` como objetos genéricos (spec 05 da migração, decisão 3).

O que chega no grafo: na criação, o conteúdo de `dadosConhecidos` vira o estado inicial (menos `viaOrquestrador`, que só a rota do orquestrador grava, #191). Chave que não existe no `state.py` é ignorada pelo LangGraph. O `fluxoId` chega na config do run (`contexto_atual()`, de `src/maria/shared/contexto.py`).

Fluxo sem implementação própria ainda (categoria só cadastrada em `fluxos_planejados`, issue #26) usa o grafo compartilhado `src/maria/fluxos/padrao/graph.py` automaticamente — não precisa criar nada até decidir implementar de verdade.

## 1.1. Precisa de lógica reaproveitável entre fluxos? Use um subgrafo

`src/maria/subgrafos/<nome>/` — peça de `StateGraph` reaproveitável, SEM `flowId` próprio, **nunca** chamada direto via HTTP, só embutida como nó dentro de um fluxo (ou de outro subgrafo — `cadastro_pessoa` embute `coletar_endereco` dentro dele, subgrafo aninhado). Ver `src/maria/subgrafos/identificar_assistido/`, `src/maria/subgrafos/cadastro_pessoa/` (issue #171) e `src/maria/subgrafos/coletar_endereco/` (issue #176) como referência.

```
src/maria/subgrafos/<nome>/
  __init__.py  # vazio
  state.py     # mesmos NOMES de canal que o fluxo pai que vai embutir — o LangGraph
               # compartilha o canal automaticamente quando o nome bate, sem nó de
               # "tradução". Sem api.py (sem metadados nem HTTP próprio).
  graph.py     # StateGraph normal, mas compile() SEM checkpointer próprio, no fim
               # do módulo (grafo = _construtor.compile()) — a persistência é herdada
               # do checkpointer do grafo PAI. Passar um checkpointer aqui criaria
               # uma 2ª camada desconectada do thread_id real da conversa.
```

No fluxo pai:

```python
from maria.subgrafos.meu_subgrafo.graph import grafo as subgrafo_meu_subgrafo

# canais que o subgrafo escreve (ex: `nome`, `cadastroErro`) precisam existir
# no state.py do fluxo pai também, com o MESMO nome — senão o subgrafo não
# tem onde escrever quando embutido.

_construtor = StateGraph(MeuFluxoState)
# ...
_construtor.add_node("meuSubgrafo", subgrafo_meu_subgrafo)  # embute o grafo compilado como nó
_construtor.add_conditional_edges("meuSubgrafo", depois_do_subgrafo, {...})
# ...
```

Quando pausar/retomar (`interrupt()`) acontece DENTRO do subgrafo, funciona de forma transparente — mesmo `chatId`/checkpoint da árvore toda, sem esforço extra.

## 2. Registrar em `src/maria/fluxos/__init__.py`

```python
from maria.fluxos.meu_fluxo import api as api_meu_fluxo
from maria.fluxos.meu_fluxo.graph import obter_grafo as obter_grafo_meu_fluxo

ID_MEU_FLUXO = "<uuid fixo>"  # gerar 1x, nunca mudar depois (é o flowId público)

fluxos_por_id: dict[str, FluxoConfig] = {
    # ...existentes...
    ID_MEU_FLUXO: FluxoConfig(
        nome="meu-fluxo",
        descricao="Texto curto em pt-BR descrevendo pra quem/qual situação esse fluxo serve — usado pelo orquestrador (src/maria/ia/classificar_fluxos.py) pra classificação automática.",
        obter_grafo=obter_grafo_meu_fluxo,
        extrair_metadados=api_meu_fluxo.extrair_metadados_meu_fluxo,
        mensagem_concluido=api_meu_fluxo.MENSAGEM_CONCLUIDO,
        mensagem_handoff=api_meu_fluxo.MENSAGEM_HANDOFF,
        # id_categoria_assunto_verde: opcional — só se existir categoria equivalente no catálogo do Verde (evita duplicar em fluxos_planejados).
    ),
}
```

Para gerar o uuid: `uv run python -c "import uuid; print(uuid.uuid4())"`.

O registro já basta para o fluxo aparecer em `GET /fluxos`, aceitar `POST /atendimentos` com o novo `flowId` e entrar no catálogo do orquestrador. Para abrir o grafo no LangGraph Studio, acrescente também a linha `"meu_fluxo": "./src/maria/fluxos/meu_fluxo/graph.py:criar_grafo"` em `langgraph.json`.

> Um fluxo novo entra no catálogo de classificação. Com mais de 10 opções no catálogo, a busca por similaridade passa a cortar candidatos antes da IA (`CANDIDATOS_MAXIMOS`, #256): hoje são 9 (2 fluxos e 7 tipos da Tykhe), então o 2º fluxo novo já muda esse comportamento. Ver `docs/fluxo-orquestrador.md`.

## 3. Testes

- `tests/fluxos/test_<nome>.py` — invoca o grafo direto (sem HTTP), cobre a lógica de decisão isolada. Use a classe `Fluxo` de `tests/fluxos/conftest.py`: `Fluxo(obter_grafo())`, depois `await fluxo.iniciar()` e `await fluxo.responder("sim", ...)`; `texto(resultado)` devolve o texto da pergunta pendente. O `conftest.py` da pasta já abre o checkpointer em memória a cada teste.
- `tests/api/test_fluxos_http.py` — via cliente HTTP sobre o ASGI (fixtures `cliente` e `auth` de `tests/api/conftest.py`), cobre conteúdo/texto de pergunta específico deste fluxo (a mecânica genérica de rota já é coberta por `tests/api/test_app.py`, não duplicar aqui).

Rodar só os testes do fluxo: `uv run pytest tests/fluxos/test_<nome>.py`. Antes do PR, a verificação inteira (`docs/testes.md`).

### O teste de conformidade confere o molde (#323)

`tests/fluxos/test_conformidade.py` roda para todo fluxo de `fluxos_por_id` e para o grafo padrão. O fluxo novo entra sozinho, pelo registro. As 14 regras:

| # | Regra |
|---|---|
| A1 | O estado tem `statusFinal`, e todo fim grava `concluido` ou `handoff_humano` |
| A2 | O estado tem `tokensGastos: CanalTokensGastos` |
| A3 | O estado tem `mensagemFinal`; sem valor, vale a mensagem padrão do registro |
| A4 | Cada pausa manda `pergunta` e `tipo` (`texto` ou `sim_nao`) |
| A5 | Pergunta sim/não leva as opções `["Sim", "Não"]`, e a resposta passa por `resposta_eh_sim` |
| A6 | Cada pergunta é um par: o nó que prepara (`preparar_pergunta`) e o que pede |
| A7 | O nó que prepara e o que pede pulam pela mesma condição |
| A8 | O grafo do fluxo compila na primeira chamada (`FabricaGrafo`), e não na importação |
| A9 | O `api.py` tem `extrair_metadados_<pasta>`, `MENSAGEM_CONCLUIDO` e `MENSAGEM_HANDOFF`, e o registro usa os três |
| A10 | O registro tem id uuid4, nome em kebab-case e descrição não vazia (a descrição só é exigida se `oferecer_ao_orquestrador` for verdadeiro; o padrão é verdadeiro) |
| A11 | Todo encaminhamento para atendimento humano grava `motivoHandoff`, de uma lista fixa do fluxo (`Literal` no `state.py`) |
| A12 | Os subgrafos compilam sem persistência própria e dividem canais com o fluxo pai |
| A13 | Toda saída da IA de uma lista fechada é conferida contra a lista antes de ser gravada (#212) |
| A14 | Falha de infraestrutura do Verde nunca vira resposta de negócio: o fluxo encerra com `motivoHandoff = falha_infra_verde` (#239) |

Além das 14 regras, o teste confere que todo nó chega ao fim e que cada resposta montada passa no esquema do contrato com a Tykhe. Um fluxo sem perguntas, como o padrão, não tem o que conferir nas regras A4 a A7 nem na A11.

O teste lê o fluxo sem executar e depois passeia por ele, respondendo "Sim" ou "Não" a toda pergunta sim/não:
- **sem IA e com o Verde em mock;**
- **com a IA simulada:** a pergunta reescrita leva uma marca, e toda saída de lista fechada vem com um valor inventado, que não pode chegar à resposta;
- **com o Verde falhando numa chamada de cada vez:** 503, tempo esgotado e 401.

**Se o fluxo pergunta algo de texto,** declare em `ROTEIROS`, no próprio teste, as respostas que o passeio dá, por padrão do texto da pergunta. Sem elas, o passeio responde um texto genérico, e uma validação de formato pode prender a conversa: o teste falha em "fim".

**Fluxo novo não tem exceção.** Pessoa presa e violência doméstica ainda não passam na A13 e na A14. As três falhas estão em `EXCECOES`, cada uma ligada à issue que a corrige, e a lista só diminui. Quando a correção entra, o teste falha até a exceção ser apagada.

### O que o registro muda em outros testes

Registrar o fluxo muda a resposta de `GET /fluxos` e o catálogo do orquestrador, e **12 testes que fixam esses dois valores falham** (conferido seguindo este guia com um fluxo de exemplo, 2026-10-20):

- **Listas esperadas no código** — `tests/api/test_app.py` (`GET /fluxos`), `tests/api/test_orquestrador_rota.py` e `tests/fluxos/test_spec_fluxos.py` (o catálogo com os 2 fluxos e os 7 tipos da Tykhe). Atualize a lista esperada para incluir o fluxo novo.
- **Respostas gravadas contra a versão TypeScript** — `tests/fixtures/contrato/http/`, `tests/fixtures/contrato/conferencia-api-pr1/` e `tests/fixtures/contrato/conferencia-api-pr2/` guardam o corpo de `GET /fluxos` com os 2 fluxos, e são conferidas byte a byte por `tests/api/test_contrato.py`, `tests/api/test_conferencia_pr1.py` e `tests/api/test_conferencia_pr2.py`. **Não edite a fixture.** Ela é evidência da tradução, e não teste de regressão: prova o que a versão TypeScript devolvia. O caso afetado sai da conferência, e o comportamento novo ganha um teste escrito. Ver `MIGRACAO.md`, seção "As respostas gravadas são evidência, não teste de regressão".

  **Como tirar os casos da conferência (#321):** aposente os 6 casos abaixo em `tests/api/casos_aposentados.py`. Cada entrada leva a issue do fluxo, o motivo e o teste escrito que confere a lista nova de `GET /fluxos` (por exemplo, o de `tests/api/test_app.py`, que você já atualizou). Esses 6 casos foram medidos com um fluxo de brinquedo (`tests/api/fluxo_de_brinquedo.py`). São todos `GET /fluxos` respondidos com 200, e o teste do brinquedo avisa se a lista mudar.

  | Conferência | Casos |
  |---|---|
  | `contrato` | `fluxos-200` |
  | `pr1` | `fluxos`, `fluxos_query`, `auth_bearer_espacos_fluxos`, `auth_bearer_duplo_espaco_fluxos` |
  | `pr2` | `rota_get_fluxos_codificado` |

  ```python
  CASOS_APOSENTADOS: dict[str, dict[str, CasoAposentado]] = {
      "contrato": {"fluxos-200": CasoAposentado(issue=<n>, motivo="fluxo novo muda a lista de GET /fluxos", teste="tests/api/test_app.py")},
      "pr1": {...},  # os 4 casos da tabela, com a mesma issue
      "pr2": {...},
  }
  ```

  O caso aposentado continua sendo enviado, porque os casos seguintes dependem do estado que ele deixa; só a comparação dele sai. Se um caso aposentado voltar a bater com a gravação, a conferência falha e pede para tirar a entrada. `tests/api/test_casos_aposentados.py` confere o registro: conferência, caso e teste citados precisam existir.

Ver `docs/testes.md` pra convenção geral.

## 4. Documentação

- `docs/fluxo-<nome>.md` — mesmo formato de `docs/fluxo-pessoa-presa.md`: passo a passo, tabela de regras de negócio, diagrama (ver seção "Diagrama explicativo" em `docs/padroes-issues.md`/`docs/padroes-pull-request.md` — gerar com o agente `diagram-specialist`, nunca commitar a fonte).
- Linkar o novo doc no `README.md`.

## 5. PR

Uma issue + uma branch (`feat/<numero>-<nome-do-fluxo>`) + um PR, seguindo `CONTRIBUTING.md`.
