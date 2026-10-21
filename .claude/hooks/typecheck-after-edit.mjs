#!/usr/bin/env node
// PostToolUse (Edit|Write) — depois de editar um .py, roda o typecheck do
// projeto (mypy) e reporta erro na hora (feedback imediato, sem esperar o CI).
// Só roda se o arquivo editado for .py; qualquer outra extensão sai cedo.
// Continua em Node depois da migração para Python (#208): o hook é do Claude
// Code, não da aplicação, e não depende do ferramental removido.
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
  if (!caminho.endsWith(".py")) process.exit(0);

  try {
    execSync("uv run mypy", { cwd: dados.cwd || process.cwd(), stdio: "pipe" });
    process.exit(0);
  } catch (erro) {
    const saida = (erro.stdout?.toString() || "") + (erro.stderr?.toString() || "");
    console.error(`typecheck falhou depois da edição em ${caminho}:\n${saida}`);
    process.exit(2);
  }
});
