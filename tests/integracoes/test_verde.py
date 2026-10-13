"""Verde: tradução de `src/integracoes/verde.test.ts` (8 testes de retry) e os
testes novos da spec do módulo integracoes (#219), com transporte falso, sem rede.

Os valores de referência de escape e de corpo foram calculados com o
encodeURIComponent e o JSON.stringify do Node (develop).
"""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from maria.integracoes import verde
from maria.integracoes.cliente_http import criar_cliente_http, definir_cliente_http, fechar_cliente_http
from maria.shared.logger import configurar_logging_stdlib
from tests.integracoes.conftest import URL_VERDE, TransporteFalso

# --- Tradução de verde.test.ts (issue #172) --------------------------------------


def resposta(status: int) -> httpx.Response:
    return httpx.Response(status)


class _Contador:
    def __init__(self) -> None:
        self.n = 0


async def test_sucesso_de_primeira_nao_retenta() -> None:
    c = _Contador()

    async def montar() -> httpx.Response:
        c.n += 1
        return resposta(200)

    resultado = await verde.chamar_verde_com_retry("teste", montar)
    assert c.n == 1
    assert resultado.ok is True


@pytest.mark.parametrize("status", [404, 422])
async def test_falha_de_negocio_nao_retenta(status: int) -> None:
    c = _Contador()

    async def montar() -> httpx.Response:
        c.n += 1
        return resposta(status)

    resultado = await verde.chamar_verde_com_retry("teste", montar)
    assert c.n == 1, f"{status} é resposta de negócio válida, não deveria retentar"
    assert resultado.ok is False
    assert resultado.falha_infra is False


async def test_500_retenta_ate_esgotar() -> None:
    c = _Contador()

    async def montar() -> httpx.Response:
        c.n += 1
        return resposta(500)

    resultado = await verde.chamar_verde_com_retry("teste", montar)
    assert c.n == verde.TENTATIVAS_RETRY_VERDE
    assert resultado.ok is False
    assert resultado.falha_infra is True


async def test_401_retenta_e_sucede_depois() -> None:
    c = _Contador()

    async def montar() -> httpx.Response:
        c.n += 1
        return resposta(401 if c.n < 2 else 200)

    resultado = await verde.chamar_verde_com_retry("teste", montar)
    assert c.n == 2
    assert resultado.ok is True


async def test_403_retenta_igual_401_e_500() -> None:
    c = _Contador()

    async def montar() -> httpx.Response:
        c.n += 1
        return resposta(403)

    resultado = await verde.chamar_verde_com_retry("teste", montar)
    assert c.n == verde.TENTATIVAS_RETRY_VERDE
    assert resultado.falha_infra is True


async def test_excecao_retenta_e_esgota() -> None:
    c = _Contador()

    async def montar() -> httpx.Response:
        c.n += 1
        raise TimeoutError("timeout simulado")

    resultado = await verde.chamar_verde_com_retry("teste", montar)
    assert c.n == verde.TENTATIVAS_RETRY_VERDE
    assert resultado.ok is False
    assert resultado.falha_infra is True
    assert resultado.res is None


async def test_excecao_na_primeira_sucesso_na_segunda() -> None:
    c = _Contador()

    async def montar() -> httpx.Response:
        c.n += 1
        if c.n == 1:
            raise TimeoutError("timeout simulado")
        return resposta(200)

    resultado = await verde.chamar_verde_com_retry("teste", montar)
    assert c.n == 2
    assert resultado.ok is True


# --- Auxiliares --------------------------------------------------------------------


def json_ok(dados: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=dados)


class CorpoQuePara(httpx.AsyncByteStream):
    """Entrega um pedaço e depois espera, para o prazo estourar no meio do corpo."""

    def __init__(self, primeiro: bytes, espera: float) -> None:
        self.primeiro = primeiro
        self.espera = espera

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.primeiro
        await asyncio.sleep(self.espera)
        yield b"}"


