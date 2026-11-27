"""Testes unitários da coexistência entre o modo Verde e o modo de dúvidas com segundo agente conferidor."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from rag.chain import ExplicadorVerde
from rag.prompt import RECUSA_PADRAO_DUVIDAS, RECUSA_PADRAO_VERDE


class _MensagemFalsa:
    def __init__(self, content: str, input_tokens: int = 100, output_tokens: int = 20) -> None:
        self.content = content
        self.usage_metadata = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }


class _RecuperadorFalso:
    def __init__(self, resultados: list[dict[str, Any]]) -> None:
        self.resultados = resultados
        self.consultas: list[str] = []

    def buscar(self, consulta: str, limite: int = 3) -> list[dict[str, Any]]:
        self.consultas.append(consulta)
        return self.resultados[:limite]


class _ModeloSequencialFalso:
    def __init__(self, respostas: list[_MensagemFalsa]) -> None:
        self.respostas = list(respostas)
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> _MensagemFalsa:
        self.prompts.append(prompt)
        if not self.respostas:
            raise AssertionError("Mais chamadas ao modelo do que o esperado.")
        return self.respostas.pop(0)


def _trecho_exemplo(similaridade: float = 0.65) -> dict[str, Any]:
    return {
        "id": "fluxo-pomar-trecho-1",
        "conteudo": "A participação na sessão de conciliação on-line é gratuita. Envie 3 documentos em até 24 horas.",
        "fonte": "Fluxo para o POMAR.docx",
        "endpoint": "",
        "metodo": "",
        "assunto": "Fluxo para o POMAR",
        "similaridade": similaridade,
    }


class TestModoDuvidasECoexistenciaVerde(unittest.TestCase):
    def _criar_explicador(
        self,
        resultados: list[dict[str, Any]],
        respostas_modelo: list[_MensagemFalsa],
    ) -> tuple[ExplicadorVerde, _RecuperadorFalso, _ModeloSequencialFalso]:
        recuperador = _RecuperadorFalso(resultados)
        modelo = _ModeloSequencialFalso(respostas_modelo)
        with patch("rag.chain.ChatBedrockConverse", return_value=modelo):
            explicador = ExplicadorVerde(recuperador)  # type: ignore[arg-type]
        return explicador, recuperador, modelo

    def test_modo_duvidas_aprova_resposta_fundamentada_e_soma_tokens_dos_dois_agentes(self) -> None:
        explicador, recuperador, modelo = self._criar_explicador(
            [_trecho_exemplo()],
            [
                _MensagemFalsa("Não precisa pagar nada, a sessão de conciliação on-line é gratuita.", input_tokens=400, output_tokens=18),
                _MensagemFalsa(
                    "VEREDITO: APROVAR\nMOTIVO: A gratuidade consta literalmente no trecho.",
                    input_tokens=500,
                    output_tokens=22,
                ),
            ],
        )

        resultado = explicador.responder_duvida("Precisa pagar para participar da conversa de acordo?")

        self.assertEqual(recuperador.consultas, ["Precisa pagar para participar da conversa de acordo?"])
        self.assertEqual(resultado["modo"], "duvidas")
        self.assertEqual(resultado["acao"], "respondeu")
        self.assertTrue(resultado["respondeu"])
        self.assertFalse(resultado["recusou"])
        self.assertIsNone(resultado["motivo_recusa"])
        self.assertEqual(resultado["resposta"], "Não precisa pagar nada, a sessão de conciliação on-line é gratuita.")
        self.assertEqual(resultado["tokens_entrada"], 900)
        self.assertEqual(resultado["tokens_saida"], 40)
        self.assertEqual(len(resultado["trechos_usados"]), 1)
        self.assertEqual(len(modelo.prompts), 2)

    def test_segundo_agente_troca_resposta_inventada_pela_recusa_padrao(self) -> None:
        explicador, _, modelo = self._criar_explicador(
            [_trecho_exemplo()],
            [
                _MensagemFalsa("A Defensoria cobra 2 salários mínimos para o divórcio.", input_tokens=420, output_tokens=15),
                _MensagemFalsa(
                    "VEREDITO: RECUSAR\nMOTIVO: O trecho não menciona cobrança em salários mínimos nem divórcio.",
                    input_tokens=520,
                    output_tokens=25,
                ),
            ],
        )

        resultado = explicador.responder_duvida("Quanto que a Defensoria cobra de taxa para dar entrada no divórcio consensual?")

        self.assertEqual(resultado["modo"], "duvidas")
        self.assertEqual(resultado["acao"], "recusou")
        self.assertFalse(resultado["respondeu"])
        self.assertTrue(resultado["recusou"])
        self.assertEqual(resultado["motivo_recusa"], "agente_conferidor")
        self.assertEqual(resultado["resposta"], RECUSA_PADRAO_DUVIDAS)
        self.assertEqual(resultado["explicacao"], RECUSA_PADRAO_DUVIDAS)
        self.assertEqual(resultado["tokens_entrada"], 940)
        self.assertEqual(resultado["tokens_saida"], 40)
        self.assertEqual(len(modelo.prompts), 2)

    def test_recusa_do_primeiro_agente_nao_chama_segundo_agente(self) -> None:
        explicador, _, modelo = self._criar_explicador(
            [_trecho_exemplo()],
            [
                _MensagemFalsa(RECUSA_PADRAO_DUVIDAS, input_tokens=380, output_tokens=28),
            ],
        )

        resultado = explicador.responder_duvida("A defensoria abre domingo de manhã para eu levar os papéis da pensão?")

        self.assertEqual(resultado["acao"], "recusou")
        self.assertEqual(resultado["motivo_recusa"], "agente_respondedor")
        self.assertEqual(resultado["resposta"], RECUSA_PADRAO_DUVIDAS)
        self.assertEqual(resultado["tokens_entrada"], 380)
        self.assertEqual(resultado["tokens_saida"], 28)
        self.assertIsNone(resultado["chamadas"]["agente_conferidor"])
        self.assertEqual(len(modelo.prompts), 1)

    def test_sem_trechos_acima_do_limiar_recusa_sem_chamar_modelo(self) -> None:
        explicador, _, modelo = self._criar_explicador(
            [_trecho_exemplo(similaridade=0.15)],
            [],
        )

        resultado = explicador.responder_duvida("Fiz um empréstimo ontem, posso cancelar em 7 dias?")

        self.assertEqual(resultado["acao"], "recusou")
        self.assertEqual(resultado["motivo_recusa"], "sem_trechos_acima_do_limiar")
        self.assertEqual(resultado["resposta"], RECUSA_PADRAO_DUVIDAS)
        self.assertEqual(resultado["tokens_entrada"], 0)
        self.assertEqual(resultado["tokens_saida"], 0)
        self.assertEqual(resultado["trechos_usados"], [])
        self.assertEqual(len(modelo.prompts), 0)

    def test_roteamento_automatico_escolhe_modo_verde_para_requisicao_do_verde(self) -> None:
        trecho_verde = {
            "id": "get-integra-cep-trecho-1",
            "conteudo": "Endpoint: GET /integra/cep/{codigoCep}\nResposta HTTP 400: CEP inválido.",
            "fonte": "swagger.json",
            "endpoint": "/integra/cep/{codigoCep}",
            "metodo": "GET",
            "assunto": "CEP",
            "similaridade": 0.72,
        }
        explicador, recuperador, _ = self._criar_explicador(
            [trecho_verde],
            [
                _MensagemFalsa("VERDE", input_tokens=190, output_tokens=3),
                _MensagemFalsa("O CEP informado foi recusado pela validação do sistema Verde.", input_tokens=310, output_tokens=16),
            ],
        )

        resultado = explicador.explicar("CEP inválido", endpoint="/integra/cep/{codigoCep}", metodo="GET", status_http=400)

        self.assertEqual(resultado["modo"], "verde")
        self.assertIn("Mensagem da API Verde: CEP inválido", recuperador.consultas[0])
        self.assertEqual(resultado["explicacao"], "O CEP informado foi recusado pela validação do sistema Verde.")
        self.assertEqual(resultado["roteamento_modo"]["modo"], "verde")

    def test_roteamento_automatico_escolhe_modo_duvidas_para_pergunta_da_pessoa(self) -> None:
        explicador, recuperador, _ = self._criar_explicador(
            [_trecho_exemplo()],
            [
                _MensagemFalsa("DUVIDAS", input_tokens=200, output_tokens=4),
                _MensagemFalsa("São 3 documentos em até 24 horas.", input_tokens=410, output_tokens=12),
                _MensagemFalsa("VEREDITO: APROVAR\nMOTIVO: Consta nos trechos.", input_tokens=490, output_tokens=14),
            ],
        )

        resultado = explicador.explicar("Quantos documentos e qual o prazo para participar da conciliação?")

        self.assertEqual(resultado["modo"], "duvidas")
        self.assertEqual(recuperador.consultas[0], "Quantos documentos e qual o prazo para participar da conciliação?")
        self.assertEqual(resultado["acao"], "respondeu")
        self.assertEqual(resultado["resposta"], "São 3 documentos em até 24 horas.")
        self.assertEqual(resultado["roteamento_modo"]["modo"], "duvidas")

    def test_modo_verde_preserva_recusa_original_quando_sem_trechos(self) -> None:
        explicador, _, _ = self._criar_explicador([_trecho_exemplo(similaridade=0.10)], [])

        resultado = explicador.explicar("Erro desconhecido", modo="verde")

        self.assertEqual(resultado["modo"], "verde")
        self.assertEqual(resultado["explicacao"], RECUSA_PADRAO_VERDE)
        self.assertEqual(resultado["acao"], "recusou")


if __name__ == "__main__":
    unittest.main()
