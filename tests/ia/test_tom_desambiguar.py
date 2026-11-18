"""#508: o Qwen simpático na pergunta de desambiguação, sem emoji nos temas sensíveis.

Decisões da Nicole (2026-11-16): o tom só para o Qwen (a produção, com o Haiku, não muda) e, nos temas
sensíveis (violência doméstica e pessoa presa), nenhum emoji, com trava no código além da regra no prompt.
"""

import json
from typing import Any

import pytest

from maria.ia import desambiguar
from maria.ia.ajuste_qwen import SUFIXO_DESAMBIGUAR, SUFIXO_TOM_DESAMBIGUAR
from maria.ia.desambiguar import CandidatoParaDesambiguar, montar_sistema, sem_emoji, tem_tema_sensivel
from maria.ia.tom import medir_tom

PRESA: CandidatoParaDesambiguar = {
    "id": "1",
    "nome": "pessoa-presa",
    "descricao": "Alguém buscando informação sobre uma pessoa que está presa",
}
VD: CandidatoParaDesambiguar = {
    "id": "2",
    "nome": "violencia-domestica",
    "descricao": "Mulher vítima de violência doméstica buscando ajuda",
}
AGENDA: CandidatoParaDesambiguar = {"id": "3", "nome": "ver-meus-agendamentos", "descricao": "Quer consultar ou remarcar um agendamento"}
EMPRESA: CandidatoParaDesambiguar = {
    "id": "4",
    "nome": "empresas e mei",
    "descricao": "Atendimento para empresas sem condições de pagar advogados",
}


def test_com_o_qwen_o_prompt_ganha_o_tom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEDROCK_MODEL_ID", "qwen.qwen3-vl-235b-a22b")
    sistema = montar_sistema([AGENDA, PRESA])
    assert sistema.endswith(SUFIXO_DESAMBIGUAR + SUFIXO_TOM_DESAMBIGUAR)
    assert "acolhedor" in sistema and "nenhum emoji" in sistema


def test_com_o_haiku_o_prompt_fica_como_antes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    sistema = montar_sistema([AGENDA, PRESA])
    assert SUFIXO_TOM_DESAMBIGUAR not in sistema and SUFIXO_DESAMBIGUAR not in sistema
    assert sistema.endswith("sem citar nomes técnicos/internos.")


@pytest.mark.parametrize(
    ("candidatos", "sensivel"),
    [([AGENDA, PRESA], True), ([VD, AGENDA], True), ([AGENDA, EMPRESA], False)],
    ids=["pessoa presa", "violência doméstica", "empresa não é presa"],
)
def test_tema_sensivel(candidatos: list[CandidatoParaDesambiguar], sensivel: bool) -> None:
    assert tem_tema_sensivel(candidatos) is sensivel


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Você quer saber do processo ou da visita? 😊", "Você quer saber do processo ou da visita?"),
        ("Certo 🙏, você já tem um processo?", "Certo, você já tem um processo?"),
        ("Tudo bem ❤️ Me conta: é sobre a agenda?", "Tudo bem Me conta: é sobre a agenda?"),
        ("Sem emoji nenhum?", "Sem emoji nenhum?"),
        # Tom de pele e junção (família): continuam saindo depois da expressão reescrita para o CodeQL (#502).
        ("Oi 👋🏽, é sobre a visita?", "Oi, é sobre a visita?"),
        ("Família 👨‍👩‍👧 presa? Não: é sobre o processo?", "Família presa? Não: é sobre o processo?"),
        ("Estrela ⭐ e sol ☀️ saem.", "Estrela e sol saem."),
    ],
)
def test_sem_emoji(texto: str, esperado: str) -> None:
    assert sem_emoji(texto) == esperado


async def _gerar(monkeypatch: pytest.MonkeyPatch, pergunta: str, candidatos: list[CandidatoParaDesambiguar]) -> Any:
    async def invocar(_modelo: Any, _esquema: Any, _sistema: str, _relato: str) -> dict[str, Any]:
        return {"parsed": {"pergunta": pergunta}, "raw": None}

    monkeypatch.setattr(desambiguar, "invocar_estruturado", invocar)
    monkeypatch.setenv("APP_ENV", "development")
    return await desambiguar.gerar_pergunta_desambiguacao("relato inventado", candidatos)


async def test_no_tema_sensivel_a_pergunta_sai_sem_emoji(monkeypatch: pytest.MonkeyPatch) -> None:
    r = await _gerar(monkeypatch, "É sobre a pessoa presa ou sobre o seu agendamento? 😊", [PRESA, AGENDA])
    assert r["pergunta"] == "É sobre a pessoa presa ou sobre o seu agendamento?"
    assert r["viaIA"] is True


async def test_fora_do_tema_sensivel_o_emoji_fica(monkeypatch: pytest.MonkeyPatch) -> None:
    r = await _gerar(monkeypatch, "É para remarcar ou para ver um processo? 😊", [AGENDA, EMPRESA])
    assert r["pergunta"].endswith("😊")


# ── O tom medido na produção, só em números (decisão da Nicole, 2026-11-17) ──


def test_medir_tom_conta_as_regras() -> None:
    m = medir_tom("Você quer ajuda com o exame ou com a cirurgia? 😊", sensivel=False)
    assert m == {
        "palavras": 10,
        "ateLimiteDePalavras": True,
        "terminaEmPergunta": True,  # o emoji depois do "?" não conta
        "semTermoTecnico": True,
        "ofereceAlternativas": True,
        "temAcolhimento": True,
        "comEmoji": True,
        "temaSensivel": False,
        "semEmojiNoTemaSensivel": True,
    }
    sensivel = medir_tom("É sobre pessoa-presa? 🙏", sensivel=True)
    assert not sensivel["semTermoTecnico"] and not sensivel["semEmojiNoTemaSensivel"]
    assert medir_tom("Você precisa proteger-se agora ou abrir um processo?", sensivel=True)["semTermoTecnico"]


async def test_o_log_do_tom_tem_os_numeros_e_nunca_o_texto(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("BEDROCK_MODEL_ID", "qwen.qwen3-vl-235b-a22b")
    pergunta = "É sobre a pessoa presa ou sobre o seu agendamento? 😊"
    await _gerar(monkeypatch, pergunta, [PRESA, AGENDA])
    linhas = [json.loads(linha) for linha in capsys.readouterr().out.splitlines() if linha.strip()]
    [tom] = [linha for linha in linhas if linha.get("evento") == "desambiguacao_tom"]
    assert tom["modelo"] == "qwen.qwen3-vl-235b-a22b"
    # Sim e não vão como 1 e 0, para o Visor somar.
    assert (tom["temaSensivel"], tom["emojiTirado"], tom["comEmoji"]) == (1, 1, 0)
    assert tom["palavras"] == 10 and tom["terminaEmPergunta"] == 1
    linha_inteira = json.dumps(tom, ensure_ascii=False)
    assert "pessoa presa" not in linha_inteira and "agendamento" not in linha_inteira, "o texto da pergunta nunca vai ao log"
    assert "relato inventado" not in linha_inteira, "o relato nunca vai ao log"
