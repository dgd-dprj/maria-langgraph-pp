#!/usr/bin/env bash
# Copia o CATÁLOGO do banco de release para docker/catalogo/catalogo-release.sql (#361).
#
# Só 4 tabelas, sem dado de pessoa: fluxos_planejados, perguntas, assuntos_verde e
# flow_assuntos. NUNCA inclua atendimentos nem o schema checkpoint_py (conversas:
# dado pessoal). fluxo_embeddings não é copiada: a API reindexa no boot.
#
# Precisa de pg_dump e de acesso de rede ao RDS de release (VPN/bastion).
#   export CATALOGO_DATABASE_URL='postgresql://usuario:senha@host:5432/banco'
#   scripts/sincronizar_catalogo_release.sh
# A URL fica só na variável de ambiente; o arquivo gerado é ignorado pelo git.
set -euo pipefail

if [[ -z "${CATALOGO_DATABASE_URL:-}" ]]; then
  echo "erro: defina CATALOGO_DATABASE_URL (banco de release)" >&2
  exit 1
fi
command -v pg_dump >/dev/null || { echo "erro: pg_dump não encontrado" >&2; exit 1; }

destino="$(cd "$(dirname "$0")/.." && pwd)/docker/catalogo/catalogo-release.sql"
temporario="$(mktemp)"
trap 'rm -f "$temporario"' EXIT

pg_dump "$CATALOGO_DATABASE_URL" \
  --data-only --column-inserts --on-conflict-do-nothing --no-owner \
  --table=public.fluxos_planejados \
  --table=public.perguntas \
  --table=public.assuntos_verde \
  --table=public.flow_assuntos \
  > "$temporario"

mv "$temporario" "$destino"
trap - EXIT
echo "ok: $destino"
