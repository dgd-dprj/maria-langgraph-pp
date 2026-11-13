"""Metadados e mensagens do fluxo Problemas com plano de saúde (NUDECON, issue #329).

Os textos marcados "provisório" valem até o NUDECON validar (#335) e a Tykhe
confirmar os destinos (#336).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

# Imagens que a Maria pede à Tykhe, na ordem (#398): (chave do estado, `tipoImagem` do contrato).
# Lista provisória até a #335 definir os documentos.
TIPOS_IMAGEM: tuple[tuple[str, str], ...] = (("carteirinhaFrente", "carteirinha_frente"), ("carteirinhaVerso", "carteirinha_verso"))
# Único domínio dos links de baixar a imagem (modelo informado pela Tykhe em 2026-11-04, #345).
HOSTS_IMAGEM_PERMITIDOS = frozenset({"downloads.tykhe.dev"})
TAMANHO_MAXIMO_URL_IMAGEM = 2048


def url_imagem_valida(texto: str) -> str | None:
    """A URL que a Tykhe devolveu, se for https de um host permitido, em /arquivos/<id>, sem usuário, senha nem porta; senão `None`."""
    url = texto.strip()
    if not url or len(url) > TAMANHO_MAXIMO_URL_IMAGEM or any(c.isspace() for c in url):
        return None
    try:
        partes = urlsplit(url)
        host = (partes.hostname or "").lower()
        porta = partes.port
    except ValueError:
        return None
    if partes.scheme != "https" or host not in HOSTS_IMAGEM_PERMITIDOS or partes.username or partes.password or porta is not None:
        return None
    # Modelo da Tykhe: /arquivos/<idDoArquivo>.
    id_do_arquivo = partes.path.removeprefix("/arquivos/")
    return url if partes.path.startswith("/arquivos/") and id_do_arquivo.strip("/") else None


def extrair_metadados_plano_saude(values: Mapping[str, Any]) -> dict[str, Any]:
    metadados: dict[str, Any] = {}
    for chave in ("paraSi", "relato", "renda", "motivoHandoff"):
        valor = values.get(chave)
        if valor is not None:
            metadados[chave] = valor
    return metadados


_CAMPOS_OUTRA_PESSOA = (
    "nome",
    "dataNascimento",
    "endereco",
    "telefone",
    "whatsapp",
    "email",
    "estadoCivil",
    "profissao",
    "rg",
    "parentesco",
)


def extrair_dados_coletados_plano_saude(values: Mapping[str, Any]) -> dict[str, Any]:
    """#448: quando o atendimento é para outra pessoa, o solicitante e a pessoa atendida voltam em `dadosColetados`, cada um
    no seu bloco, para a Tykhe não misturar os CPFs. Dado pessoal: só na resposta, nunca em log nem em `metadados`."""
    outra = values.get("dadosOutraPessoa")
    if not isinstance(outra, Mapping) or not outra:
        return {}

    def texto(valor: Any) -> str:
        return valor.strip() if isinstance(valor, str) else ""

    solicitante = {chave: texto(values.get(origem)) for chave, origem in (("nome", "nome"), ("cpf", "cpf"))}
    pessoa = {"cpf": texto(values.get("cpfOutraPessoa")), **{chave: texto(outra.get(chave)) for chave in _CAMPOS_OUTRA_PESSOA}}
    pessoa["origem"] = "informado" if outra.get("origem") == "informado" else "verde"
    return {
        "solicitante": {k: v for k, v in solicitante.items() if v},
        "outraPessoa": {k: v for k, v in pessoa.items() if v},
    }


# Provisório: o texto final, com documentos e prazo, é da #335; o envio ao NUDECON, da #345.
MENSAGEM_CONCLUIDO = "Recebi suas informações e vou encaminhar seu atendimento ao NUDECON, que entra em contato com você."
MENSAGEM_IMAGENS_PENDENTES = "Não recebi as imagens dos documentos. Vou encaminhar seu atendimento para a equipe dar continuidade."
MENSAGEM_SITUACAO_NAO_INFORMADA = "Não consegui entender a sua situação. Vou encaminhar seu atendimento para a equipe dar continuidade."
MENSAGEM_RENDA_NAO_ENTENDIDA = "Não consegui entender a sua renda. Vou encaminhar seu atendimento para a equipe dar continuidade."
MENSAGEM_DADOS_NAO_CONFIRMADOS = "Não consegui confirmar seus dados. Vou encaminhar seu atendimento para a equipe dar continuidade."
# Outra pessoa (#433): CPF dela inválido, três vezes.
MENSAGEM_CPF_OUTRA_INVALIDO = (
    "Não consegui entender o CPF da pessoa que será atendida. Vou encaminhar seu atendimento para a equipe dar continuidade."
)
# Sem cadastro no Verde, a Maria pede os dados dela (#446); três respostas inválidas no mesmo campo encerram.
MENSAGEM_DADOS_OUTRA_INVALIDOS = (
    "Não consegui entender os dados da pessoa que será atendida. Vou encaminhar seu atendimento para a equipe dar continuidade."
)
# O e-mail saiu com os dados, mas a função não conseguiu anexar as imagens da carteirinha (#423).
MENSAGEM_IMAGENS_NAO_ANEXADAS = (
    "Recebi suas informações e já avisei o NUDECON, mas não consegui anexar as imagens da carteirinha. "
    "Vou encaminhar seu atendimento para a equipe, que vai pedir as imagens para dar continuidade."
)
# O envio do e-mail ao NUDECON falhou (#405): a pessoa não pode ficar sem atendimento.
MENSAGEM_FALHA_ENVIO_EMAIL = "Não consegui enviar o seu pedido agora. Vou encaminhar seu atendimento para a equipe dar continuidade."
# A consulta do CPF da outra pessoa no Verde falhou (#433).
MENSAGEM_FALHA_INFRA_VERDE = "Não consegui consultar o cadastro agora. Vou encaminhar seu atendimento para a equipe."
# Qualquer falha inesperada do fluxo: o assistido não pode ficar sem atendimento (#329).
MENSAGEM_ERRO_INTERNO = "Tive um problema para continuar o seu atendimento. Vou encaminhar para a equipe dar continuidade."
MENSAGEM_HANDOFF = "Vou encaminhar seu atendimento para um atendente humano."
