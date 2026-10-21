"""Gera `.sonda/coletar-sonda.ts` no worktree de develop a partir do script original (spec 08, seção 7).

O script de develop exige DATABASE_URL, e a máquina da conferência não tem Postgres. A cópia
sonda muda só o necessário para rodar com as stores em memória e devolver o que gravou:
1. tira a guarda de DATABASE_URL;
2. antes do `main`, cadastra os planejados do cenário na store em memória (`semear`);
3. depois do `main`, grava as perguntas e os assuntos de cada flow num arquivo (`despejar`).

Cada troca é exata (o texto original precisa aparecer uma vez) e o diff é impresso.

Uso: python gerar_sonda.py <worktree de develop>
"""

import difflib
import sys
from pathlib import Path

raiz = Path(sys.argv[1])
original = (raiz / "scripts" / "coletarArvorePerguntasVerde.ts").read_text(encoding="utf-8").replace("\r\n", "\n")

TROCAS = [
    (
        'import { listarFluxosPlanejados } from "../src/shared/fluxosPlanejadosDb.js";\n',
        'import { listarFluxosPlanejados, adicionarPlanejadoDeTeste } from "../src/shared/fluxosPlanejadosDb.js";\n'
        'import { writeFileSync } from "node:fs";\n',
    ),
    (
        '  if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL obrigatório — sem isso o resultado do crawl não fica salvo em lugar nenhum");\n',  # noqa: E501
        "  // sonda: guarda de DATABASE_URL removida (stores em memória)\n",
    ),
    (
        "main().catch((erro) => {\n",
        """// sonda: cadastra os planejados do cenário e despeja o que foi gravado
const planejadosDoCenario = JSON.parse(process.env.CENARIO_PLANEJADOS ?? "[]");
async function semear(): Promise<void> {
  for (const f of planejadosDoCenario) await adicionarPlanejadoDeTeste(f);
}
async function despejar(): Promise<void> {
  const store = await obterPerguntasStore();
  const saida: Record<string, unknown> = {};
  for (const id of [ID_VIOLENCIA_DOMESTICA, ...planejadosDoCenario.map((f: { id: string }) => f.id)]) {
    const perguntas = (await store.listarPerguntasPorFlow(id)).map(({ id: _id, ...resto }) => resto);
    saida[id] = { perguntas, assuntos: await store.listarAssuntosPorFlow(id) };
  }
  writeFileSync(process.env.DUMP_ARQUIVO as string, JSON.stringify(saida));
}

semear().then(main).then(despejar).catch((erro) => {
""",
    ),
]

sonda = original
for antigo, novo in TROCAS:
    assert sonda.count(antigo) == 1, antigo
    sonda = sonda.replace(antigo, novo)

destino = raiz / ".sonda" / "coletar-sonda.ts"
destino.parent.mkdir(exist_ok=True)
destino.write_text(sonda, encoding="utf-8", newline="\n")
sys.stdout.writelines(
    difflib.unified_diff(
        original.splitlines(True), sonda.splitlines(True), "scripts/coletarArvorePerguntasVerde.ts", ".sonda/coletar-sonda.ts"
    )
)
