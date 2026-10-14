import json
import os
import socket
import time

import pytest

from maria.shared.logger import configurar_logging_stdlib, logger


def _linhas(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(linha) for linha in capsys.readouterr().out.splitlines() if linha.strip()]


def test_envelope_pino_com_campos_de_negocio_no_primeiro_nivel(capsys: pytest.CaptureFixture[str]) -> None:
    antes = time.time_ns() // 1_000_000
    logger.info("[verde] apenado: chamada concluída", chatId="c1", evento="verde_chamada", chamada="apenado", duracaoMs=12)
    depois = time.time_ns() // 1_000_000
    [linha] = _linhas(capsys)
    assert list(linha) == ["level", "time", "pid", "hostname", "chatId", "evento", "chamada", "duracaoMs", "msg"]
    assert linha["level"] == 30
    assert isinstance(linha["time"], int)
    assert antes <= linha["time"] <= depois
    assert linha["pid"] == os.getpid()
    assert linha["hostname"] == socket.gethostname()
    assert linha["duracaoMs"] == 12
    assert linha["msg"] == "[verde] apenado: chamada concluída"


def test_linha_igual_ao_formato_gravado_do_pino_em_develop(capsys: pytest.CaptureFixture[str]) -> None:
    # Mesma linha de tests/fixtures/contrato/logs/a-*.ndjson, menos time/pid/hostname.
    logger.warn("[checkpoint] DATABASE_URL ausente — usando MemorySaver (não persiste)")
    bruto = capsys.readouterr().out.strip()
    assert '"msg":"[checkpoint] DATABASE_URL ausente — usando MemorySaver (não persiste)"}' in bruto
    assert bruto.startswith('{"level":40,"time":')
    assert ", " not in bruto.split('"msg"')[0]


@pytest.mark.parametrize(
    ("metodo", "nivel"),
    [("info", 30), ("warn", 40), ("warning", 40), ("error", 50)],
)
def test_niveis_numericos_do_pino(capsys: pytest.CaptureFixture[str], metodo: str, nivel: int) -> None:
    getattr(logger, metodo)("x")
    [linha] = _linhas(capsys)
    assert linha["level"] == nivel


def test_debug_nao_sai_com_o_nivel_padrao(capsys: pytest.CaptureFixture[str]) -> None:
    logger.debug("não deve aparecer")
    assert capsys.readouterr().out == ""


def test_campo_none_nao_aparece_na_linha(capsys: pytest.CaptureFixture[str]) -> None:
    logger.info("atendimento finalizado", evento="atendimento_finalizado", motivoHandoff=None, fluxoId=None)
    [linha] = _linhas(capsys)
    assert "motivoHandoff" not in linha
    assert "fluxoId" not in linha
    assert None not in linha.values()


def test_campo_aninhado_com_none_tambem_omite_a_chave(capsys: pytest.CaptureFixture[str]) -> None:
    logger.info("x", tokensGastos={"input": 1, "output": None, "total": 1})
    [linha] = _linhas(capsys)
    assert linha["tokensGastos"] == {"input": 1, "total": 1}


def test_erro_serializado_como_o_err_do_pino(capsys: pytest.CaptureFixture[str]) -> None:
    try:
        raise TypeError("Cannot read properties of null")
    except TypeError as erro:
        logger.error("falhou", err=erro)
    [linha] = _linhas(capsys)
    err = linha["err"]
    assert isinstance(err, dict)
    assert list(err) == ["type", "message", "stack"]
    assert err["type"] == "TypeError"
    assert err["message"] == "Cannot read properties of null"
    assert "TypeError: Cannot read properties of null" in err["stack"]


def test_utf8_cru_sem_escape(capsys: pytest.CaptureFixture[str]) -> None:
    logger.info("violência doméstica — órgão")
    assert "violência doméstica — órgão" in capsys.readouterr().out


