// Extrai os 74 registros do literal DADOS_SEED de develop para scripts/dados/fluxos_planejados.json
// (spec 08, seção 2.2). Quem interpreta as strings é o próprio JavaScript: o literal é avaliado
// num contexto isolado (node:vm), sem acesso a módulos, e a entrada é só a fixture fixada pelo
// id do blob de develop. O teste tests/scripts/test_seed_extracao.py lê a mesma fixture com um
// leitor próprio, em Python, e confere que os dois caminhos concordam.
//
// Uso: node tests/fixtures/scripts/extrair_seed.mjs tests/fixtures/scripts/seedFluxosPlanejados-1157a6d.ts scripts/dados/fluxos_planejados.json
import { readFileSync, writeFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const [fonte, destino] = process.argv.slice(2);
const texto = readFileSync(fonte, "utf8");
const inicio = texto.indexOf("const DADOS_SEED");
const abre = texto.indexOf("[", texto.indexOf("=", inicio));
const fecha = texto.indexOf("\n];", abre);
if (inicio < 0 || abre < 0 || fecha < 0) throw new Error("literal DADOS_SEED não encontrado");
const dados = runInNewContext(`(${texto.slice(abre, fecha + 2)})`, Object.create(null));
writeFileSync(destino, JSON.stringify(dados, null, 2) + "\n", "utf8");
console.log(`${dados.length} registros gravados em ${destino}`);
