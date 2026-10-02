import type {
  DadosApenado,
  DadosCep,
  DadosPessoa,
  DadosProcesso,
  OrgaoAtendimento,
  OrgaosViolenciaDomestica,
  Plantao,
  ResultadoCadastroPessoa,
  ResultadoEncaminhamento,
} from "../shared/types.js";
import { logger } from "../shared/logger.js";
import { contextoAtual } from "../shared/contexto.js";

// TODO: VERDE_JWT_TOKEN é temporário (emitido como app "Tykhe" pelo Verde,
// expira 2026-09-12) — precisa de credencial própria da Maria antes disso.
const VERDE_API_URL = process.env.VERDE_API_URL ?? "https://homologacao.verde.rj.def.br/api/integra";
const VERDE_JWT_TOKEN = process.env.VERDE_JWT_TOKEN ?? "";
const VERDE_CLIENT_ID = process.env.VERDE_CLIENT_ID ?? "";
// Issue #196 — achado ao vivo: RG que existe de verdade veio "não
// encontrado" porque a chamada estourou o timeout antigo (20s) num dia de
// Verde homolog lenta (levou 13.5s numa chamada direta) — timeout vira
// encontrado:false no catch, indistinguível de "não achou de verdade".
const TIMEOUT_VERDE_MS = 30_000;

// Issue #112 — 401/403 (token expirado/inválido) e 5xx (infra da Verde) são
// bem diferentes de 404/422 (dado de negócio genuinamente não encontrado),
// mas até aqui todo `!res.ok` caía no mesmo logger.warn — token expirado
// virava indistinguível de "CPF não encontrado" nos logs (achado ao vivo
// 2026-09-18, investigando um bug que na real era outra coisa, mas quase
// nos fez perder tempo culpando dado de teste em vez de credencial).
// error (não warn) pra auth_ou_infra dar sinal mais forte pra alerta.
function logHttpNaoOk(chamada: string, status: number, duracaoMs: number, extra: Record<string, unknown> = {}) {
  const tipoErro = status === 401 || status === 403 || status >= 500 ? "auth_ou_infra" : "nao_encontrado";
  const nivel = tipoErro === "auth_ou_infra" ? "error" : "warn";
  logger[nivel](
    { ...contextoAtual(), status, tipoErro, evento: "verde_chamada", chamada, resultado: "nao_ok", duracaoMs, ...extra },
    `[verde] ${chamada}: HTTP não-ok`
  );
}

function ehAuthOuInfra(status: number): boolean {
  return status === 401 || status === 403 || status >= 500;
}

// Issue #172 — 401/403/5xx (auth_ou_infra, já classificado por
// logHttpNaoOk) e exceção de rede/timeout são tratados IGUAL aqui: retry
// automático, mesmo número de tentativas de ia/*.ts (TENTATIVAS_RETRY_IA).
// 404/422 (negócio — dado genuinamente não encontrado) NUNCA retenta, sai
// na 1ª tentativa — é resposta válida da Verde, não falha.
export const TENTATIVAS_RETRY_VERDE = 3;

// `res` fica disponível no caso de falha de NEGÓCIO (404/422) e também na
// última tentativa de uma falha de infra esgotada baseada em status HTTP
// (não numa exceção de rede/timeout, que nunca chega a ter Response) — dá
// pra quem precisa (encaminhamento/cadastroPessoa, que leem `corpo.mensagem`
// do erro) ainda extrair a mensagem real da Verde quando ela existir.
type ResultadoChamadaVerde = { ok: true; res: Response } | { ok: false; res?: Response; falhaInfra: boolean };

// Exportado (não precisa de VERDE_JWT_TOKEN/rede real pra testar) —
// montarRequisicao é injetado pelo chamador, então dá pra testar a lógica
// de retry/classificação isoladamente com um fake, sem mock mode nem HTTP
// de verdade (ver verde.test.ts).
export async function chamarVerdeComRetry(chamada: string, montarRequisicao: () => Promise<Response>): Promise<ResultadoChamadaVerde> {
  for (let tentativa = 1; tentativa <= TENTATIVAS_RETRY_VERDE; tentativa++) {
    const inicio = Date.now();
    try {
      const res = await montarRequisicao();
      const duracaoMs = Date.now() - inicio;
      if (res.ok) return { ok: true, res };
      if (!ehAuthOuInfra(res.status)) {
        logHttpNaoOk(chamada, res.status, duracaoMs);
        return { ok: false, res, falhaInfra: false };
      }
      logHttpNaoOk(chamada, res.status, duracaoMs, { tentativa, tentativasRestantes: TENTATIVAS_RETRY_VERDE - tentativa });
      if (tentativa === TENTATIVAS_RETRY_VERDE) return { ok: false, res, falhaInfra: true };
    } catch (err) {
      const duracaoMs = Date.now() - inicio;
      logger.error(
        { ...contextoAtual(), err, evento: "verde_chamada", chamada, resultado: "erro", duracaoMs, tentativa, tipoErro: "auth_ou_infra" },
        `[verde] ${chamada}: falha na chamada (tentativa ${tentativa})`
      );
      if (tentativa === TENTATIVAS_RETRY_VERDE) return { ok: false, falhaInfra: true };
    }
  }
  /* c8 ignore next */
  return { ok: false, falhaInfra: true }; // inalcançável — loop sempre retorna antes, só pro TS não reclamar de falta de return
}