def test_logs_info_de_bibliotecas_nao_saem(capsys: pytest.CaptureFixture[str]) -> None:
    # psycopg_pool registra cada conexão entregue e httpx registra cada requisição
    # com a URL completa (no Verde, com ?cpf=). Nenhum dos dois pode chegar ao stdout.
    import logging

    raiz = logging.getLogger()
    estado = raiz.handlers[:], raiz.level, {n: logging.getLogger(n).level for n in ("uvicorn", "uvicorn.error", "uvicorn.access")}
    try:
        configurar_logging_stdlib()
        logging.getLogger("psycopg.pool").info("connection given by %r", "pool-1")
        logging.getLogger("httpx").info("HTTP Request: GET https://verde/pessoa?cpf=00000000000")
        logging.getLogger("uvicorn.error").info("Application startup complete.")
        logging.getLogger("psycopg.pool").warning("aviso do pool")
    finally:
        raiz.handlers, raiz.level = estado[0], estado[1]
        for nome, nivel in estado[2].items():
            logging.getLogger(nome).setLevel(nivel)
    mensagens = [linha["msg"] for linha in _linhas(capsys)]
    assert mensagens == ["Application startup complete.", "aviso do pool"]


def test_debug_global_nao_libera_bibliotecas_com_conteudo_do_atendimento(capsys: pytest.CaptureFixture[str]) -> None:
    # Cenário: alguém baixa o nível raiz para DEBUG para depurar um incidente. O
    # botocore registraria o corpo da chamada ao Bedrock (prompt com o relato) e o
    # httpx a URL com ?cpf=. Nenhum dos dois pode sair; um WARNING continua saindo.
    import logging

    from maria.shared.logger import BIBLIOTECAS_COM_NIVEL_FIXO

    nomes = ("uvicorn", "uvicorn.error", "uvicorn.access", *BIBLIOTECAS_COM_NIVEL_FIXO)
    raiz = logging.getLogger()
    estado = raiz.handlers[:], raiz.level, {n: logging.getLogger(n).level for n in nomes}
    try:
        configurar_logging_stdlib()
        raiz.setLevel(logging.DEBUG)
        logging.getLogger("botocore.endpoint").debug("Making request ... body: {'messages': [{'content': 'relato'}]}")
        logging.getLogger("botocore.endpoint").info("Making request ... (info)")
        logging.getLogger("httpx").info("HTTP Request: GET https://verde/pessoa?cpf=00000000000")
        logging.getLogger("httpcore.http11").debug("send_request_headers")
        logging.getLogger("urllib3.connectionpool").debug("https://bedrock-runtime:443 POST /model/x/converse")
        logging.getLogger("psycopg.pool").info("connection given by 'pool-1'")
        logging.getLogger("botocore.retryhandler").warning("aviso do botocore")
    finally:
        raiz.handlers, raiz.level = estado[0], estado[1]
        for nome, nivel in estado[2].items():
            logging.getLogger(nome).setLevel(nivel)
    mensagens = [linha["msg"] for linha in _linhas(capsys)]
    assert mensagens == ["aviso do botocore"]


def test_bibliotecas_com_nivel_fixo_cobrem_aws_http_e_banco() -> None:
    from maria.shared.logger import BIBLIOTECAS_COM_NIVEL_FIXO

    esperadas = {"botocore", "boto3", "urllib3", "s3transfer", "httpx", "httpcore", "psycopg"}
    esperadas |= {"langchain_aws", "langsmith", "httpx2", "httpcore2"}
    assert esperadas <= set(BIBLIOTECAS_COM_NIVEL_FIXO)


def test_bytes_sempre_em_utf8_mesmo_com_codificacao_local_diferente(capfdbinary: pytest.CaptureFixture[bytes]) -> None:
    # Achado ao rodar o servidor no Windows com a saída redirecionada: o Python
    # usava cp1252 e corrompia o "—". O pino escreve sempre UTF-8.
    logger.info("[checkpoint] DATABASE_URL ausente — usando MemorySaver (não persiste)")
    bruto = capfdbinary.readouterr().out
    assert "ausente — usando MemorySaver (não persiste)".encode() in bruto


def test_logging_da_biblioteca_padrao_sai_no_mesmo_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    import logging

    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        configurar_logging_stdlib()
        logging.getLogger("uvicorn.error").warning("Started server process")
    finally:
        raiz.handlers, raiz.level = handlers, nivel
    [linha] = _linhas(capsys)
    assert linha["level"] == 40
    assert linha["msg"] == "Started server process"
