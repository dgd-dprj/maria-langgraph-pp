#!/usr/bin/env node
// PostToolUse (Edit|Write) — depois de editar um .ts, roda o typecheck do
// projeto e reporta erro na hora (feedback imediato, sem esperar o CI).
// Só roda se o arquivo editado for .ts; qualquer outra extensão sai cedo.
import { execSync } from "node:child_process";

let entrada = "";
process.stdin.on("data", (c) => (entrada += c));
process.stdin.on("end", () => {
  let dados;
  try {
    dados = JSON.parse(entrada);
  } catch {
    process.exit(0);
  }

  const caminho = dados?.tool_input?.file_path || "";
  if (!caminho.endsWith(".ts")) process.exit(0);

  try {
    execSync("pnpm typecheck", { cwd: dados.cwd || process.cwd(), stdio: "pipe" });
    process.exit(0);
  } catch (erro) {
    const saida = (erro.stdout?.toString() || "") + (erro.stderr?.toString() || "");
    console.error(`typecheck falhou depois da edição em ${caminho}:\n${saida}`);
    process.exit(2);
  }
});
