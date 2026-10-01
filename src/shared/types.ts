// Tipos compartilhados entre fluxos (fluxos/*) e integrações (integracoes/*)
// — não pertencem a um fluxo específico, então não moram dentro de
// fluxos/<nome>/state.ts.

export interface Pergunta {
  pergunta: string;
  tipo: "texto" | "sim_nao" | "opcoes";
  opcoes?: string[];
}

export interface DadosApenado {
  encontrado: boolean;
  idSeap?: number;
  idPessoa?: number;
  nome?: string;
  situacao?: string;
  // confirmados ao vivo 2026-09-09 — Verde já devolve os dois no /apenado,
  // só não eram capturados (ver integracoes/verde.ts). Usados no payload de
  // encaminhamento pro fluxo prisional (Origem do Processo, Tipo de preso,
  // Regime, etc).
  tipoPreso?: string;
  regime?: string;
}

export interface MovimentoProcesso {
  titulo?: string;
  data?: string;
  descricao?: string;
  // explicação em linguagem simples pro cidadão — vem pronta do Verde,
  // não é gerada por nós.
  traducao?: string;
}

export interface DadosProcesso {
  encontrado: boolean;
  id?: number;
  origem?: string;
  instancia?: number;
  nomeAssunto?: string;
  nomeOrgaoJulgador?: string;
  movimentos?: MovimentoProcesso[];
}

// Issue #127 — só ids + CEP (sem os textos de logradouro/bairro/município/uf,
// que a Verde já devolve em /pessoa mas ninguém usa em lógica do fluxo).
// idUf vem sempre; idBairro/idMunicipio ficam undefined quando a Verde não
// tem esse dado cadastrado pro CEP (achado ao vivo 2026-09-21).
export interface EnderecoDetalhado {
  cep?: string;
  idUf?: number;
  idBairro?: number;
  idMunicipio?: number;
}

export interface DadosPessoa {
  encontrado: boolean;
  idPessoa?: number;
  nome?: string;
  nomeSocial?: string;
  genero?: string;
  endereco?: string;
  enderecoDetalhado?: EnderecoDetalhado;
}

// Issue #127 — GET /cep/{cep} na Verde, separado de /pessoa. idBairro/
// idMunicipio ficam undefined quando a Verde não tem esse dado pro CEP
// (não é regra geral da API — CEP a CEP, alguns vêm completos, outros não).
// Issue #176 — campos de TEXTO (uf/bairro/municipio/logradouro) também
// vêm na resposta quando cadastrados, além dos ids — usado pelo subgrafo
// coletarEndereco pra não perguntar de novo o que a Verde já sabe.
export interface DadosCep {
  encontrado: boolean;
  idUf?: number;
  idBairro?: number;
  idMunicipio?: number;
  uf?: string;
  bairro?: string;
  municipio?: string;
  logradouro?: string;
}

export interface HorarioUrgencia {
  diaDaSemana?: string;
  horaInicio?: string;
  horaFim?: string;
  informacaoComplementar?: string;
}

export interface EnderecoOrgao {
  logradouro?: string;
  numero?: string;
  complemento?: string;
  cep?: string;
  bairro?: string;
  municipio?: string;
  uf?: string;
  // usado no POST /integra/encaminhamento/encaminhar como idLocalAtendimento
  // do órgão escolhido — ver criarEncaminhamentoViolenciaDomestica.
  idLocalAtendimento?: number;
  horariosUrgencia?: HorarioUrgencia[];
  horariosAtendimentoFormatado?: string;
  horariosUrgenciaFormatado?: string;
}

export interface OrgaoAtendimento {
  id: number;
  nome: string;
  enderecos?: EnderecoOrgao[];
}

export interface OrgaosViolenciaDomestica {
  encontrado: boolean;
  // Verde já devolve em ordem de prioridade — o primeiro item é sempre o
  // escolhido (ver fluxos/violenciaDomestica/graph.ts).
  orgaos: OrgaoAtendimento[];
  // true só quando indicacaoRO:true e o Verde não achou nenhum órgão — regra
  // deles, RO:false sempre tem fallback (NUDEM > núcleo 1º atendimento > DP
  // única). mensagemCrc vem pronta do Verde ("...ligar 129").
  contactarCrc?: boolean;
  mensagemCrc?: string;
}

// GET /integra/plantao/vigente — sem parâmetros, lista plantões ativos AGORA.
// Vazio = fora de horário de plantão (fluxo normal). Não vazio = usa
// consultarOrgaosPlantaoViolenciaDomestica em vez da consulta normal (regra
// de órgão muda em plantão — ver fluxos/violenciaDomestica/graph.ts).
export interface Plantao {
  id: number;
  tipo?: string;
}

export interface ResultadoEncaminhamento {
  sucesso: boolean;
  // preenchido só quando sucesso:true — id do encaminhamento criado de
  // verdade no Verde, vira parte da mensagem final (protocolo).
  id?: number;
  // preenchido só quando sucesso:false.
  erro?: string;
}

// Issue #171 — cadastro de pessoa nova no Verde (POST /integra/pessoa),
// usado pelo subgrafo subgrafos/cadastroPessoa/ quando o CPF informado não
// tem cadastro. Mesmo padrão de ResultadoEncaminhamento (sucesso/erro).
export interface ResultadoCadastroPessoa {
  sucesso: boolean;
  // preenchido só quando sucesso:true — idPessoa criado de verdade no Verde.
  idPessoa?: number;
  // preenchido só quando sucesso:false.
  erro?: string;
}
