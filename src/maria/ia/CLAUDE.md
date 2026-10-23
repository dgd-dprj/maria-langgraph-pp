# IA (Bedrock) — regras sempre válidas

Toda chamada aqui vai pro Bedrock de verdade (custo real por request) quando `APP_ENV != "test"` e há credencial AWS configurada.

## Nunca

- Logar o prompt/resposta completo quando ele contém dado sensível (CPF, RG, nome/endereço de vítima de violência doméstica ou pessoa presa) — log de negócio usa `chatId`/`fluxoId` pra correlação, não o conteúdo.
- Remover o caminho mock (`APP_ENV == "test"` cai em resposta fake, nunca chama o Bedrock de verdade) — é o que mantém o `pytest` sem custo e sem dependência de rede/credencial.
- Adicionar uma nova função de IA sem esse mesmo padrão de mock em teste.
- Trocar `invocar_estruturado` por `with_structured_output` com classe Pydantic: ele valida a saída, e a versão TypeScript não validava, o que a tradução reproduz (#212). A mudança de comportamento tem de ser decidida naquela issue, não de passagem.

## Sempre

- Testar mudança de prompt com uma chamada real (via ambiente com credencial, `uv run pytest -m integracao tests/integracao/ia`) antes de assumir que o comportamento mudou como esperado — resposta de LLM não é 100% determinística.
- Contar requisições num Bedrock falso (`tests/ia/conftest.py`) ao mexer em retry, prazo ou cota: o efeito, e não o valor do parâmetro, é o que precisa bater com a versão TypeScript (régua da migração, #208).