interface ApenadoResponseVerde {
  codigo?: string;
  mensagem?: string;
  dados?: {
    idSeap?: number;
    nome?: string;
    situacao?: string;
    idPessoa?: number;
    // confirmados ao vivo 2026-09-09 (curl direto no /apenado) — Verde já
    // manda os dois, só não estavam sendo capturados. cpf e unidadePrisional
    // também vêm na resposta real, mas nenhum fluxo precisa deles hoje —
    // não capturados (YAGNI).
    tipoPreso?: string;
    regime?: string;
  };
}

export async function consultarApenadoPorRg(rg: string): Promise<DadosApenado> {
  if (!VERDE_JWT_TOKEN) {
    logger.warn(contextoAtual(), "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)");
    // RG "000000000" simula "não encontrado" no mock (pra testar o fluxo de
    // retry sem depender do Verde real) — qualquer outro RG "acha" a pessoa
    // de teste.
    if (rg === "000000000") return { encontrado: false };
    // Issue #172 — simula falha de infra esgotada (401/403/5xx mesmo depois
    // do retry automático), sentinela separado de "000000000" (não
    // encontrado de verdade) — testa o roteamento pro handoff direto, sem
    // precisar de rede/token real.
    if (rg === "66666666666") return { encontrado: false, falhaInfra: true };
    // situacao/tipoPreso/regime sem sufixo "(mock)" de propósito (issue
    // #57) — concluir() (fluxos/pessoaPresa/graph.ts) compara esses 3
    // campos por igualdade estrita contra o que o Verde real devolve, um
    // sufixo quebraria a comparação em teste.
    //
    // Sentinelas de teste (issue #57 — situação/tipo/regime fora do
    // permitido, ou situação com prefixo "EM" pra testar a normalização),
    // mesmo padrão de "000000000" acima. Qualquer outro RG cai no caso
    // "tudo permitido" (situação ATIVO, tipo CONDENADO, regime SEMIABERTO).
    if (rg === "22222222222") {
      return { encontrado: true, idSeap: 999999, idPessoa: 999999, nome: "Pessoa de Teste (mock)", situacao: "LIBERTADO", tipoPreso: "CONDENADO", regime: "SEMIABERTO" };
    }
    if (rg === "33333333333") {
      return { encontrado: true, idSeap: 999999, idPessoa: 999999, nome: "Pessoa de Teste (mock)", situacao: "ATIVO", tipoPreso: "PROVISÓRIO", regime: "SEMIABERTO" };
    }
    if (rg === "44444444444") {
      return { encontrado: true, idSeap: 999999, idPessoa: 999999, nome: "Pessoa de Teste (mock)", situacao: "ATIVO", tipoPreso: "CONDENADO", regime: "ABERTO" };
    }
    if (rg === "55555555555") {
      return { encontrado: true, idSeap: 999999, idPessoa: 999999, nome: "Pessoa de Teste (mock)", situacao: "EM RESDOM", tipoPreso: "CONDENADO", regime: "FECHADO" };
    }
    return {
      encontrado: true,
      idSeap: 999999,
      idPessoa: 999999,
      nome: "Pessoa de Teste (mock)",
      situacao: "ATIVO",
      tipoPreso: "CONDENADO",
      regime: "SEMIABERTO",
    };
  }
  const inicio = Date.now();
  const resultado = await chamarVerdeComRetry("apenado", () =>
    fetch(`${VERDE_API_URL}/apenado`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${VERDE_JWT_TOKEN}`,
        "x-client-id": VERDE_CLIENT_ID,
      },
      body: JSON.stringify({ rg }),
      signal: AbortSignal.timeout(TIMEOUT_VERDE_MS),
    })
  );
  if (!resultado.ok) return { encontrado: false, ...(resultado.falhaInfra ? { falhaInfra: true as const } : {}) };
  const corpo = (await resultado.res.json()) as ApenadoResponseVerde;
  // RG não encontrado: Verde devolve "dados": {} (objeto VAZIO, não null/
  // ausente — confirmado ao vivo 2026-08-28) — checar só `!corpo.dados`
  // não pega isso, `{}` é truthy. Checa um campo que só existe se achou
  // de verdade.
  logger.info({ ...contextoAtual(), evento: "verde_chamada", chamada: "apenado", resultado: "sucesso", duracaoMs: Date.now() - inicio }, "[verde] apenado: chamada concluída");
  if (!corpo.dados || corpo.dados.idPessoa === undefined) return { encontrado: false };
  return {
    encontrado: true,
    idSeap: corpo.dados.idSeap,
    idPessoa: corpo.dados.idPessoa,
    nome: corpo.dados.nome,
    situacao: corpo.dados.situacao,
    tipoPreso: corpo.dados.tipoPreso,
    regime: corpo.dados.regime,
  };
}

interface ProcessoResponseVerde {
  codigo?: string;
  mensagem?: string;
  dados?: {
    id?: number;
    origem?: string;
    instancia?: number;
    nomeAssunto?: string;
    nomeOrgaoJulgador?: string;
    movimentos?: Array<{ titulo?: string; data?: string; descricao?: string; traducao?: string }>;
  };
}

// Consulta o processo pelo número informado (só chamada quando temProcesso:
// true — ver fluxos/pessoaPresa/graph.ts). Diferente de consultarApenadoPorRg,
// NÃO trava o fluxo: erro/não encontrado só fica registrado em
// dadosProcesso.encontrado, sem retry nem pergunta de "tentar de novo" — é
// informação complementar pra Tykhe, não um gate de identificação.
export async function consultarProcesso(numero: string): Promise<DadosProcesso> {
  if (!VERDE_JWT_TOKEN) {
    logger.warn(contextoAtual(), "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)");
    // Sentinelas de teste (issue #51 — só SEEU é resolvido pelo bot
    // sozinho): número "000000000" simula processo NÃO ENCONTRADO (sem
    // origem nenhuma); "0000000-00.0000.0.00.0000" simula origem NÃO
    // suportada; qualquer outro número "acha" um processo com origem SEEU.
    // origem precisa ser o valor EXATO "SEEU" (sem sufixo "(mock)") porque
    // `concluir()` compara por igualdade estrita contra o que o Verde real
    // devolve.
    if (numero === "000000000") return { encontrado: false };
    if (numero === "0000000-00.0000.0.00.0000") {
      return { encontrado: true, id: 999999, origem: "e-Proc (mock)", nomeAssunto: "Processo de Teste (mock)" };
    }
    return { encontrado: true, id: 999999, origem: "SEEU", nomeAssunto: "Processo de Teste (mock)" };
  }
  const inicio = Date.now();
  const resultado = await chamarVerdeComRetry("processo", () =>
    fetch(`${VERDE_API_URL}/processo/consultar/${encodeURIComponent(numero)}`, {
      method: "GET",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${VERDE_JWT_TOKEN}`,
        "x-client-id": VERDE_CLIENT_ID,
      },
      signal: AbortSignal.timeout(TIMEOUT_VERDE_MS),
    })
  );
  if (!resultado.ok) return { encontrado: false };
  const corpo = (await resultado.res.json()) as ProcessoResponseVerde;
  logger.info({ ...contextoAtual(), evento: "verde_chamada", chamada: "processo", resultado: "sucesso", duracaoMs: Date.now() - inicio }, "[verde] processo: chamada concluída");
  if (!corpo.dados || corpo.dados.id === undefined) return { encontrado: false };
  return {
    encontrado: true,
    id: corpo.dados.id,
    origem: corpo.dados.origem,
    instancia: corpo.dados.instancia,
    nomeAssunto: corpo.dados.nomeAssunto,
    nomeOrgaoJulgador: corpo.dados.nomeOrgaoJulgador,
    movimentos: corpo.dados.movimentos,
  };
}

