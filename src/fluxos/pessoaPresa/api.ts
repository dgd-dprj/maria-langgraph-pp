// Shape do campo `metadados` da resposta HTTP pra esse fluxo especificamente
// (schema Swagger + extrator a partir do `values` do grafo) — cada fluxo tem
// o seu, plugado em rotas/atendimentos.ts via registrarRotasAtendimento().
import type { DadosApenado, DadosPessoa, DadosProcesso } from "../../shared/types.js";

// Recortes de DadosProcesso/DadosApenado — só os campos que outro sistema
// vai consumir de verdade (payload de encaminhamento do fluxo prisional:
// Origem do Processo, Nome, idProcesso, RG, Situação, Tipo de preso, Regime,
// idPessoa, idSeap). Decisão 2026-09-09: dadosProcesso/dadosApenado
// COMPLETOS (movimentos, instancia, nomeAssunto, nomeOrgaoJulgador,
// encontrado) tinham campo demais expostos sem necessidade — corta aqui,
// não no tipo interno (DadosProcesso/DadosApenado seguem completos pra
// quem usa dentro do grafo).
export interface DadosProcessoResumo {
  id?: number;
  origem?: string;
}

export interface DadosApenadoResumo {
  idSeap?: number;
  idPessoa?: number;
  nome?: string;
  situacao?: string;
  tipoPreso?: string;
  regime?: string;
}

export interface MetadadosPessoaPresa {
  parentesco?: string;
  temProcesso?: boolean;
  numeroProcesso?: string;
  dadosProcesso?: DadosProcessoResumo;
  rg?: string;
  dadosApenado?: DadosApenadoResumo;
  // Issue #183 — identificação/cadastro do ASSISTIDO (quem está
  // conversando) no Verde, via CPF — não confundir com dadosApenado acima
  // (o PRESO). Mesmo padrão de fluxos/violenciaDomestica/api.ts: expõe o
  // objeto final resolvido, não os campos transitórios de coleta (cpf/nome/
  // dataNascimento somem dentro de dadosPessoa depois de identificar/
  // cadastrar).
  dadosPessoa?: DadosPessoa;
  motivoHandoff?: string;
}

// Schema JSON (não Zod) — @fastify/swagger dynamic mode lê isso direto dos
// options de cada rota pra montar o /docs. Espelha a interface acima à mão
// (não tem geração automática TS→JSON Schema aqui, repo pequeno/experimental).
export const metadadosSchemaPessoaPresa = {
  type: "object",
  properties: {
    parentesco: { type: "string" },
    temProcesso: { type: "boolean" },
    numeroProcesso: { type: "string" },
    dadosProcesso: {
      type: "object",
      properties: {
        id: { type: "number" },
        origem: { type: "string" },
      },
    },
    rg: { type: "string" },
    dadosApenado: {
      type: "object",
      properties: {
        idSeap: { type: "number" },
        idPessoa: { type: "number" },
        nome: { type: "string" },
        situacao: { type: "string" },
        tipoPreso: { type: "string" },
        regime: { type: "string" },
      },
    },
    dadosPessoa: {
      type: "object",
      properties: {
        encontrado: { type: "boolean" },
        idPessoa: { type: "number" },
        nome: { type: "string" },
        nomeSocial: { type: "string" },
        genero: { type: "string" },
        endereco: { type: "string" },
        enderecoDetalhado: {
          type: "object",
          properties: {
            cep: { type: "string" },
            idUf: { type: "number" },
            idBairro: { type: "number" },
            idMunicipio: { type: "number" },
          },
        },
      },
    },
    motivoHandoff: {
      type: "string",
      enum: [
        "nome_nao_confirmado",
        "rg_nao_encontrado",
        "sem_numero_processo",
        "origem_processo_nao_suportada",
        "dados_pessoa_nao_atendidos",
        "falha_cadastro",
      ],
    },
  },
} as const;

function resumirDadosProcesso(d: DadosProcesso | undefined): DadosProcessoResumo | undefined {
  if (!d) return undefined;
  return { id: d.id, origem: d.origem };
}

function resumirDadosApenado(d: DadosApenado | undefined): DadosApenadoResumo | undefined {
  if (!d) return undefined;
  return { idSeap: d.idSeap, idPessoa: d.idPessoa, nome: d.nome, situacao: d.situacao, tipoPreso: d.tipoPreso, regime: d.regime };
}

export function extrairMetadadosPessoaPresa(values: Record<string, unknown>): MetadadosPessoaPresa {
  const v = values as {
    parentesco?: string;
    temProcesso?: boolean;
    numeroProcesso?: string;
    dadosProcesso?: DadosProcesso;
    rg?: string;
    dadosApenado?: DadosApenado;
    dadosPessoa?: DadosPessoa;
    motivoHandoff?: string;
  };
  return {
    parentesco: v.parentesco,
    temProcesso: v.temProcesso,
    numeroProcesso: v.numeroProcesso,
    dadosProcesso: resumirDadosProcesso(v.dadosProcesso),
    rg: v.rg,
    dadosApenado: resumirDadosApenado(v.dadosApenado),
    dadosPessoa: v.dadosPessoa,
    ...(v.motivoHandoff ? { motivoHandoff: v.motivoHandoff } : {}),
  };
}

export const MENSAGEM_CONCLUIDO =
  "Show! Já confirmei os dados da pessoa presa. Vou seguir com o encaminhamento a partir daqui.";
export const MENSAGEM_HANDOFF =
  "Não consegui confirmar os dados da pessoa presa. Vou encaminhar seu atendimento pra equipe verificar com mais calma.";
// Issue #49 — diferente do MENSAGEM_HANDOFF genérico acima (que soa como
// "não consegui confirmar"), aqui os dados FORAM confirmados (RG, nome,
// parentesco) — só falta o número do processo, que só um atendente
// consegue levantar. Setado como mensagemFinal (não usa o texto genérico).
export const MENSAGEM_HANDOFF_SEM_NUMERO_PROCESSO =
  "Já confirmei os dados da pessoa presa, mas como você não tem o número do processo, vou encaminhar seu atendimento pra equipe localizar isso e dar continuidade.";
// Issue #51 — só processo com origem SEEU é considerado "resolvido" pelo
// bot; origem diferente (ou processo não encontrado na consulta, sem
// origem nenhuma) vira handoff, mesmo com os outros dados confirmados.
export const MENSAGEM_HANDOFF_ORIGEM_NAO_SUPORTADA =
  "Já confirmei os dados da pessoa presa, mas o processo informado tem uma origem que ainda não consigo tratar por aqui. Vou encaminhar seu atendimento pra equipe dar continuidade.";
// Issue #183 — CPF do assistido esgotou tentativas (não encontrado) e o
// cadastro novo no Verde (subgrafo cadastroPessoa) também falhou. Mesmo
// texto/padrão de violenciaDomestica/api.ts::MENSAGEM_FALHA_CADASTRO.
export const MENSAGEM_FALHA_CADASTRO =
  "Não consegui localizar nem cadastrar seus dados no sistema. Vou encaminhar seu atendimento pra um atendente confirmar manualmente.";
