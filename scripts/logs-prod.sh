#!/bin/sh
# aws logs tail --follow trava/demora demais nesta versão do CLI (testado ao
# vivo — sem --follow ele é instantâneo). Poll manual: cada volta busca só a
# janela desde a última, sem repetir linha.
#
# Migração (spec 08, D-3): em develop, o pino-pretty vinha do node_modules pelo
# `pnpm logs:prod`. Aqui não há node_modules, então ele roda pelo npx, com a
# versão fixa de develop. Antes do laço, o script confere o que precisa e diz o
# que falta: é ferramenta de diagnóstico, e falhar com "command not found" no
# meio de uma investigação é o pior momento.
#
# O stderr do `aws logs tail` continua indo para /dev/null, como em develop: uma
# credencial vencida não mostra erro, só nenhuma linha (achado B3, decisão em aberto).
PINO_PRETTY="pino-pretty@13.1.3"

falta() {
  echo "logs-prod.sh: $1" >&2
  exit 1
}

command -v node >/dev/null 2>&1 || falta "precisa do Node.js: o pino-pretty, que formata o log, roda pelo npx. Instale o Node.js 22 ou mais novo (https://nodejs.org)."
command -v npx >/dev/null 2>&1 || falta "precisa do npx, que vem com o Node.js. Reinstale o Node.js ou confira se a pasta dele está no PATH."
command -v aws >/dev/null 2>&1 || falta "precisa do AWS CLI v2, com a mesma credencial usada em qualquer comando aws local (https://aws.amazon.com/cli/)."
npx --yes "$PINO_PRETTY" --version >/dev/null 2>&1 || falta "não consegui obter o $PINO_PRETTY pelo npx. A primeira execução baixa o pacote: confira a conexão com a internet, ou um proxy que bloqueie o registro do npm."

LAST=$(date -u -d '30 seconds ago' +%Y-%m-%dT%H:%M:%S)
while true; do
  NOW=$(date -u +%Y-%m-%dT%H:%M:%S)
  aws logs tail /ecs/maria-langgraph-pp/api --since "$LAST" --region us-east-1 2>/dev/null | sed 's/^[^{]*//' | npx --yes "$PINO_PRETTY"
  LAST=$NOW
  sleep 3
done
