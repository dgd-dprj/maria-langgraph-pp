# Integração com o Verde

Todo o código de chamada ao Verde mora em `src/integracoes/verde.ts`. Base URL de homolog: `https://homologacao.verde.rj.def.br/api/integra`. Autenticação: `Authorization: Bearer <VERDE_JWT_TOKEN>` + `X-Client-ID: <VERDE_CLIENT_ID>`.

**Modo mock**: sem `VERDE_JWT_TOKEN` no ambiente (dev local sem `.env`, ou testes), toda função cai num mock local com CPFs/RGs/números sentinela (`"000000000"` = não encontrado, etc — ver comentário de cada função). Nunca chama a Verde de verdade nesse modo.

## Token expira — renovação automática (issues #113/#187)

`VERDE_JWT_TOKEN` é temporário (emitido como app "Tykhe" pelo Verde). Um workflow agendado (`.github/workflows/verificar-token-verde.yml`) roda diário e:

1. Consulta `GET /autenticacao/token/status` (dados `valido`/`expirado`/`revogado`/`expiraEm`).
2. **Revogado** → falha o workflow direto (`::error::`) — não tem renovação possível, precisa de token novo emitido manualmente na Verde.
3. **Saudável** (mais de 7 dias pro vencimento) → só loga, não faz nada.
4. **Perto de vencer ou já expirado dentro do grace period** (Verde aceita renovar até 5 dias depois de expirado — nesse caso o token só serve pra chamar o refresh, nenhuma outra chamada) → chama `POST /autenticacao/token/refresh`, grava o token novo no Secrets Manager (`aws secretsmanager put-secret-value`) e força redeploy do ECS (`--force-new-deployment`) pra task pegar o valor novo no próximo boot.
5. Refresh falhou (grace period estourado, erro de rede) → falha o workflow, mesmo canal de alerta de antes (e-mail via GitHub Actions).

Esse workflow é o único "dono" da renovação — a aplicação nunca se auto-renova em runtime. Motivo: o serviço roda com múltiplas tasks ECS lendo o MESMO token; se 2 tasks tentassem renovar ao mesmo tempo, a primeira invalidaria o token na hora (regra da própria Verde) e a segunda colidiria. Um único processo agendado como dono evita essa corrida — as tasks só LEEM o token (no boot), nunca escrevem.

## Erros: distinguir "não encontrado" de "token/infra quebrado" — issue #112

Toda chamada passa por `logHttpNaoOk()` quando o HTTP não é 2xx:

| Status | Classificação | Nível de log |
|---|---|---|
| 401, 403 | `auth_ou_infra` (token expirado/inválido) | `error` |
| 5xx | `auth_ou_infra` (problema do lado do Verde) | `error` |
| 404, 422, outros | `nao_encontrado` (dado de negócio genuíno) | `warn` |

Antes dessa distinção existir, um token expirado virava indistinguível de "CPF não encontrado" nos logs — quase fez a gente culpar dado de teste em vez de credencial (achado ao vivo 2026-09-18). Painel no Grafana separa os dois tipos por ambiente/chamada.

## Endpoints usados

### `POST /apenado` (por RG) — pessoa presa

```json
// request: { "rg": "12345678" }
// response (encontrado):
{ "dados": { "idSeap": 1, "idPessoa": 2, "nome": "...", "situacao": "ATIVO", "tipoPreso": "CONDENADO", "regime": "SEMIABERTO" } }
// response (NÃO encontrado): dados é OBJETO VAZIO, não null/ausente
{ "dados": {} }
```

⚠️ **Achado ao vivo (2026-08-28)**: checar só `!corpo.dados` não pega o caso "não encontrado" — `{}` é truthy. O código checa um campo que só existe se achou de verdade (`idPessoa`).

### `GET /processo/consultar/{numero}` — pessoa presa e violência doméstica

```json
{ "dados": { "id": 1, "origem": "SEEU", "instancia": 1, "nomeAssunto": "...", "nomeOrgaoJulgador": "...", "movimentos": [{ "titulo": "...", "data": "...", "descricao": "...", "traducao": "..." }] } }
```

