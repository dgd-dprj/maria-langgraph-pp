"""Dados da outra pessoa quando o CPF dela não tem cadastro no Verde (#446, parte da fase 2 da #347).

Cada campo é uma pergunta, na ordem de `ETAPAS`; a validação é só por regra (sem IA) e devolve o valor já normalizado,
ou `None` quando a resposta não serve. Dado de terceiro: nunca vai para log nem para `metadados`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime

from maria.fluxos.pessoa_presa.graph import PARENTESCOS_PERMITIDOS

MAXIMO_TENTATIVAS_DADOS_OUTRA = 3

ESTADOS_CIVIS = ["Solteiro(a)", "Casado(a)", "União estável", "Divorciado(a)", "Viúvo(a)", "Separado(a)"]
ETAPA_ENDERECO = "endereco"
_NAO_TEM = {"nao", "n", "nao tenho", "nao sei", "sem", "nenhum", "nenhuma", "pular", "nao possui", "nao tem", "-"}
_MESMO = {"mesmo", "o mesmo", "mesmo numero", "o mesmo numero", "igual", "sim", "s"}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower().strip()


def _limpo(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _quer_pular(resposta: str) -> bool:
    return _sem_acento(resposta).rstrip(".!") in _NAO_TEM


def interpretar_nome(resposta: str, _: Mapping[str, str]) -> str | None:
    nome = _limpo(resposta)
    palavras = nome.split(" ")
    if len(palavras) < 2 or len(nome) > 120 or not re.fullmatch(r"[^\W\d_]+(?:[ '.\-][^\W\d_]+)*\.?", nome):
        return None
    return nome


def interpretar_data_nascimento(resposta: str, _: Mapping[str, str]) -> str | None:
    texto = resposta.strip()
    achado = re.fullmatch(r"(\d{1,2})[/.\- ](\d{1,2})[/.\- ](\d{4})", texto) or re.fullmatch(r"(\d{2})(\d{2})(\d{4})", texto)
    if achado is None:
        return None
    dia, mes, ano = (int(g) for g in achado.groups())
    try:
        nascimento = date(ano, mes, dia)
    except ValueError:
        return None
    if ano < 1900 or nascimento > datetime.now().date():
        return None
    return f"{dia:02d}/{mes:02d}/{ano}"


def _variantes(opcao: str) -> set[str]:
    """Como a pessoa pode escrever a opção: sem acento, com o "(a)" aberto em masculino e feminino, e cada lado de "Avô/Avó"."""
    saida: set[str] = set()
    for parte in _sem_acento(opcao).split("/"):
        base = parte.replace("(a)", "").strip()
        saida.add(base)
        if "(a)" in parte and base.endswith("o"):
            saida.add(base[:-1] + "a")
    return saida


def _opcao(resposta: str, opcoes: list[str]) -> str | None:
    """A opção que a pessoa escolheu: igual a uma das formas dela (sem acento nem caixa) ou, sem ambiguidade, o começo dela."""
    texto = _sem_acento(resposta).replace("(a)", "").rstrip(".! ")
    if not texto:
        return None
    for opcao in opcoes:
        if texto in _variantes(opcao):
            return opcao
    achadas = [opcao for opcao in opcoes if len(texto) >= 3 and any(v.startswith(texto) for v in _variantes(opcao))]
    return achadas[0] if len(achadas) == 1 else None


def interpretar_estado_civil(resposta: str, _: Mapping[str, str]) -> str | None:
    return _opcao(resposta, ESTADOS_CIVIS)


def interpretar_parentesco(resposta: str, _: Mapping[str, str]) -> str | None:
    return _opcao(resposta, PARENTESCOS_PERMITIDOS)


def interpretar_profissao(resposta: str, _: Mapping[str, str]) -> str | None:
    profissao = _limpo(resposta)
    return profissao if 2 <= len(profissao) <= 80 and re.search(r"[^\W\d_]", profissao) else None


def interpretar_rg(resposta: str, _: Mapping[str, str]) -> str | None:
    if _quer_pular(resposta):
        return ""
    rg = resposta.strip()
    essencial = re.sub(r"[.\-\s/]", "", rg)
    return rg if re.fullmatch(r"[0-9A-Za-z.\-\s/]{5,20}", rg) and re.fullmatch(r"[0-9A-Za-z]{5,16}", essencial) else None


def _telefone(resposta: str) -> str | None:
    digitos = re.sub(r"[^0-9]", "", resposta)
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11) or not 11 <= int(digitos[:2]) <= 99:
        return None
    return digitos if len(digitos) == 10 or digitos[2] == "9" else None


def interpretar_telefone(resposta: str, _: Mapping[str, str]) -> str | None:
    return _telefone(resposta)


def interpretar_whatsapp(resposta: str, dados: Mapping[str, str]) -> str | None:
    texto = _sem_acento(resposta).rstrip(".!")
    if texto in _MESMO:
        return dados.get("telefone") or ""
    if _quer_pular(resposta):
        return ""
    return _telefone(resposta)


def interpretar_email(resposta: str, _: Mapping[str, str]) -> str | None:
    if _quer_pular(resposta):
        return ""
    email = resposta.strip().lower()
    return email if len(email) <= 120 and re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9\-]+(?:\.[a-z0-9\-]+)+", email) else None


@dataclass(frozen=True)
class Campo:
    chave: str
    pergunta: str
    novamente: str
    interpretar: Callable[[str, Mapping[str, str]], str | None]
    opcoes: list[str] | None = None  # `tipoResposta: opcoes` quando preenchido; senão, `texto`


CAMPOS: dict[str, Campo] = {
    campo.chave: campo
    for campo in (
        Campo(
            "nome",
            "Não encontrei esse CPF no cadastro. Vou pedir os dados da pessoa que será atendida. Qual o nome completo dela?",
            "Não entendi o nome. Informe o nome completo da pessoa que será atendida (nome e sobrenome).",
            interpretar_nome,
        ),
        Campo(
            "dataNascimento",
            "Qual a data de nascimento dela? (dd/mm/aaaa)",
            "Não entendi a data. Informe a data de nascimento no formato dd/mm/aaaa.",
            interpretar_data_nascimento,
        ),
        Campo(
            "estadoCivil",
            "Qual o estado civil dela?",
            "Não entendi. Escolha o estado civil dela.",
            interpretar_estado_civil,
            ESTADOS_CIVIS,
        ),
        Campo(
            "profissao",
            "Qual a profissão dela?",
            "Não entendi. Informe a profissão dela, em poucas palavras.",
            interpretar_profissao,
        ),
        Campo(
            "rg",
            'Qual o RG dela? Se não souber, responda "não tenho".',
            'Não entendi o RG. Envie só o número do RG, ou responda "não tenho".',
            interpretar_rg,
        ),
        Campo(
            "telefone",
            "Qual o telefone dela, com DDD?",
            "Não entendi o telefone. Informe com DDD, por exemplo 21 98888-0000.",
            interpretar_telefone,
        ),
        Campo(
            "whatsapp",
            'Qual o WhatsApp dela, com DDD? Se for o mesmo número do telefone, responda "mesmo". Se não tiver, responda "não tenho".',
            'Não entendi o WhatsApp. Informe com DDD, ou responda "mesmo" ou "não tenho".',
            interpretar_whatsapp,
        ),
        Campo(
            "email",
            'Qual o e-mail dela? Se não tiver, responda "não tenho".',
            'Não entendi o e-mail. Envie um e-mail válido, ou responda "não tenho".',
            interpretar_email,
        ),
        Campo(
            "parentesco",
            "Qual o seu parentesco com a pessoa que será atendida?",
            "Não entendi. Escolha o seu parentesco com a pessoa que será atendida.",
            interpretar_parentesco,
            PARENTESCOS_PERMITIDOS,
        ),
    )
}

# A ordem da conversa; o endereço entra pelo subgrafo `coletar_endereco`, sem verificar o município.
ETAPAS: tuple[str, ...] = (
    "nome",
    "dataNascimento",
    "estadoCivil",
    "profissao",
    "rg",
    ETAPA_ENDERECO,
    "telefone",
    "whatsapp",
    "email",
    "parentesco",
)


def etapa_depois_de(etapa: str) -> str | None:
    posicao = ETAPAS.index(etapa) + 1
    return ETAPAS[posicao] if posicao < len(ETAPAS) else None
