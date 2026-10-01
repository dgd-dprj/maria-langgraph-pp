#!/usr/bin/env node
// PreToolUse (Edit|Write) — bloqueia edição em arquivo que provavelmente
// guarda segredo real. Falha aberto (nunca bloqueia por engano de parse):
// qualquer erro inesperado deixa passar (exit 0), só bloqueia (exit 2)
// quando o path bate com um padrão conhecido.
const PADROES_SENSIVEIS = [
  /(^|\/)\.env(\..+)?$/,
  /\.pem$/,
  /\.key$/,
  /credentials.*\.json$/i,
  /id_rsa/,
];

let entrada = "";
process.stdin.on("data", (c) => (entrada += c));
process.stdin.on("end", () => {
  try {
    const dados = JSON.parse(entrada);
    const caminho = dados?.tool_input?.file_path || "";
    if (PADROES_SENSIVEIS.some((p) => p.test(caminho))) {
      console.error(
        `Bloqueado: edição em arquivo sensível (${caminho}). Se for legítimo, edite fora do Claude Code.`,
      );
      process.exit(2);
    }
  } catch {
    // parse falhou — não é motivo pra bloquear, deixa passar.
  }
  process.exit(0);
});
