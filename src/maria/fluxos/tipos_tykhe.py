"""Tipos de caso que a Tykhe já atende com fluxo próprio (issue #225), traduzido de
`src/fluxos/tiposTykhe.ts`.

O orquestrador classifica o relato entre eles (e os fluxos implementados, pessoa
presa e violência doméstica), mas NÃO conduz: devolve `status: "redirecionado"`
mais `tipoCaso`, e a Tykhe continua o atendimento. Enquanto um tipo não migra
para a Maria, ele mora aqui; migrar = virar um fluxo em `fluxos_por_id`
(`fluxos/__init__.py`) e sair desta lista.

`tipoCaso` é o valor do contrato com a Tykhe (`docs/contrato-tykhe.md`): trocar
ou acrescentar um valor é mudança de contrato, combinada antes. `id` é o
identificador no catálogo de classificação (embeddings e enum da IA), com
prefixo para nunca colidir com o uuid de um fluxo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TipoCasoTykhe = Literal["saude", "novo-processo", "andamento-processo", "agendamentos", "ajuda-app", "outros", "sair"]


@dataclass(frozen=True)
class TipoTykhe:
    id: str
    tipo_caso: TipoCasoTykhe
    nome: str
    # Lida pela IA e pelo embedding para classificar: mesmo papel de
    # FluxoConfig.descricao. Inclui as formas como a pessoa costuma escrever.
    descricao: str
    # Frase de transição devolvida em `resposta`; a Tykhe decide se exibe.
    mensagem: str


TIPOS_TYKHE: tuple[TipoTykhe, ...] = (
    TipoTykhe(
        id="tykhe:saude",
        tipo_caso="saude",
        nome="questoes-de-saude",
        descricao=(
            "Questões de saúde: pedido de remédio, medicamento, exame, cirurgia, internação, vaga em UTI ou CTI, "
            "tratamento, fralda, leite especial, prótese, cadeira de rodas, transferência de hospital, plano de saúde "
            "que negou cobertura, erro médico, prontuário médico."
        ),
        mensagem="Entendi. Vou te encaminhar para o atendimento de questões de saúde.",
    ),
    TipoTykhe(
        id="tykhe:novo-processo",
        tipo_caso="novo-processo",
        nome="iniciar-novo-processo",
        descricao=(
            "Quer iniciar um novo processo ou abrir um caso novo na Defensoria sobre um problema que ainda não tem "
            "processo: pensão alimentícia, divórcio, guarda, visita, inventário, imóvel, aluguel, dívida, consumidor, "
            "banco, indenização, documentos, entre outros assuntos cíveis e de família."
        ),
        mensagem="Entendi. Vou te encaminhar para o atendimento de abertura de um novo caso.",
    ),
    TipoTykhe(
        id="tykhe:andamento-processo",
        tipo_caso="andamento-processo",
        nome="ver-andamento-do-processo",
        descricao=(
            "Quer saber o andamento, a situação ou novidades de um processo que já existe: número do processo, "
            "audiência marcada, sentença, decisão do juiz, prazo, intimação ou citação recebida sobre um processo em "
            "curso."
        ),
        mensagem="Entendi. Vou te encaminhar para a consulta do andamento do seu processo.",
    ),
    TipoTykhe(
        id="tykhe:agendamentos",
        tipo_caso="agendamentos",
        nome="ver-meus-agendamentos",
        descricao=(
            "Quer consultar, confirmar, remarcar ou cancelar um agendamento ou atendimento marcado na Defensoria: "
            "data, horário, endereço do núcleo, comparecimento."
        ),
        mensagem="Entendi. Vou te encaminhar para os seus agendamentos.",
    ),
    TipoTykhe(
        id="tykhe:ajuda-app",
        tipo_caso="ajuda-app",
        nome="ajuda-app-defensoria-rj",
        descricao=(
            "Dúvida ou dificuldade com o aplicativo Defensoria RJ ou com o canal digital: não consegue acessar, "
            "cadastro, senha, erro no app, como usar, onde encontrar uma função. Também perguntas gerais sobre como "
            "funciona a Defensoria."
        ),
        mensagem="Entendi. Vou te encaminhar para a ajuda com o aplicativo Defensoria RJ.",
    ),
    TipoTykhe(
        id="tykhe:outros",
        tipo_caso="outros",
        nome="outros-assuntos",
        descricao="Outros assuntos que não se encaixam nas demais opções.",
        mensagem="Entendi. Vou te encaminhar para o atendimento de outros assuntos.",
    ),
    TipoTykhe(
        id="tykhe:sair",
        tipo_caso="sair",
        nome="sair",
        descricao="A pessoa quer encerrar ou sair da conversa: tchau, encerrar, sair, não quero mais, obrigado era só isso.",
        mensagem="Tudo bem. Quando precisar, é só chamar.",
    ),
)

_por_id = {t.id: t for t in TIPOS_TYKHE}


def tipo_tykhe_por_id(id_: str) -> TipoTykhe | None:
    return _por_id.get(id_)


def tipo_tykhe_por_caso(tipo_caso: TipoCasoTykhe) -> TipoTykhe:
    # Em develop, `find(...) as TipoTykhe`: o tipo garante que existe.
    return next(t for t in TIPOS_TYKHE if t.tipo_caso == tipo_caso)
