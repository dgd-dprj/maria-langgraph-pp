// Tolerância de respostas a perguntas sim_nao, compartilhada por todos os nós
// de fluxo/subgrafo e pela confirmação de TTL (rotas/atendimentos.ts).
//
// O contrato com a Tykhe prevê "true"/"false" crus, mas na prática ela às
// vezes repassa o texto que a pessoa digitou/clicou ("Sim"/"Não", com acento
// e maiúscula variáveis) — achado ao vivo 2026-08-31, quando "Sim" literal
// caía em `resposta === "true"` e virava não. O bridge do WhatsApp (#198)
// sempre repassa texto digitado. Issue #227: era duplicado em 4 grafos e a
// confirmação de TTL não usava; agora é uma função só.

export function normalizarResposta(resposta: string): string {
  return resposta
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "") // remove acentos (ã→a, ó→o...)
    .trim()
    .toLowerCase();
}

const SIM = new Set(["true", "sim", "s", "yes"]);
const NAO = new Set(["false", "nao", "n", "no"]);

export function respostaEhSim(resposta: string): boolean {
  return SIM.has(normalizarResposta(resposta));
}

export function respostaEhNao(resposta: string): boolean {
  return NAO.has(normalizarResposta(resposta));
}