interface PessoaResponseVerde {
  codigo?: string;
  mensagem?: string;
  dados?: {
    idPessoa?: number;
    nome?: string;
    nomeSocial?: string;
    genero?: string;
    endereco?: string;
    // Issue #127 — só cep é usado (pra alimentar consultarCep); a Verde
    // devolve logradouro/bairro/municipio/uf também, mas ninguém lê isso
    // em lógica do fluxo, e os ids equivalentes vêm de /cep, não daqui.
    enderecoDetalhado?: {
      cep?: string;
    };
  };
}

// Consulta dados do assistido (endereço incluso) pelo CPF — usado pelo fluxo
// violenciaDomestica pra saber o município e decidir capital x outras cidades
// (ver fluxos/violenciaDomestica/graph.ts). CPF aceito com ou sem pontuação,
// a própria API do Verde tolera os dois formatos, sem precisar sanitizar aqui.
export async function consultarPessoaPorCpf(cpf: string): Promise<DadosPessoa> {
  if (!VERDE_JWT_TOKEN) {
    logger.warn(contextoAtual(), "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)");
    // CPF "00000000000" simula "não encontrado" no mock, mesmo padrão do RG
    // "000000000" em consultarApenadoPorRg — qualquer outro CPF "acha" a
    // pessoa de teste, com município Rio de Janeiro (capital).
    if (cpf === "00000000000") return { encontrado: false };
    // Issue #172 — mesmo racional do sentinela "66666666666" em
    // consultarApenadoPorRg: simula falha de infra esgotada, separado de
    // "não encontrado de verdade".
    if (cpf === "66666666666") return { encontrado: false, falhaInfra: true };
    return {
      encontrado: true,
      idPessoa: 999999,
      nome: "Pessoa de Teste (mock)",
      genero: "Feminino",
      endereco: "Rua de Teste, 123 (mock)",
      enderecoDetalhado: { cep: "20000-000" },
    };
  }
  const inicio = Date.now();
  // 404 (CPF não encontrado) e 422 (mais de uma pessoa encontrada) caem no
  // mesmo `encontrado:false` — mesmo tratamento genérico de status não-ok
  // dos outros métodos deste arquivo, sem distinguir motivo (repo pequeno,
  // não vale ramificação extra por enquanto).
  const resultado = await chamarVerdeComRetry("pessoa", () =>
    fetch(`${VERDE_API_URL}/pessoa?cpf=${encodeURIComponent(cpf)}`, {
      method: "GET",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${VERDE_JWT_TOKEN}`,
        "x-client-id": VERDE_CLIENT_ID,
      },
      signal: AbortSignal.timeout(TIMEOUT_VERDE_MS),
    })
  );
  if (!resultado.ok) return { encontrado: false, ...(resultado.falhaInfra ? { falhaInfra: true as const } : {}) };
  const corpo = (await resultado.res.json()) as PessoaResponseVerde;
  logger.info({ ...contextoAtual(), evento: "verde_chamada", chamada: "pessoa", resultado: "sucesso", duracaoMs: Date.now() - inicio }, "[verde] pessoa: chamada concluída");
  if (!corpo.dados || corpo.dados.idPessoa === undefined) return { encontrado: false };
  return {
    encontrado: true,
    idPessoa: corpo.dados.idPessoa,
    nome: corpo.dados.nome,
    nomeSocial: corpo.dados.nomeSocial,
    genero: corpo.dados.genero,
    endereco: corpo.dados.endereco,
    enderecoDetalhado: corpo.dados.enderecoDetalhado,
  };
}

// bairro/municipio vêm ora null, ora objeto completo {id, nome} (CEP a CEP,
// não é regra geral da API) — leitura defensiva, sem assumir shape fixo.
// Issue #176 — uf.sigla/bairro.nome/municipio.nome/logradouro são TEXTO de
// verdade quando presentes (confirmado ao vivo com CEP real, issue #176) —
// antes só os ids eram lidos, o texto era descartado.
interface CepResponseVerde {
  codigo?: string;
  mensagem?: string;
  dados?: {
    uf?: { id?: number; sigla?: string; nome?: string } | null;
    bairro?: { id?: number; nome?: string } | null;
    municipio?: { id?: number; nome?: string } | null;
    logradouro?: string | null;
    numero?: string | null;
  };
}

function idDeCampoCep(campo: { id?: number } | null | undefined): number | undefined {
  return campo && typeof campo === "object" ? campo.id : undefined;
}

function nomeDeCampoCep(campo: { nome?: string } | null | undefined): string | undefined {
  return campo && typeof campo === "object" ? campo.nome : undefined;
}

// Issue #127 — GET /cep/{cep}, separado de /pessoa: devolve ids de
// uf/bairro/município (quando cadastrados) pra quem só tinha o nome em
// texto via /pessoa. idBairro/idMunicipio ficam undefined quando a Verde
// não tem esse dado pro CEP — não é erro, o CEP existe, só falta o
// detalhe (aconteceu com os 2 CEPs reais testados nesta sessão).
export async function consultarCep(cep: string): Promise<DadosCep> {
  if (!VERDE_JWT_TOKEN) {
    logger.warn(contextoAtual(), "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)");
    // CEP "00000000" simula "não encontrado" (mesmo padrão do CPF
    // "00000000000" em consultarPessoaPorCpf) — testa o caso da pessoa
    // não saber o CEP: coletarEndereco (issue #178) pergunta todos os
    // campos normalmente, já que nada veio pronto.
    if (cep.replace(/\D/g, "") === "00000000") return { encontrado: false };
    // MOCK_CEP_INCOMPLETO=true simula o caso real já visto (issue #127) de
    // CEP que só devolve uf, sem bairro/município/logradouro — testa o
    // fallback de pergunta do subgrafo coletarEndereco (issue #176). Sem a
    // flag, mock devolve endereço completo (caso mais comum na prática).
    if (process.env.MOCK_CEP_INCOMPLETO === "true") return { encontrado: true, idUf: 19, uf: "RJ" };
    return {
      encontrado: true,
      idUf: 19,
      idBairro: 9948,
      idMunicipio: 3643,
      uf: "RJ",
      bairro: "Bairro de Teste (mock)",
      municipio: "Rio de Janeiro (mock)",
      logradouro: "Rua de Teste (mock)",
    };
  }
  const inicio = Date.now();
  const resultado = await chamarVerdeComRetry("cep", () =>
    fetch(`${VERDE_API_URL}/cep/${encodeURIComponent(cep)}`, {
      method: "GET",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${VERDE_JWT_TOKEN}`,
        "x-client-id": VERDE_CLIENT_ID,
      },
      signal: AbortSignal.timeout(TIMEOUT_VERDE_MS),
    })
  );
  if (!resultado.ok) return { encontrado: false };
  const corpo = (await resultado.res.json()) as CepResponseVerde;
  logger.info({ ...contextoAtual(), evento: "verde_chamada", chamada: "cep", resultado: "sucesso", duracaoMs: Date.now() - inicio }, "[verde] cep: chamada concluída");
  if (!corpo.dados) return { encontrado: false };
  return {
    encontrado: true,
    idUf: idDeCampoCep(corpo.dados.uf),
    idBairro: idDeCampoCep(corpo.dados.bairro),
    idMunicipio: idDeCampoCep(corpo.dados.municipio),
    uf: corpo.dados.uf?.sigla,
    bairro: nomeDeCampoCep(corpo.dados.bairro),
    municipio: nomeDeCampoCep(corpo.dados.municipio),
    logradouro: corpo.dados.logradouro ?? undefined,
  };
}