class CorpoCortado(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"dados": {"idPes'
        raise httpx.ReadError("conexão cortada no meio do corpo")


# --- 3.1.1 Redirect -----------------------------------------------------------------


async def test_1_apenado_com_302_segue_e_encontra(verde_real: TransporteFalso) -> None:
    async def tratar(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/integra/apenado":
            return httpx.Response(302, headers={"location": f"{URL_VERDE}/apenado-novo"})
        return json_ok({"dados": {"idPessoa": 2, "nome": "X"}})

    verde_real.tratador = tratar
    resultado = await verde.consultar_apenado_por_rg("123")
    assert resultado == {"encontrado": True, "idPessoa": 2, "nome": "X"}


@pytest.mark.parametrize(
    ("status", "metodo_esperado", "com_corpo"), [(302, "GET", False), (303, "GET", False), (307, "POST", True), (308, "POST", True)]
)
async def test_1b_redirect_do_encaminhamento_troca_metodo_como_o_fetch(
    verde_real: TransporteFalso, status: int, metodo_esperado: str, com_corpo: bool
) -> None:
    async def tratar(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/encaminhar"):
            return httpx.Response(status, headers={"location": f"{URL_VERDE}/destino"})
        return json_ok({"dados": {"id": 5}}, 201)

    verde_real.tratador = tratar
    await verde.criar_encaminhamento_violencia_domestica({"idPessoa": 1, "idOrgao": 2, "urgente": False})
    segunda = verde_real.requisicoes[1]
    assert segunda.method == metodo_esperado
    assert (verde_real.corpos[1] != b"") is com_corpo


async def test_1b_redirect_para_outra_origem_remove_authorization_e_mantem_client_id(verde_real: TransporteFalso) -> None:
    async def tratar(req: httpx.Request) -> httpx.Response:
        if req.url.host == "verde.teste":
            return httpx.Response(302, headers={"location": "https://outra-origem.teste/x"})
        return json_ok({"dados": {"idPessoa": 1}})

    verde_real.tratador = tratar
    await verde.consultar_pessoa_por_cpf("1")
    destino = verde_real.requisicoes[1]
    assert "authorization" not in destino.headers
    assert destino.headers["x-client-id"] == "cliente-de-teste"


# --- 3.1.2 Prazo total por tentativa ---------------------------------------------------


@pytest.fixture
def prazo_curto(monkeypatch: pytest.MonkeyPatch) -> float:
    monkeypatch.setattr(verde, "TIMEOUT_VERDE_S", 0.4)
    return 0.4


async def test_2_cabecalhos_dentro_do_prazo_encontra_e_fora_do_prazo_esgota(verde_real: TransporteFalso, prazo_curto: float) -> None:
    espera = {"s": prazo_curto * 0.5}

    async def tratar(_req: httpx.Request) -> httpx.Response:
        await asyncio.sleep(espera["s"])
        return json_ok({"dados": {"idPessoa": 9}})

    verde_real.tratador = tratar
    assert (await verde.consultar_apenado_por_rg("1"))["encontrado"] is True

    espera["s"] = prazo_curto * 2
    verde_real.requisicoes.clear()
    assert await verde.consultar_apenado_por_rg("1") == {"encontrado": False, "falhaInfra": True}
    assert len(verde_real.requisicoes) == verde.TENTATIVAS_RETRY_VERDE


async def test_2b_cada_tentativa_tem_o_proprio_prazo(verde_real: TransporteFalso, prazo_curto: float) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        if len(verde_real.requisicoes) < 3:
            await asyncio.sleep(prazo_curto * 1.5)
        return json_ok({"dados": {"idPessoa": 9}})

    verde_real.tratador = tratar
    assert (await verde.consultar_apenado_por_rg("1"))["encontrado"] is True
    assert len(verde_real.requisicoes) == 3


# --- 3.1.3 true/True e null na query string ----------------------------------------------


async def test_3_indicacao_ro_vai_como_true_e_false(verde_real: TransporteFalso) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return json_ok({"dados": []})

    verde_real.tratador = tratar
    await verde.consultar_orgaos_violencia_domestica(True, 123)
    await verde.consultar_orgaos_violencia_domestica(False, 123)
    assert [r.url.query for r in verde_real.requisicoes] == [b"indicacaoRO=true&idPessoa=123", b"indicacaoRO=false&idPessoa=123"]


async def test_3b_id_plantao_nulo_vai_como_null(verde_real: TransporteFalso) -> None:
    await verde.consultar_orgaos_plantao_violencia_domestica([1, None], 5)
    assert verde_real.requisicoes[0].url.query == b"idPlantao=1&idPlantao=null&idAssistido=5"


# --- 3.1.4 Escape igual ao encodeURIComponent ---------------------------------------------

REFERENCIA_ENCODE_URI_COMPONENT = {
    "123.456.789-01": "123.456.789-01",
    "0000000-00.0000.0.00.0000": "0000000-00.0000.0.00.0000",
    "a b/c?d=é": "a%20b%2Fc%3Fd%3D%C3%A9",
    "!*()~'_.-": "!*()~'_.-",
    "0001234-56.2024/8.19#0001": "0001234-56.2024%2F8.19%230001",
    "72.500-000 & co": "72.500-000%20%26%20co",
}


@pytest.mark.parametrize(("valor", "esperado"), list(REFERENCIA_ENCODE_URI_COMPONENT.items()))
async def test_4_escape_igual_ao_encode_uri_component(verde_real: TransporteFalso, valor: str, esperado: str) -> None:
    await verde.consultar_processo(valor)
    await verde.consultar_pessoa_por_cpf(valor)
    await verde.consultar_cep(valor)
    processo, pessoa, cep = verde_real.requisicoes
    assert processo.url.raw_path.decode() == f"/api/integra/processo/consultar/{esperado}"
    assert pessoa.url.raw_path.decode() == f"/api/integra/pessoa?cpf={esperado}"
    assert cep.url.raw_path.decode() == f"/api/integra/cep/{esperado}"


async def test_4b_numero_com_barra_e_um_segmento_so(verde_real: TransporteFalso) -> None:
    await verde.consultar_processo("0001234-56.2024/8.19.0001")
    assert verde_real.requisicoes[0].url.raw_path == b"/api/integra/processo/consultar/0001234-56.2024%2F8.19.0001"


# --- Corpos enviados -----------------------------------------------------------------


async def test_5_corpo_do_cadastro_igual_ao_json_stringify(verde_real: TransporteFalso) -> None:
    # Referência do Node: o complemento undefined some; o bairro null vai como null.
    verde_real.tratador = None
    await verde.cadastrar_pessoa(
        {
            "nome": "Ana Souza",
            "cpf": "123.456.789-01",
            "dataNascimento": "1990-05-04",
            "endereco": {"logradouro": "Rua São João", "numero": "10", "bairro": None, "uf": "RJ"},  # type: ignore[typeddict-item]
        }
    )
    assert (
        verde_real.corpos[0]
        == (
            '{"nome":"Ana Souza","cpf":"123.456.789-01","dtNascimento":"1990-05-04",'
            '"endereco":{"logradouro":"Rua São João","numero":"10","bairro":null,"uf":"RJ"}}'
        ).encode()
    )


async def test_6_corpo_do_encaminhamento_na_ordem_de_develop(verde_real: TransporteFalso) -> None:
    await verde.criar_encaminhamento_violencia_domestica({"idPessoa": 7, "idOrgao": 1226, "urgente": False})
    await verde.criar_encaminhamento_violencia_domestica({"idPessoa": 7, "idOrgao": 1226, "idLocalAtendimento": 1009, "urgente": True})
    assert verde_real.corpos == [
        b'{"idPessoa":7,"idOrgao":1226,"urgencia":false,"preferenciaAtendimento":"Remoto","fluxoEncaminhamento":"VIOLENCIA_DOMESTICA"}',
        '{"idPessoa":7,"idOrgao":1226,"idLocalAtendimento":1009,"urgencia":true,"preferenciaAtendimento":"Remoto",'
        '"fluxoEncaminhamento":"VIOLENCIA_DOMESTICA","motivoUrgencia":"Violência doméstica com Boletim de Ocorrência registrado"}'.encode(),
    ]


async def test_7_accept_por_chamada(verde_real: TransporteFalso) -> None:
    await verde.consultar_apenado_por_rg("1")
    await verde.consultar_processo("1")
    apenado, processo = verde_real.requisicoes
    assert apenado.headers["accept"] == "*/*"  # o POST /apenado não define accept; o fetch manda */*
    assert apenado.headers["content-type"] == "application/json"
    assert processo.headers["accept"] == "application/json"
    assert "content-type" not in processo.headers


async def test_8_proxy_do_ambiente_e_ignorado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    transporte = TransporteFalso()
    await fechar_cliente_http()
    definir_cliente_http(criar_cliente_http(httpx.MockTransport(transporte)))
    monkeypatch.setattr(verde, "VERDE_JWT_TOKEN", "t")
    monkeypatch.setattr(verde, "VERDE_API_URL", URL_VERDE)
    try:
        await verde.consultar_processo("1")
    finally:
        await fechar_cliente_http()
    assert len(transporte.requisicoes) == 1


# --- 3.3 Ausente, null e objeto vazio ---------------------------------------------------


async def test_9_apenado_dados_vazio_nao_encontrado_e_id_pessoa_null_encontrado(verde_real: TransporteFalso) -> None:
    respostas = iter([json_ok({"dados": {}}), json_ok({"dados": {"idPessoa": None}})])

    async def tratar(_req: httpx.Request) -> httpx.Response:
        return next(respostas)

    verde_real.tratador = tratar
    assert await verde.consultar_apenado_por_rg("1") == {"encontrado": False}
    assert await verde.consultar_apenado_por_rg("1") == {"encontrado": True, "idPessoa": None}


async def test_10_cep_com_dados_vazio_e_encontrado_sem_campos(verde_real: TransporteFalso) -> None:
    verde_real.tratador = None  # devolve {"dados": {}}
    assert await verde.consultar_cep("20000000") == {"encontrado": True}


async def test_11_plantao_mantem_id_null_e_descarta_sem_chave(verde_real: TransporteFalso) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return json_ok({"dados": [{"id": None}, {"tipo": "x"}]})

    verde_real.tratador = tratar
    assert await verde.consultar_plantao_vigente() == [{"id": None}]


async def test_12_orgao_de_plantao_objeto_unico_e_codigo(verde_real: TransporteFalso) -> None:
    respostas = iter([json_ok({"dados": {"id": 3, "nome": "Órgão"}}), json_ok({"codigo": "REQUISICAO_INVALIDA", "mensagem": "ligue 129"})])

    async def tratar(_req: httpx.Request) -> httpx.Response:
        return next(respostas)

    verde_real.tratador = tratar
    assert await verde.consultar_orgaos_plantao_violencia_domestica([1], 5) == {"encontrado": True, "orgaos": [{"id": 3, "nome": "Órgão"}]}
    assert await verde.consultar_orgaos_plantao_violencia_domestica([1], 5) == {
        "encontrado": False,
        "orgaos": [],
        "contactarCrc": True,
        "mensagemCrc": "ligue 129",
    }


async def test_12b_dados_como_objeto_no_endpoint_normal_lanca_como_develop(verde_real: TransporteFalso) -> None:
    # Achado da tradução: `(corpo.dados ?? []).map` lança TypeError em develop (500 na rota).
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return json_ok({"dados": {"id": 1}})

    verde_real.tratador = tratar
    with pytest.raises(TypeError):
        await verde.consultar_orgaos_violencia_domestica(False, 1)


async def test_13_encaminhamento_sem_id_e_com_infra_esgotada(verde_real: TransporteFalso) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return json_ok({"dados": {}}, 201)

    verde_real.tratador = tratar
    assert await verde.criar_encaminhamento_violencia_domestica({"idPessoa": 1, "idOrgao": 2, "urgente": False}) == {"sucesso": True}

    async def cair(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede")

    verde_real.tratador = cair
    assert await verde.criar_encaminhamento_violencia_domestica({"idPessoa": 1, "idOrgao": 2, "urgente": False}) == {
        "sucesso": False,
        "erro": "falha na chamada ao Verde (infra esgotada)",
    }


async def test_14_sentinela_de_cep_nao_aceita_digitos_unicode() -> None:
    assert verde.VERDE_JWT_TOKEN == "", "a suíte roda em modo mock"
    assert (await verde.consultar_cep("٠٠٠٠٠٠٠٠"))["encontrado"] is True
    assert (await verde.consultar_cep("00000-000"))["encontrado"] is False


# --- Observabilidade ------------------------------------------------------------------


def _linhas(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(linha) for linha in capsys.readouterr().out.splitlines() if linha.strip()]


async def test_17_logs_de_verde_chamada(verde_real: TransporteFalso, capsys: pytest.CaptureFixture[str]) -> None:
    respostas = iter([httpx.Response(500), json_ok({"dados": {"id": 1}})])

    async def tratar(_req: httpx.Request) -> httpx.Response:
        return next(respostas)

    verde_real.tratador = tratar
    capsys.readouterr()
    await verde.consultar_processo("1")
    erro, sucesso = _linhas(capsys)
    assert erro["level"] == 50
    assert erro["msg"] == "[verde] processo: HTTP não-ok"
    assert {k: erro[k] for k in ("status", "tipoErro", "evento", "chamada", "resultado", "tentativa", "tentativasRestantes")} == {
        "status": 500,
        "tipoErro": "auth_ou_infra",
        "evento": "verde_chamada",
        "chamada": "processo",
        "resultado": "nao_ok",
        "tentativa": 1,
        "tentativasRestantes": 2,
    }
    assert isinstance(erro["duracaoMs"], int)
    assert sucesso["msg"] == "[verde] processo: chamada concluída"
    assert sucesso["level"] == 30
    assert "chatId" not in sucesso and "fluxoId" not in sucesso  # fora de um run, ausentes e não null


# --- 3.2.1 Leitura do corpo: POST fora do retry, GET dentro ----------------------------------


async def test_18_encaminhamento_com_corpo_parado_envia_um_post_so(verde_real: TransporteFalso, prazo_curto: float) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(201, stream=CorpoQuePara(b'{"dados": {"id": 77', prazo_curto * 3))

    verde_real.tratador = tratar
    resultado = await verde.criar_encaminhamento_violencia_domestica({"idPessoa": 1, "idOrgao": 2, "urgente": False})
    assert len(verde_real.requisicoes) == 1
    assert resultado == {"sucesso": True}  # sem id: no grafo, vai para falha_encaminhamento


async def test_18b_cadastro_com_corpo_parado_envia_um_post_so(verde_real: TransporteFalso, prazo_curto: float) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(201, stream=CorpoQuePara(b'{"dados": {"idPessoa": 1', prazo_curto * 3))

    verde_real.tratador = tratar
    resultado = await verde.cadastrar_pessoa({"nome": "A", "cpf": "1", "dataNascimento": "2000-01-01"})
    assert len(verde_real.requisicoes) == 1
    assert resultado == {"sucesso": False, "erro": "Verde não devolveu idPessoa"}


async def test_18c_apenado_com_corpo_parado_envia_um_post_e_lanca(verde_real: TransporteFalso, prazo_curto: float) -> None:
    async def tratar(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=CorpoQuePara(b'{"dados": {"idPessoa": 1', prazo_curto * 3))

    verde_real.tratador = tratar
    with pytest.raises(TimeoutError):
        await verde.consultar_apenado_por_rg("1")
    assert len(verde_real.requisicoes) == 1


async def test_19_get_com_corpo_cortado_e_retentado(verde_real: TransporteFalso, capsys: pytest.CaptureFixture[str]) -> None:
    # Divergência aceita: em develop, o corte no meio do corpo de um GET vira 500.
    respostas = iter([httpx.Response(200, stream=CorpoCortado()), json_ok({"dados": {"idPessoa": 4}})])

    async def tratar(_req: httpx.Request) -> httpx.Response:
        return next(respostas)

    verde_real.tratador = tratar
    capsys.readouterr()
    assert (await verde.consultar_pessoa_por_cpf("1"))["encontrado"] is True
    assert len(verde_real.requisicoes) == 2
    assert [linha["level"] for linha in _linhas(capsys)] == [50, 30]


# --- Cabeçalhos, mock e logs sem dado pessoal -------------------------------------------------


async def test_20_cabecalhos_implicitos_do_fetch(verde_real: TransporteFalso) -> None:
    await verde.consultar_processo("1")
    cabecalhos = verde_real.requisicoes[0].headers
    assert cabecalhos["user-agent"] == "node"
    assert cabecalhos["accept-language"] == "*"
    assert cabecalhos["sec-fetch-mode"] == "cors"
    assert cabecalhos["authorization"] == "Bearer token-de-teste"
    assert cabecalhos["x-client-id"] == "cliente-de-teste"


async def test_21_interruptores_mock_lidos_a_cada_chamada(monkeypatch: pytest.MonkeyPatch) -> None:
    assert verde.VERDE_JWT_TOKEN == ""
    dados = {"idPessoa": 1, "idOrgao": 2, "urgente": False}
    assert await verde.criar_encaminhamento_violencia_domestica(dados) == {"sucesso": True, "id": 999999}  # type: ignore[arg-type]
    monkeypatch.setenv("MOCK_ENCAMINHAMENTO_FALHA", "true")
    assert await verde.criar_encaminhamento_violencia_domestica(dados) == {"sucesso": False, "erro": "falha simulada (mock)"}  # type: ignore[arg-type]
    monkeypatch.setenv("MOCK_CADASTRO_FALHA", "true")
    assert (await verde.cadastrar_pessoa({"nome": "A", "cpf": "1", "dataNascimento": "x"}))["sucesso"] is False
    monkeypatch.setenv("MOCK_PLANTAO_VIGENTE", "true")
    assert await verde.consultar_plantao_vigente() == [{"id": 1, "tipo": "Violência Doméstica (mock)"}]
    monkeypatch.setenv("MOCK_CEP_INCOMPLETO", "true")
    assert await verde.consultar_cep("20000000") == {"encontrado": True, "idUf": 19, "uf": "RJ"}
    # O token é lido na importação: mudar o ambiente depois não tira do modo mock.
    monkeypatch.setenv("VERDE_JWT_TOKEN", "agora-tem-token")
    assert await verde.consultar_processo("1") == {
        "encontrado": True,
        "id": 999999,
        "origem": "SEEU",
        "nomeAssunto": "Processo de Teste (mock)",
    }


@pytest.mark.parametrize("cenario", ["500", "timeout"])
async def test_22_cpf_nao_aparece_em_nenhuma_linha_de_log(
    verde_real: TransporteFalso, prazo_curto: float, capsys: pytest.CaptureFixture[str], cenario: str
) -> None:
    import logging

    cpf = "98765432100"

    async def tratar(_req: httpx.Request) -> httpx.Response:
        if cenario == "timeout":
            await asyncio.sleep(prazo_curto * 2)
        return httpx.Response(500)

    verde_real.tratador = tratar
    raiz = logging.getLogger()
    estado = raiz.handlers[:], raiz.level
    try:
        configurar_logging_stdlib()
        capsys.readouterr()
        await verde.consultar_pessoa_por_cpf(cpf)
    finally:
        raiz.handlers, raiz.level = estado
    saida = capsys.readouterr()
    assert cpf not in saida.out
    assert cpf not in saida.err
    assert len(_linhas_brutas(saida.out)) == verde.TENTATIVAS_RETRY_VERDE


def _linhas_brutas(texto: str) -> list[str]:
    return [linha for linha in texto.splitlines() if linha.strip()]
