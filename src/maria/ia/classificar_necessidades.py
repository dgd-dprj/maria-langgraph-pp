"""Classificação por necessidades do multi-fluxo (#435, fase 1a da #279).

Lê o relato e devolve cada necessidade de atendimento separada: o id do catálogo, o trecho do
relato que a justifica, se a evidência é clara e se há urgência. A dúvida entre opções para um
MESMO assunto vem à parte (`idsEmAmbiguidade`), e o orquestrador continua tratando como hoje
(desambiguação, escolha direta da #419).

O prompt é o da fase 0 da #279, medido fora do ar com 343 relatos inventados (27 e 28/10), com as
decisões da Nicole: a prisão citada só como contexto não é pedido sobre pessoa presa; urgência só
com os 4 sinais combinados em 28/10; erro de digitação e jeito de falar são entendidos pelo sentido.

Só roda no release (`fluxo_em_teste_liga`); a produção segue com `classificar_fluxos_plausiveis`.
Diferente dela, aqui a saída É validada: id fora da lista sai, e item malformado é ignorado.
É código novo, sem develop para reproduzir (#212 vale para o caminho de hoje).
"""

from __future__ import annotations

import json
import os
from typing import Any, NotRequired, TypedDict

from maria.ia._estruturado import criar_modelo, definir_tokens, erro_para_log, esquema_objeto, invocar_estruturado
from maria.shared.contexto import contexto_atual
from maria.shared.logger import logger

modelo = criar_modelo()

# Assunto do relato que não cabe em nenhuma opção. O orquestrador manda para "outros" da Tykhe.
FORA_DA_LISTA = "fora_da_lista"


class OpcaoParaNecessidades(TypedDict):
    id: str
    nome: str
    descricao: str


class Necessidade(TypedDict):
    id: str
    evidencia: str
    evidenciaClara: bool
    urgente: bool


class ResultadoNecessidades(TypedDict):
    necessidades: list[Necessidade]
    idsEmAmbiguidade: list[str]
    viaIA: bool
    tokensEntrada: NotRequired[int]
    tokensSaida: NotRequired[int]
    tokensTotal: NotRequired[int]