`origem` importa: só `"SEEU"` é considerado "resolvido pelo bot" no fluxo de pessoa presa (issue #51) — qualquer outra origem vira handoff.

### `GET /pessoa?cpf=` — violência doméstica

```json
{
  "dados": {
    "idPessoa": 2861514,
    "nome": "...",
    "nomeSocial": "",
    "genero": "Feminino",
    "endereco": "Rua A, nº 501, ...",
    "enderecoDetalhado": { "cep": "25780000", "bairro": "CENTRO", "municipio": "...", "uf": "RJ", "logradouro": "...", ... }
  }
}
```

⚠️ A Verde devolve `enderecoDetalhado.bairro`/`.municipio`/`.uf`/`.logradouro`/`.numero`/`.complemento` também, mas **só `cep` é lido** — os demais são texto sem id, ninguém usava em lógica de fluxo (issue #127 removeu do nosso tipo — se algo novo precisar do texto, tem que voltar a capturar).

### `GET /cep/{cep}` — violência doméstica (issue #127, texto na #176)

```json
{ "dados": { "uf": { "id": 19, "sigla": "RJ", "nome": "Rio de Janeiro" }, "bairro": { "id": 9948, "nome": "Centro" }, "municipio": { "id": 3643, "nome": "Rio de Janeiro" }, "logradouro": "Rua Exemplo", "numero": null } }
```

Quando cadastrado, `uf`/`bairro`/`municipio` vêm como `{id, nome}` (`sigla` só em `uf`) e `logradouro` como string solta — capturamos tanto o `id` quanto o texto (`idDeCampoCep()`/`nomeDeCampoCep()` em `verde.ts`). Usado por `coletarEndereco` (issue #176) pra não perguntar de novo o que a Verde já sabe.

⚠️ **Achado ao vivo (2026-09-21)**, testando com 2 CEPs reais: `bairro`/`municipio` vieram `null` nos dois — só `uf` veio populado. Não é regra geral da API, é CEP a CEP: outro CEP testado depois (2026-09-25) veio com tudo populado (exemplo acima). O código lê defensivamente (`idDeCampoCep()`/`nomeDeCampoCep()`), sem assumir shape fixo — se vier `null` ou objeto sem `id`/`nome`, só fica `undefined`, não quebra nada; `coletarEndereco` pergunta de volta o que faltou.

### `GET /plantao/vigente` — violência doméstica

Sem parâmetros. `{ "dados": [{ "id": 1, "tipo": "..." }] }` — vazio = fora de plantão.

### `GET /orgao/violencia-domestica?indicacaoRO=&idPessoa=` — violência doméstica

```json
{ "dados": [{ "id": 1226, "nome": "DP ÚNICA DE...", "enderecos": [{ "logradouro": "...", "idLocalAtendimento": 1009, "horariosUrgencia": [...] }] }] }
```

Devolve em **ordem de prioridade** — o código sempre usa `orgaos[0]`. Código especial `"CONTACTAR_CRC"` = "não achei nada, liga 129" (só com `indicacaoRO=true`; sem RO sempre tem fallback do lado do Verde).

### `GET /orgao/plantao/violencia-domestica?idPlantao=&idAssistido=` — violência doméstica, em plantão

⚠️ **Divergência doc x realidade**: o Swagger do Verde documenta `dados` como **objeto único** aqui (diferente do endpoint normal, que é array). O código normaliza os dois formatos (`Array.isArray(bruto) ? bruto : [bruto]`) — não confia 100% na doc depois de já ter visto ela divergir. Qualquer resposta com campo `codigo` (ex: `REQUISICAO_INVALIDA`, visto ao vivo pra assistido sem endereço) é tratada como erro, mesma UX do `CONTACTAR_CRC`.

### `POST /encaminhamento/encaminhar` — violência doméstica, escreve de verdade

```json
// request:
{ "idPessoa": 1, "idOrgao": 1226, "idLocalAtendimento": 1009, "urgencia": true, "preferenciaAtendimento": "Remoto", "fluxoEncaminhamento": "VIOLENCIA_DOMESTICA", "motivoUrgencia": "..." }
// response real (HTTP 201):
{ "dados": { "id": 1177688, "urgente": false } }
```

⚠️ **Bug real corrigido (issue #108, achado ao vivo 2026-09-18)**: o código lia `corpo.id` na **raiz** da resposta — esse campo nunca existiu de verdade, o id vem **aninhado em `dados.id`** (mesmo padrão de pessoa/órgão). Resultado: `id` sempre vinha `undefined`, e **todo** encaminhamento de violência doméstica que chegava até essa etapa terminava em `handoff_humano` (`falha_encaminhamento`) **mesmo com a Verde tendo criado o registro de verdade** (HTTP 201 OK). Provável efeito colateral em produção: encaminhamentos duplicados no Verde (a chamada real deu certo, só a leitura do resultado que estava errada) — vale conferir com o time se aconteceu.

`idAssunto` NÃO é enviado — confirmado com o time do Verde (2026-09-04) que não é necessário pra esse fluxo. `preferenciaAtendimento` sempre `"Remoto"` (é chatbot, não tem atendimento presencial nesse canal).

### `POST /integra/pessoa` — cadastro de pessoa nova (issue #171, endereço na #176)

```json
// request:
{
  "nome": "...", "cpf": "...", "dtNascimento": "...",
  "endereco": { "logradouro": "...", "numero": "...", "complemento": "...", "cep": "...", "bairro": "...", "municipio": "...", "uf": "..." }
}
// response (sucesso):
{ "dados": { "idPessoa": 123456 } }
```

Usado pelo subgrafo `src/subgrafos/cadastroPessoa/` quando o CPF informado não tem cadastro no Verde (depois de esgotar as tentativas de busca por CPF). `endereco` vem do subgrafo `src/subgrafos/coletarEndereco/` (issue #176), embutido dentro do cadastro — **achado ao vivo**: pessoa cadastrada sem endereço pode não ter órgão disponível na consulta de violência doméstica (a consulta de órgão parece depender do endereço cadastrado), mesmo em casos que teriam fallback com endereço presente. `coletarEndereco` consulta `GET /cep/{cep}` primeiro e só pergunta os campos que a Verde não devolveu em texto (ver seção acima) — número e complemento nunca vêm do CEP, sempre perguntados.

`CadastrarPessoaDTO` completo também aceita telefones, gênero, nacionalidade e representante legal — nenhum desses é enviado ainda (decisão registrada na issue #171: chatbot não pede esses dados por enquanto, fica pra melhoria futura).

## RDS Proxy tem allowlist própria — achado configurando o Grafana (issue #83)

Não é sobre a API do Verde em si, mas relevante pra quem for configurar outro acesso ao mesmo Postgres: o **RDS Proxy** que fica na frente do banco (compartilhado com o app) tem uma lista de credenciais autorizadas própria (`Auth`, `AuthScheme: SECRETS`), **separada** das roles que existem de fato no Postgres. Criar uma role no Postgres com `CREATE ROLE` não basta — o proxy rejeita a conexão com `"This RDS proxy has no credentials for the role"` até você registrar um secret (formato `{"username":..., "password":...}`, chaves minúsculas — diferente do formato livre que usamos pros nossos próprios secrets) na allowlist do proxy via `aws rds modify-db-proxy`, e dar `secretsmanager:GetSecretValue` nesse secret pra role IAM que o proxy assume.

## Checklist pra investigar um bug "estranho" no Verde

Pela ordem do que já rendeu confusão real nesta sessão:
1. **É token expirado, não dado ausente?** Confira o campo `tipoErro` no log (`auth_ou_infra` vs `nao_encontrado`) antes de qualquer outra hipótese.
2. **O campo que você espera está mesmo na raiz, ou aninhado em `dados`?** Já teve endpoint com os dois padrões dentro do mesmo arquivo (`encaminhamento` tinha campo na raiz que nunca existiu).
3. **A doc do Swagger bate com a resposta real?** Já teve pelo menos 1 caso documentado como array virando objeto único na prática.
4. **Teste com uma chamada real** antes de mudar código às cegas — via `ecs run-task` com o `VERDE_JWT_TOKEN` que já está no ambiente (não precisa nunca extrair o token pra fora do container pra isso).
