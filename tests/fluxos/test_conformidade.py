"""Teste de conformidade dos fluxos (#323): as 14 regras do molde, em todo
fluxo registrado e no grafo padrão dos planejados.

Um fluxo novo entra sozinho, pelo registro (`fluxos_por_id`). Se ele pergunta
algo de texto, declare em `ROTEIROS` as respostas que o passeio dá; sem elas,
o passeio responde `TEXTO_PADRAO`, e uma validação de formato pode prender a
conversa (falha "fim").

As regras A13 e A14 valem para fluxo novo. Os fluxos de hoje que não passam
nelas ficam em `EXCECOES`, cada uma ligada à issue que a corrige. A lista só
diminui: quando a correção entra, a exceção vencida faz o teste falhar até ser
apagada, e acrescentar uma exige mudar `EXCECOES_INICIAIS`, à vista na revisão.
Decisão de 2026-10-23, registrada na #208.
"""

from __future__ import annotations

from typing import Any

import pytest

from maria.fluxos import FLUXO_PADRAO, ID_PESSOA_PRESA, ID_VIOLENCIA_DOMESTICA, fluxos_por_id
from maria.fluxos.pessoa_presa import graph as grafo_pessoa_presa
from maria.ia.classificar import classificar_entre_opcoes
from tests.fluxos import conformidade, molde_de_teste
from tests.fluxos.conformidade import Falhas, FluxoSobConferencia, Roteiro, conferir
from tests.integracoes.conftest import TransporteFalso

# Respostas de texto dos subgrafos de identificação, cadastro e endereço.
COMUNS = (
    (r"CPF", "12345678909"),
    (r"nome completo", "Pessoa de Teste"),
    (r"data de nascimento", "01/01/1990"),
    (r"CEP", "20000-000"),
    (r"rua/avenida", "Rua de Teste"),
    (r"Qual o número\?", "123"),
    (r"complemento", "não"),
    (r"bairro", "Centro"),
    (r"município", "Rio de Janeiro"),
    (r"UF", "RJ"),
    (r"número do processo", "0000088-95.2026.8.19.0010"),
)
# CPF que o Verde em mock não encontra: leva ao cadastro.
CPF_NOVO = ((r"CPF", "00000000000"),)
PESSOA_PRESA = ((r"RG", "123456789"), (r"parentesco", "sou a mãe dele"), *COMUNS)

ROTEIROS: dict[str, tuple[Roteiro, ...]] = {
    ID_PESSOA_PRESA: (
        Roteiro({}, PESSOA_PRESA),
        Roteiro({"viaOrquestrador": True}, PESSOA_PRESA),
        Roteiro({"viaOrquestrador": True}, (*CPF_NOVO, *PESSOA_PRESA)),
    ),
    ID_VIOLENCIA_DOMESTICA: (Roteiro({}, COMUNS), Roteiro({}, (*CPF_NOVO, *COMUNS))),
}

EXCECOES: dict[tuple[str, str], str] = {
    ("pessoa-presa", "A13"): "#212",
    ("pessoa-presa", "A14"): "#239",
    ("violencia-domestica", "A14"): "#239",
}
EXCECOES_INICIAIS = frozenset({("pessoa-presa", "A13"), ("pessoa-presa", "A14"), ("violencia-domestica", "A14")})

FLUXOS = [FluxoSobConferencia.do_registro(id_, config, ROTEIROS.get(id_, (Roteiro(),))) for id_, config in fluxos_por_id.items()]
FLUXOS.append(FluxoSobConferencia.do_registro(None, FLUXO_PADRAO))


def falhas_que_valem(nome: str, falhas: Falhas) -> list[str]:
    erros = [f"{regra}: {falha}" for regra, lista in falhas.items() if (nome, regra) not in EXCECOES for falha in lista]
    for (fluxo, regra), issue in EXCECOES.items():
        if fluxo == nome and not falhas[regra]:
            erros.append(
                f"exceção vencida: {fluxo} passa na {regra}. A correção ({issue}) entrou? Apague a exceção em EXCECOES e EXCECOES_INICIAIS."
            )
    return erros


@pytest.mark.parametrize("fluxo", FLUXOS, ids=lambda f: f.nome)
async def test_fluxo_segue_o_molde(fluxo: FluxoSobConferencia, transporte: TransporteFalso) -> None:
    erros = falhas_que_valem(fluxo.nome, await conferir(fluxo, transporte))
    assert not erros, f"{fluxo.nome} fora do molde (docs/novo-fluxo.md):\n" + "\n".join(erros)


def test_a_lista_de_excecoes_so_diminui() -> None:
    assert set(EXCECOES) <= EXCECOES_INICIAIS, "exceção nova no molde: só com decisão registrada na #208"


def test_toda_excecao_aponta_um_fluxo_registrado() -> None:
    nomes = {f.nome for f in FLUXOS}
    assert {fluxo for fluxo, _ in EXCECOES} <= nomes


# --- Verificação por mutação ---------------------------------------------------------


async def test_o_fluxo_de_teste_segue_o_molde(transporte: TransporteFalso) -> None:
    falhas = await conferir(molde_de_teste.montar(), transporte)
    assert not falhas_que_valem("fluxo-de-teste", falhas)


@pytest.mark.parametrize(("defeito", "regra"), molde_de_teste.DEFEITOS.items())
async def test_cada_defeito_quebra_a_sua_regra(defeito: str, regra: str, transporte: TransporteFalso) -> None:
    falhas = await conferir(molde_de_teste.montar(defeito), transporte)
    assert falhas[regra], f"o defeito {defeito!r} passou pela regra {regra}"


async def test_a_correcao_da_212_faz_a_excecao_quebrar_o_teste(transporte: TransporteFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simula a correção da #212 no código de pessoa presa: a escolha da IA fora
    da lista vira "nenhum", e o fluxo grava "Outro", como já faz com "nenhum"."""

    async def com_a_lista_conferida(mensagem: str, sistema: str, ids: list[str]) -> Any:
        resultado = dict(await classificar_entre_opcoes(mensagem, sistema, ids))
        if resultado.get("escolhaId") not in ids:
            resultado["escolhaId"] = None
        return resultado

    monkeypatch.setattr(grafo_pessoa_presa, "classificar_entre_opcoes", com_a_lista_conferida)
    pessoa_presa = next(f for f in FLUXOS if f.nome == "pessoa-presa")
    falhas = await conferir(pessoa_presa, transporte)
    assert not falhas["A13"]
    erros = falhas_que_valem("pessoa-presa", falhas)
    assert len(erros) == 1 and erros[0].startswith("exceção vencida: pessoa-presa passa na A13. A correção (#212)"), erros


@pytest.mark.parametrize("nome", ["pessoa-presa", "violencia-domestica"])
async def test_a_correcao_da_239_faz_a_excecao_quebrar_o_teste(
    nome: str, transporte: TransporteFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A #239 muda 7 chamadas ao Verde em dois fluxos; simulá-la no código seria
    fazê-la. Aqui a A14 passa por troca do passeio do Verde, o que confere a
    contabilidade das duas exceções, e não o fluxo."""

    async def sem_falhas(*args: Any) -> None:
        return None

    monkeypatch.setattr(conformidade, "_passeios_com_verde_falhando", sem_falhas)
    fluxo = next(f for f in FLUXOS if f.nome == nome)
    erros = falhas_que_valem(nome, await conferir(fluxo, transporte))
    assert [e for e in erros if e.startswith("exceção vencida")] == [
        f"exceção vencida: {nome} passa na A14. A correção (#239) entrou? Apague a exceção em EXCECOES e EXCECOES_INICIAIS."
    ]
