// Issue #225 — tipos de caso que a Tykhe já atende com fluxo próprio. O
// orquestrador classifica o relato entre eles (e os fluxos implementados,
// pessoa presa e violência doméstica), mas NÃO conduz: devolve
// `status: "redirecionado"` + `tipoCaso` e a Tykhe continua o atendimento.
// Enquanto um tipo não migra para a Maria, ele mora aqui; migrar = virar um
// fluxo em fluxosPorId (fluxos/index.ts) e sair desta lista.
//
// `tipoCaso` é o valor do contrato com a Tykhe (docs/contrato-tykhe.md):
// trocar ou acrescentar um valor é mudança de contrato, combinada antes.
// `id` é o identificador no catálogo de classificação (embeddings e enum
// da IA), com prefixo para nunca colidir com o uuid de um fluxo.

export type TipoCasoTykhe = "saude" | "novo-processo" | "andamento-processo" | "agendamentos" | "ajuda-app" | "outros" | "sair";

export interface TipoTykhe {
  id: string;
  tipoCaso: TipoCasoTykhe;
  nome: string;
  // Lida pela IA e pelo embedding para classificar — mesmo papel de
  // FluxoConfig.descricao. Inclui as formas como a pessoa costuma escrever.
  descricao: string;
  // Frase de transição devolvida em `resposta`; a Tykhe decide se exibe.
  mensagem: string;
}

export const TIPOS_TYKHE: TipoTykhe[] = [
  {
    id: "tykhe:saude",
    tipoCaso: "saude",
    nome: "questoes-de-saude",
    descricao:
      "Questões de saúde: pedido de remédio, medicamento, exame, cirurgia, internação, vaga em UTI ou CTI, tratamento, fralda, leite especial, prótese, cadeira de rodas, transferência de hospital, plano de saúde que negou cobertura, erro médico, prontuário médico.",
    mensagem: "Entendi. Vou te encaminhar para o atendimento de questões de saúde.",
  },
  {
    id: "tykhe:novo-processo",
    tipoCaso: "novo-processo",
    nome: "iniciar-novo-processo",
    descricao:
      "Quer iniciar um novo processo ou abrir um caso novo na Defensoria sobre um problema que ainda não tem processo: pensão alimentícia, divórcio, guarda, visita, inventário, imóvel, aluguel, dívida, consumidor, banco, indenização, documentos, entre outros assuntos cíveis e de família.",
    mensagem: "Entendi. Vou te encaminhar para o atendimento de abertura de um novo caso.",
  },
  {
    id: "tykhe:andamento-processo",
    tipoCaso: "andamento-processo",
    nome: "ver-andamento-do-processo",
    descricao:
      "Quer saber o andamento, a situação ou novidades de um processo que já existe: número do processo, audiência marcada, sentença, decisão do juiz, prazo, intimação ou citação recebida sobre um processo em curso.",
    mensagem: "Entendi. Vou te encaminhar para a consulta do andamento do seu processo.",
  },
  {
    id: "tykhe:agendamentos",
    tipoCaso: "agendamentos",
    nome: "ver-meus-agendamentos",
    descricao:
      "Quer consultar, confirmar, remarcar ou cancelar um agendamento ou atendimento marcado na Defensoria: data, horário, endereço do núcleo, comparecimento.",
    mensagem: "Entendi. Vou te encaminhar para os seus agendamentos.",
  },
  {
    id: "tykhe:ajuda-app",
    tipoCaso: "ajuda-app",
    nome: "ajuda-app-defensoria-rj",
    descricao:
      "Dúvida ou dificuldade com o aplicativo Defensoria RJ ou com o canal digital: não consegue acessar, cadastro, senha, erro no app, como usar, onde encontrar uma função. Também perguntas gerais sobre como funciona a Defensoria.",
    mensagem: "Entendi. Vou te encaminhar para a ajuda com o aplicativo Defensoria RJ.",
  },
  {
    id: "tykhe:outros",
    tipoCaso: "outros",
    nome: "outros-assuntos",
    descricao: "Outros assuntos que não se encaixam nas demais opções.",
    mensagem: "Entendi. Vou te encaminhar para o atendimento de outros assuntos.",
  },
  {
    id: "tykhe:sair",
    tipoCaso: "sair",
    nome: "sair",
    descricao: "A pessoa quer encerrar ou sair da conversa: tchau, encerrar, sair, não quero mais, obrigado era só isso.",
    mensagem: "Tudo bem. Quando precisar, é só chamar.",
  },
];

const porId = new Map(TIPOS_TYKHE.map((t) => [t.id, t]));

export function tipoTykhePorId(id: string): TipoTykhe | undefined {
  return porId.get(id);
}

export function tipoTykhePorCaso(tipoCaso: TipoCasoTykhe): TipoTykhe {
  return TIPOS_TYKHE.find((t) => t.tipoCaso === tipoCaso) as TipoTykhe;
}