interface OrgaoResponseVerde {
  codigo?: string;
  mensagem?: string;
  dados?: Array<{
    id?: number;
    nome?: string;
    enderecos?: Array<{
      logradouro?: string;
      numero?: string;
      complemento?: string;
      cep?: string;
      bairro?: string;
      municipio?: string;
      uf?: string;
      idLocalAtendimento?: number;
      horariosUrgencia?: Array<{ diaDaSemana?: string; horaInicio?: string; horaFim?: string; informacaoComplementar?: string }>;
      horariosAtendimentoFormatado?: string;
      horariosUrgenciaFormatado?: string;
    }>;
  }>;
}

// Consulta o(s) órgão(s) certo(s) pra encaminhar um caso de violência
// doméstica, dado o idPessoa — o Verde resolve TUDO internamente pelo
// endereço cadastrado da pessoa (regra de negócio deles, documentada nas
// issues #8485/#10146 do Facilitador: sem RO cai em NUDEM > núcleo de 1º
// atendimento > DP única, com RO cai no Juizado de VD ou DP única
// competente). Sem comparação de município/capital aqui — isso morava no
// nosso lado antes, mas é o Verde quem decide de verdade.
//
// Devolve em ordem de prioridade — fluxos/violenciaDomestica/graph.ts usa
// sempre o primeiro item. RO:true sem NENHUM órgão encontrado é o único
// caso "não encontrado" documentado (RO:false sempre tem fallback).
export async function consultarOrgaosViolenciaDomestica(indicacaoRO: boolean, idPessoa: number): Promise<OrgaosViolenciaDomestica> {
  if (!VERDE_JWT_TOKEN) {
    logger.warn(contextoAtual(), "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)");
    // idPessoa 0 (== "pessoa não encontrada" no mock de consultarPessoaPorCpf)
    // + RO:true simula o caso "sem órgão" — só existe nessa combinação,
    // mesmo padrão de sentinela dos outros mocks deste arquivo.
    if (indicacaoRO && idPessoa === 0) {
      return {
        encontrado: false,
        orgaos: [],
        contactarCrc: true,
        mensagemCrc: "Para dar continuidade ao seu atendimento, favor entrar em contato com a Central de Relacionamento com o Cidadão ligando 129",
      };
    }
    const orgao: OrgaoAtendimento = indicacaoRO
      ? {
          id: 274,
          nome: "DP de Defesa da Mulher junto ao Juizado de Violência Doméstica (mock)",
          enderecos: [{ municipio: "Município de Teste", idLocalAtendimento: 222 }],
        }
      : {
          id: 525,
          nome: "Coordenação de Defesa dos Direitos da Mulher (mock)",
          enderecos: [{ municipio: "Rio de Janeiro (mock)", idLocalAtendimento: 1233 }],
        };
    return { encontrado: true, orgaos: [orgao] };
  }
  const inicio = Date.now();
  const resultado = await chamarVerdeComRetry("orgao-violencia-domestica", () =>
    fetch(`${VERDE_API_URL}/orgao/violencia-domestica?indicacaoRO=${indicacaoRO}&idPessoa=${idPessoa}`, {
      method: "GET",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${VERDE_JWT_TOKEN}`,
        "x-client-id": VERDE_CLIENT_ID,
      },
      signal: AbortSignal.timeout(TIMEOUT_VERDE_MS),
    })
  );
  if (!resultado.ok) return { encontrado: false, orgaos: [] };
  const corpo = (await resultado.res.json()) as OrgaoResponseVerde;
  logger.info({ ...contextoAtual(), evento: "verde_chamada", chamada: "orgao-violencia-domestica", resultado: "sucesso", duracaoMs: Date.now() - inicio }, "[verde] orgao-violencia-domestica: chamada concluída");
  // "CONTACTAR_CRC" — código específico do Verde pra "não achei nada,
  // liga 129" (só acontece com RO:true). mensagem já vem pronta deles,
  // pt-BR, direto pro usuário.
  if (corpo.codigo === "CONTACTAR_CRC") {
    return { encontrado: false, orgaos: [], contactarCrc: true, mensagemCrc: corpo.mensagem };
  }
  const orgaos: OrgaoAtendimento[] = (corpo.dados ?? []).map((o) => ({ id: o.id ?? 0, nome: o.nome ?? "", enderecos: o.enderecos }));
  return { encontrado: orgaos.length > 0, orgaos };
}

interface PlantaoResponseVerde {
  codigo?: string;
  mensagem?: string;
  dados?: Array<{ id?: number; tipo?: string }>;
}

// GET /integra/plantao/vigente — sem parâmetros. Lista vazia = fora de
// horário de plantão (fluxo normal de órgão). Não vazia = usa
// consultarOrgaosPlantaoViolenciaDomestica em vez da consulta normal — ver
// fluxos/violenciaDomestica/graph.ts.
export async function consultarPlantaoVigente(): Promise<Plantao[]> {
  if (!VERDE_JWT_TOKEN) {
    logger.warn(contextoAtual(), "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)");
    // MOCK_PLANTAO_VIGENTE=true simula plantão ativo — sem isso o mock
    // sempre devolve vazio (não dá pra simular via parâmetro, esse endpoint
    // não recebe nenhum). Só lido em teste/dev, nunca com token real.
    if (process.env.MOCK_PLANTAO_VIGENTE === "true") return [{ id: 1, tipo: "Violência Doméstica (mock)" }];
    return [];
  }
  const inicio = Date.now();
  const resultado = await chamarVerdeComRetry("plantao-vigente", () =>
    fetch(`${VERDE_API_URL}/plantao/vigente`, {
      method: "GET",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${VERDE_JWT_TOKEN}`,
        "x-client-id": VERDE_CLIENT_ID,
      },
      signal: AbortSignal.timeout(TIMEOUT_VERDE_MS),
    })
  );
  if (!resultado.ok) return [];
  const corpo = (await resultado.res.json()) as PlantaoResponseVerde;
  logger.info({ ...contextoAtual(), evento: "verde_chamada", chamada: "plantao-vigente", resultado: "sucesso", duracaoMs: Date.now() - inicio }, "[verde] plantao-vigente: chamada concluída");
  return (corpo.dados ?? []).filter((p) => p.id !== undefined).map((p) => ({ id: p.id as number, tipo: p.tipo }));
}