SISTEMA = """Você é a IA de triagem da Maria, assistente da Defensoria Pública do RJ. Você lê o relato da pessoa e identifica as necessidades de atendimento, escolhendo o id correto para cada uma a partir de uma lista fechada de opções. Você não conversa com a pessoa, não escreve mensagens e não decide destino nem ordem de atendimento.

Opções do catálogo (use somente estes ids):
{descricoes}

Quando o texto trouxer, depois do relato, uma pergunta de esclarecimento e a resposta da pessoa, classifique o relato junto com a resposta.

Regras:
- Use somente ids da lista. Se nenhum servir, devolva quantidade "sem_id_compativel" e nenhuma necessidade. Não invente id.
- Se um dos assuntos do relato não cabe em nenhuma opção, registre-o como necessidade com o id "fora_da_lista". Não force esse assunto numa opção parecida e não o descarte.
- Com mais de um assunto, cada assunto que não cabe vira uma necessidade "fora_da_lista" própria, mesmo que nenhum caiba. Use "sem_id_compativel" sem necessidades só quando o relato tem um assunto só e ele não cabe em nenhuma opção.
- Só crie mais de uma necessidade quando houver evidências distintas no relato para ids diferentes.
- Se o relato tiver um assunto só, devolva uma única necessidade, mesmo que a pessoa dê vários detalhes.
- Se for a mesma necessidade com dúvida entre ids, marque ambiguidade e liste os ids em dúvida. Não crie duas necessidades.
- Se a pessoa disser "os dois", "as duas coisas", "quero os dois" ou equivalente em resposta à pergunta de esclarecimento, trate como duas necessidades. Não marque ambiguidade.
- Nunca descarte uma necessidade porque a pessoa falou mais de outra.
- Na dúvida entre dividir ou não, não divida: falso desdobramento é o erro mais caro.
- O motivo, a causa, a consequência ou o contexto de um pedido não é outro assunto. Exemplos de um assunto só: "meu cartão de gratuidade foi bloqueado e eu faço tratamento três vezes por semana" (o tratamento é o motivo); "o hospital não me dá o prontuário do meu pai, que faleceu lá" (o falecimento é o contexto). Só é outro assunto quando a pessoa pede outra coisa.
- Jeitos populares de dizer que alguém foi preso: "rodou", "a polícia levou", "tá na cana", "foi pra Bangu", "tá puxando cadeia", "tá no sistema", "pegaram ele".
- Citar que alguém está preso não é, sozinho, pedido sobre pessoa presa. Quando a prisão aparece só como contexto de outro pedido ("meu marido está preso e eu quero me divorciar dele"; "meu marido foi preso, tenho direito a algum benefício?"), conte só o outro pedido. Conte pessoa presa quando a pessoa pede algo sobre o preso ou sobre a prisão: onde está, situação, processo, quando sai.
- Cirurgia ou operação sem dizer se é pelo plano de saúde (convênio) ou pela rede pública (SUS, posto, hospital público) é dúvida entre as duas opções de saúde: marque ambiguidade entre elas.
- Relato vago, que pode caber em mais de uma opção sem dizer qual, é ambiguidade: marque as opções possíveis em vez de devolver "sem_id_compativel". Use "sem_id_compativel" só quando o relato claramente não cabe em nenhuma opção.
- Não invente informação. A evidência é um trecho curto copiado do relato. Se faltar dado, marque a evidência como não clara.
- Urgência ("urgente": true) só quando o relato mostra um destes sinais:
  1. violência ou ameaça recente contra a pessoa ou alguém da casa, medo de voltar para casa, ou o agressor por perto;
  2. prisão que acabou de acontecer (flagrante, "ontem", "agora"), ainda sem audiência de custódia;
  3. risco à saúde ou à vida que não pode esperar: internação, cirurgia ou tratamento negado com urgência médica, pessoa internada ou com dor forte;
  4. criança ou adolescente em risco, desacompanhado ou apreendido agora.
  Sem um desses sinais, não marque urgência, mesmo que o assunto seja grave.
- O relato pode ter erros de digitação, falta de acento, letras trocadas, abreviações ("vc", "q", "pq", "tbm", "hj", "n"), palavras juntas ou separadas e jeito de falar ("presu", "divorsio", "sirurgia", "fio" no lugar de "filho"). Entenda pelo sentido. A evidência continua sendo copiada do relato como está escrito, com os erros, sem corrigir."""  # noqa: E501


def esquema(ids: list[str]) -> dict[str, Any]:
    return esquema_objeto(
        {
            "quantidade": {"type": "string", "enum": ["uma", "mais_de_uma", "sem_id_compativel"]},
            "haAmbiguidade": {"type": "boolean"},
            "idsEmAmbiguidade": {"type": "array", "items": {"type": "string", "enum": ids}},
            "necessidades": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": [*ids, FORA_DA_LISTA]},
                        "evidencia": {"type": "string", "description": "trecho curto copiado do relato"},
                        "evidenciaClara": {"type": "boolean"},
                        "urgente": {"type": "boolean"},
                    },
                    "required": ["id", "evidencia", "evidenciaClara", "urgente"],
                },
            },
            "observacao": {"type": "string"},
        },
        ["quantidade", "haAmbiguidade", "necessidades"],
    )


