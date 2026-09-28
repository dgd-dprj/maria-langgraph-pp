// Shape do campo `metadados` da resposta HTTP pra esse fluxo especificamente
// — mesmo padrão de fluxos/pessoaPresa/api.ts.
import type { DadosPessoa, DadosProcesso, OrgaosViolenciaDomestica } from "../../shared/types.js";

export interface MetadadosViolenciaDomestica {
  ehVitima?: boolean;
  temProcesso?: boolean;
  numeroProcesso?: string;
  dadosProcesso?: DadosProcesso;
  temRegistroOcorrencia?: boolean;
  dadosPessoa?: DadosPessoa;
  orgaosViolenciaDomestica?: OrgaosViolenciaDomestica;
  tipoEncaminhamento?: string;
  motivoHandoff?: string;
  // só presente quando o encaminhamento real (POST no Verde) deu certo —
  // "protocolo" que a mensagem final também cita.
  encaminhamentoId?: number;
}

const enderecoOrgaoSchema = {
  type: "object",
  properties: {
    logradouro: { type: "string" },
    numero: { type: "string" },
    complemento: { type: "string" },
    cep: { type: "string" },
    bairro: { type: "string" },
    municipio: { type: "string" },
    uf: { type: "string" },
    idLocalAtendimento: { type: "number" },
  },
} as const;

export const metadadosSchemaViolenciaDomestica = {
  type: "object",
  properties: {
    ehVitima: { type: "boolean" },
    temProcesso: { type: "boolean" },
    numeroProcesso: { type: "string" },
    dadosProcesso: {
      type: "object",
      properties: {
        encontrado: { type: "boolean" },
        id: { type: "number" },
        origem: { type: "string" },
        instancia: { type: "number" },
        nomeAssunto: { type: "string" },
        nomeOrgaoJulgador: { type: "string" },
        movimentos: {
          type: "array",
          items: {
            type: "object",
            properties: {
              titulo: { type: "string" },
              data: { type: "string" },
              descricao: { type: "string" },
              traducao: { type: "string" },
            },
          },
        },
      },
    },
    temRegistroOcorrencia: { type: "boolean" },
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
    orgaosViolenciaDomestica: {
      type: "object",
      properties: {
        encontrado: { type: "boolean" },
        contactarCrc: { type: "boolean" },
        mensagemCrc: { type: "string" },
        orgaos: {
          type: "array",
          items: {
            type: "object",
            properties: {
              id: { type: "number" },
              nome: { type: "string" },
              enderecos: { type: "array", items: enderecoOrgaoSchema },
            },
          },
        },
      },
    },
    tipoEncaminhamento: { type: "string", enum: ["padrao", "urgente"] },
    motivoHandoff: { type: "string", enum: ["nao_e_vitima", "sem_orgao_disponivel", "falha_encaminhamento", "falha_cadastro", "assistido_nao_confirmado"] },
    encaminhamentoId: { type: "number" },
  },
} as const;

export function extrairMetadadosViolenciaDomestica(values: Record<string, unknown>): MetadadosViolenciaDomestica {
  const v = values as {
    ehVitima?: boolean;
    temProcesso?: boolean;
    numeroProcesso?: string;
    dadosProcesso?: DadosProcesso;
    temRegistroOcorrencia?: boolean;
    dadosPessoa?: DadosPessoa;
    orgaosViolenciaDomestica?: OrgaosViolenciaDomestica;
    tipoEncaminhamento?: string;
    motivoHandoff?: string;
    encaminhamentoId?: number;
  };
  return {
    ehVitima: v.ehVitima,
    temProcesso: v.temProcesso,
    numeroProcesso: v.numeroProcesso,
    dadosProcesso: v.dadosProcesso,
    temRegistroOcorrencia: v.temRegistroOcorrencia,
    dadosPessoa: v.dadosPessoa,
    orgaosViolenciaDomestica: v.orgaosViolenciaDomestica,
    ...(v.tipoEncaminhamento ? { tipoEncaminhamento: v.tipoEncaminhamento } : {}),
    ...(v.motivoHandoff ? { motivoHandoff: v.motivoHandoff } : {}),
    ...(v.encaminhamentoId !== undefined ? { encaminhamentoId: v.encaminhamentoId } : {}),
  };
}

// Cada desfecho do grafo (graph.ts) seta um destes como mensagemFinal no
// state — rotas/atendimentos.ts usa esse campo em vez do texto genérico
// abaixo (ver montarRespostaAtendimento). A mensagem de encaminhamento em si
// (padrão/urgente) é montada dinamicamente em graph.ts::montarMensagemEncaminhamento,
// usando o nome/endereço real do órgão devolvido pelo Verde — só os 2
// desfechos "sem ação de negócio" (não é vítima, sem órgão) têm texto fixo.
export const MENSAGEM_NAO_VITIMA =
  "Esse atendimento é destinado apenas para quem é vítima da violência. Vou encaminhar você para um atendente humano.";
export const MENSAGEM_SEM_ORGAO_DISPONIVEL =
  "Não encontrei um órgão disponível pra encaminhar seu caso agora. Por favor, ligue 129 pra Central de Relacionamento com o Cidadão.";
// Achou o órgão certo, mas o POST de encaminhamento de verdade (Verde)
// falhou — não afirma que deu certo, evita passar informação falsa.
export const MENSAGEM_FALHA_ENCAMINHAMENTO =
  "Identifiquei o órgão certo pro seu caso, mas tive um problema técnico ao registrar o encaminhamento. Vou passar seu atendimento pra equipe confirmar manualmente.";
// Issue #171 — CPF esgotou tentativas (não encontrado) e o cadastro novo
// no Verde (subgrafo cadastroPessoa) também falhou. Substitui o antigo
// MENSAGEM_CPF_NAO_ENCONTRADO (issue #72) — antes esgotar tentativas já
// virava esse handoff direto; agora só chega aqui se o cadastro em si
// não deu certo.
export const MENSAGEM_FALHA_CADASTRO =
  "Não consegui localizar nem cadastrar seus dados no sistema. Vou encaminhar seu atendimento pra um atendente confirmar manualmente.";

// Fallback genérico exigido pelo contrato FluxoConfig (fluxos/index.ts) —
// todo desfecho real deste fluxo seta mensagemFinal (acima), então isso só
// entraria em jogo num estado inesperado/bug.
export const MENSAGEM_CONCLUIDO = "Vou seguir com o encaminhamento do seu atendimento.";
export const MENSAGEM_HANDOFF = "Vou encaminhar seu atendimento para um atendente humano.";