// GET /integra/orgao/plantao/violencia-domestica — mesmo formato de
// resultado de consultarOrgaosViolenciaDomestica (reaproveitado pelo grafo
// sem precisar saber qual dos dois foi chamado). idPlantao é repetível na
// query string (?idPlantao=1&idPlantao=2).
export async function consultarOrgaosPlantaoViolenciaDomestica(idPlantao: number[], idAssistido: number): Promise<OrgaosViolenciaDomestica> {
  if (!VERDE_JWT_TOKEN) {
    logger.warn(contextoAtual(), "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)");
    if (idAssistido === 0) {
      return {
        encontrado: false,
        orgaos: [],
        contactarCrc: true,
        mensagemCrc: "Para dar continuidade ao seu atendimento, favor entrar em contato com a Central de Relacionamento com o Cidadão ligando 129",
      };
    }
    return {
      encontrado: true,
      orgaos: [
        {
          id: 999,
          nome: "Órgão de Plantão (mock)",
          enderecos: [{ municipio: "Rio de Janeiro (mock)", idLocalAtendimento: 333 }],
        },
      ],
    };
  }
  const inicio = Date.now();
  const query = idPlantao.map((id) => `idPlantao=${id}`).join("&");
  const resultado = await chamarVerdeComRetry("orgao-plantao-violencia-domestica", () =>
    fetch(`${VERDE_API_URL}/orgao/plantao/violencia-domestica?${query}&idAssistido=${idAssistido}`, {
      method: "GET",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${VERDE_JWT_TOKEN}`,
        "x-client-id": VERDE_CLIENT_ID,
      },
      signal: AbortSignal.timeout(TIMEOUT_VERDE_MS),
    })
  );
  if (!resultado.ok) return { encontrado: false, orgaos: [] };
  logger.info({ ...contextoAtual(), evento: "verde_chamada", chamada: "orgao-plantao-violencia-domestica", resultado: "sucesso", duracaoMs: Date.now() - inicio }, "[verde] orgao-plantao-violencia-domestica: chamada concluída");
  const corpo = (await resultado.res.json()) as {
    codigo?: string;
    mensagem?: string;
    dados?: NonNullable<OrgaoResponseVerde["dados"]>[number] | NonNullable<OrgaoResponseVerde["dados"]>;
  };
  if (corpo.codigo) {
    // qualquer resposta com `codigo` aqui é erro/"não encontrado" (ex:
    // REQUISICAO_INVALIDA visto ao vivo pra assistido sem endereço) — trata
    // igual ao CONTACTAR_CRC do endpoint normal, mesma UX (handoff humano).
    return { encontrado: false, orgaos: [], contactarCrc: true, mensagemCrc: corpo.mensagem };
  }
  // Doc do Swagger mostra `dados` como objeto único aqui (diferente do
  // endpoint normal, que é array) — normaliza os dois formatos, não
  // confiei 100% na doc depois do que já vimos divergir da realidade.
  const bruto = (corpo as { dados?: unknown }).dados;
  const lista = Array.isArray(bruto) ? bruto : bruto ? [bruto] : [];
  const orgaos: OrgaoAtendimento[] = (lista as Array<{ id?: number; nome?: string; enderecos?: OrgaoAtendimento["enderecos"] }>).map((o) => ({
    id: o.id ?? 0,
    nome: o.nome ?? "",
    enderecos: o.enderecos,
  }));
  return { encontrado: orgaos.length > 0, orgaos };
}

interface EncaminhamentoResponseVerde {
  codigo?: string;
  mensagem?: string;
  // id vem aninhado em `dados` (confirmado ao vivo 2026-09-18) — igual ao
  // padrão de pessoa/orgao, diferente do que este endpoint tinha antes
  // (corpo.id na raiz, que nunca existiu de verdade e fazia todo
  // encaminhamento cair em falha_encaminhamento mesmo com HTTP 201 OK).
  dados?: { id?: number; urgente?: boolean };
}

export interface DadosEncaminhamento {
  idPessoa: number;
  idOrgao: number;
  idLocalAtendimento?: number;
  urgente: boolean;
}

// POST /integra/encaminhamento/encaminhar — executa o encaminhamento de
// verdade (cria registro real no Verde). idAssunto NÃO é enviado — confirmado
// com o time do Verde que não é necessário pro fluxo de violência doméstica
// (2026-09-04). preferenciaAtendimento sempre "Remoto" (é chatbot).
export async function criarEncaminhamentoViolenciaDomestica(dados: DadosEncaminhamento): Promise<ResultadoEncaminhamento> {
  if (!VERDE_JWT_TOKEN) {
    logger.warn(contextoAtual(), "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)");
    // MOCK_ENCAMINHAMENTO_FALHA=true simula falha — só lido em teste/dev.
    if (process.env.MOCK_ENCAMINHAMENTO_FALHA === "true") return { sucesso: false, erro: "falha simulada (mock)" };
    return { sucesso: true, id: 999999 };
  }
  const inicio = Date.now();
  const body = {
    idPessoa: dados.idPessoa,
    idOrgao: dados.idOrgao,
    ...(dados.idLocalAtendimento !== undefined ? { idLocalAtendimento: dados.idLocalAtendimento } : {}),
    urgencia: dados.urgente,
    preferenciaAtendimento: "Remoto",
    fluxoEncaminhamento: "VIOLENCIA_DOMESTICA",
    ...(dados.urgente ? { motivoUrgencia: "Violência doméstica com Boletim de Ocorrência registrado" } : {}),
  };
  const resultado = await chamarVerdeComRetry("encaminhamento", () =>
    fetch(`${VERDE_API_URL}/encaminhamento/encaminhar`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        authorization: `Bearer ${VERDE_JWT_TOKEN}`,
        "x-client-id": VERDE_CLIENT_ID,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_VERDE_MS),
    })
  );
  if (!resultado.ok) {
    const corpoErro = (await resultado.res?.json().catch(() => ({}))) as EncaminhamentoResponseVerde | undefined;
    // Achado em code review: chamarVerdeComRetry só loga via logHttpNaoOk
    // ANTES do parse do body (não tem acesso ao JSON) — sem isso aqui, o
    // corpo de erro da Verde (campo mensagem/codigo) sumia do log
    // estruturado em caso de falha, só sobrevivia dentro do campo `erro` do
    // retorno (que `falhaEncaminhamento()` em violenciaDomestica/graph.ts
    // nem sequer lê — vira mensagem genérica pro usuário).
    logger.error(
      { ...contextoAtual(), corpo: corpoErro, status: resultado.res?.status, evento: "verde_chamada", chamada: "encaminhamento", resultado: "nao_ok", duracaoMs: Date.now() - inicio },
      "[verde] encaminhamento: falhou, corpo de erro da Verde"
    );
    return { sucesso: false, erro: corpoErro?.mensagem ?? (resultado.falhaInfra ? "falha na chamada ao Verde (infra esgotada)" : `HTTP ${resultado.res?.status}`) };
  }
  const corpo = (await resultado.res.json().catch(() => ({}))) as EncaminhamentoResponseVerde;
  logger.info({ ...contextoAtual(), corpo, evento: "verde_chamada", chamada: "encaminhamento", resultado: "sucesso", duracaoMs: Date.now() - inicio }, "[verde] encaminhamento: chamada concluída");
  return { sucesso: true, id: corpo.dados?.id };
}

export interface EnderecoCadastroPessoa {
  logradouro?: string;
  numero?: string;
  complemento?: string;
  cep?: string;
  bairro?: string;
  municipio?: string;
  uf?: string;
}

export interface DadosCadastroPessoa {
  nome: string;
  cpf: string;
  dataNascimento: string;
  // Issue #176 — opcional; sem ele, POST /integra/pessoa cadastra sem
  // endereço (comportamento de antes da issue #176, ainda suportado).
  endereco?: EnderecoCadastroPessoa;
}

interface CadastroPessoaResponseVerde {
  codigo?: string;
  mensagem?: string;
  dados?: { idPessoa?: number };
}

// Issue #171 — POST /integra/pessoa, cria cadastro novo no Verde (CPF válido
// e ainda não cadastrado). Escopo restrito de propósito (decisão registrada
// na issue): só os 3 campos obrigatórios do CadastrarPessoaDTO (nome, cpf,
// dtNascimento) — endereço/telefone/email/gênero/representante ficam pra
// melhoria futura, chatbot não pede ainda.
export async function cadastrarPessoa(dados: DadosCadastroPessoa): Promise<ResultadoCadastroPessoa> {
  if (!VERDE_JWT_TOKEN) {
    logger.warn(contextoAtual(), "[verde] VERDE_JWT_TOKEN ausente — modo mock (dev local)");
    // MOCK_CADASTRO_FALHA=true simula falha — só lido em teste/dev, mesmo
    // padrão de MOCK_ENCAMINHAMENTO_FALHA.
    if (process.env.MOCK_CADASTRO_FALHA === "true") return { sucesso: false, erro: "falha simulada (mock)" };
    return { sucesso: true, idPessoa: 888888 };
  }
  const inicio = Date.now();
  const body = {
    nome: dados.nome,
    cpf: dados.cpf,
    dtNascimento: dados.dataNascimento,
    ...(dados.endereco ? { endereco: dados.endereco } : {}),
  };
  const resultado = await chamarVerdeComRetry("cadastroPessoa", () =>
    fetch(`${VERDE_API_URL}/pessoa`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        authorization: `Bearer ${VERDE_JWT_TOKEN}`,
        "x-client-id": VERDE_CLIENT_ID,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_VERDE_MS),
    })
  );
  if (!resultado.ok) {
    const corpoErro = (await resultado.res?.json().catch(() => ({}))) as CadastroPessoaResponseVerde | undefined;
    // Mesmo achado de code review do encaminhamento acima — sem isso, o
    // corpo de erro da Verde sumia do log estruturado em caso de falha.
    logger.error(
      { ...contextoAtual(), corpo: corpoErro, status: resultado.res?.status, evento: "verde_chamada", chamada: "cadastroPessoa", resultado: "nao_ok", duracaoMs: Date.now() - inicio },
      "[verde] cadastroPessoa: falhou, corpo de erro da Verde"
    );
    return { sucesso: false, erro: corpoErro?.mensagem ?? (resultado.falhaInfra ? "falha na chamada ao Verde (infra esgotada)" : `HTTP ${resultado.res?.status}`) };
  }
  const corpo = (await resultado.res.json().catch(() => ({}))) as CadastroPessoaResponseVerde;
  logger.info(
    { ...contextoAtual(), corpo, evento: "verde_chamada", chamada: "cadastroPessoa", resultado: "sucesso", duracaoMs: Date.now() - inicio },
    "[verde] cadastroPessoa: chamada concluída"
  );
  if (corpo.dados?.idPessoa === undefined) return { sucesso: false, erro: "Verde não devolveu idPessoa" };
  return { sucesso: true, idPessoa: corpo.dados.idPessoa };
}
