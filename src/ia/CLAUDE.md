# IA (Bedrock) — regras sempre válidas

Toda chamada aqui vai pro Bedrock de verdade (custo real por request) quando `NODE_ENV !== "test"` e há credencial AWS configurada.

## Nunca

- Logar o prompt/resposta completo quando ele contém dado sensível (CPF, RG, nome/endereço de vítima de violência doméstica ou pessoa presa) — log de negócio usa `chatId`/`fluxoId` pra correlação, não o conteúdo.
- Remover o caminho mock (`NODE_ENV === "test"` cai em resposta fake, nunca chama o Bedrock de verdade) — é o que mantém `pnpm test` sem custo e sem dependência de rede/credencial.
- Adicionar uma nova função de IA sem esse mesmo padrão de mock em teste.

## Sempre

- Testar mudança de prompt com uma chamada real (via ambiente com credencial) antes de assumir que o comportamento mudou como esperado — resposta de LLM não é 100% determinística.