def _validar(parsed: Any, ids: list[str]) -> tuple[list[Necessidade], list[str]]:
    """Só o que tem forma certa e id conhecido. O resto é descartado, sem lançar."""
    validos = set(ids) | {FORA_DA_LISTA}
    necessidades: list[Necessidade] = []
    itens = parsed.get("necessidades") if isinstance(parsed, dict) else None
    for item in itens if isinstance(itens, list) else []:
        if not isinstance(item, dict) or item.get("id") not in validos:
            continue
        evidencia = item.get("evidencia")
        necessidades.append(
            {
                "id": item["id"],
                "evidencia": evidencia if isinstance(evidencia, str) else "",
                "evidenciaClara": item.get("evidenciaClara") is True,
                "urgente": item.get("urgente") is True,
            }
        )
    ambiguos = parsed.get("idsEmAmbiguidade") if isinstance(parsed, dict) and parsed.get("haAmbiguidade") is True else None
    em_duvida = list(dict.fromkeys(i for i in (ambiguos if isinstance(ambiguos, list) else []) if isinstance(i, str) and i in ids))
    return necessidades, em_duvida


def _mock() -> ResultadoNecessidades:
    """APP_ENV=test nunca chama o Bedrock.

    MOCK_NECESSIDADES (JSON: lista de ids ou de necessidades) simula o multi-fluxo. Sem ela, vale o
    mock de hoje (MOCK_CLASSIFICACAO_FLOWIDS / MOCK_CLASSIFICACAO_FLOWID): 1 id é uma necessidade, e
    mais de 1 é dúvida entre opções. Assim os testes de antes da #435 seguem com o mesmo sentido."""
    bruto = os.environ.get("MOCK_NECESSIDADES")
    if bruto is not None:
        itens = json.loads(bruto)
        necessidades: list[Necessidade] = [
            {"id": i, "evidencia": "", "evidenciaClara": True, "urgente": False}
            if isinstance(i, str)
            else {
                "id": i["id"],
                "evidencia": i.get("evidencia", ""),
                "evidenciaClara": i.get("evidenciaClara", True),
                "urgente": i.get("urgente", False),
            }
            for i in itens
        ]
        return {"necessidades": necessidades, "idsEmAmbiguidade": [], "viaIA": False}
    mock_ids = os.environ.get("MOCK_CLASSIFICACAO_FLOWIDS")
    if mock_ids is not None:
        ids = [s.strip() for s in mock_ids.split(",") if s.strip()]
    else:
        mock_id = os.environ.get("MOCK_CLASSIFICACAO_FLOWID")
        ids = [mock_id] if mock_id else []
    if len(ids) == 1:
        return {
            "necessidades": [{"id": ids[0], "evidencia": "", "evidenciaClara": True, "urgente": False}],
            "idsEmAmbiguidade": [],
            "viaIA": False,
        }
    return {"necessidades": [], "idsEmAmbiguidade": ids, "viaIA": False}


async def classificar_necessidades(mensagem: str, opcoes: list[OpcaoParaNecessidades]) -> ResultadoNecessidades:
    if os.environ.get("APP_ENV") == "test":
        return _mock()
    ids = list(dict.fromkeys(o["id"] for o in opcoes))
    if not ids:
        return {"necessidades": [], "idsEmAmbiguidade": [], "viaIA": False}
    descricoes = "\n".join(f'- id "{o["id"]}" ({o["nome"]}): {o["descricao"]}' for o in opcoes)
    try:
        resultado = await invocar_estruturado(modelo, esquema(ids), SISTEMA.format(descricoes=descricoes), mensagem)
        necessidades, em_duvida = _validar(resultado["parsed"], ids)
        saida: dict[str, Any] = {"necessidades": necessidades, "idsEmAmbiguidade": em_duvida, "viaIA": True}
        definir_tokens(saida, resultado["raw"])
        return saida  # type: ignore[return-value]
    except Exception as erro:
        # Na falha, segue como hoje numa falha da classificação: nada identificado.
        logger.error(
            "[classificar] falha ao classificar necessidades, tratando como não identificado", **contexto_atual(), err=erro_para_log(erro)
        )
        return {"necessidades": [], "idsEmAmbiguidade": [], "viaIA": False}
