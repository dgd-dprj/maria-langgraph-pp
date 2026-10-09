"""Integridade das fixtures de contrato HTTP (#209).

As fixtures foram gravadas com a aplicação TypeScript de develop @ 4e695f2
rodando de verdade (receita em comentário da #209). Elas são a única
referência executável do contrato com a Tykhe até o módulo `api`, que as
compara byte a byte. Este teste só garante que o conjunto está inteiro e
coerente; ele não testa a aplicação.
"""

import json
from pathlib import Path

PASTA = Path(__file__).parent / "fixtures" / "contrato"
TOTAL_DE_CASOS = 50


def _indice() -> list[dict[str, object]]:
    dados = json.loads((PASTA / "indice.json").read_text(encoding="utf-8"))
    assert isinstance(dados, list)
    return dados


def test_indice_tem_os_50_casos_com_nomes_unicos() -> None:
    nomes = [caso["nome"] for caso in _indice()]
    assert len(nomes) == TOTAL_DE_CASOS
    assert len(set(nomes)) == TOTAL_DE_CASOS


def test_cada_caso_do_indice_tem_um_arquivo_coerente_e_nenhum_sobra() -> None:
    arquivos = {p.stem for p in (PASTA / "http").glob("*.json")}
    assert arquivos == {caso["nome"] for caso in _indice()}
    for caso in _indice():
        fixture = json.loads((PASTA / "http" / f"{caso['nome']}.json").read_text(encoding="utf-8"))
        assert fixture["requisicao"]["metodo"] == caso["metodo"]
        assert fixture["requisicao"]["caminho"] == caso["caminho"]
        resposta = fixture["resposta"]
        assert resposta["status"] == caso["status"]
        assert {"status", "contentType", "location", "corpoBruto"} <= set(resposta)


def test_nenhuma_fixture_carrega_a_chave_de_api_real() -> None:
    for arquivo in (PASTA / "http").glob("*.json"):
        cabecalhos = json.loads(arquivo.read_text(encoding="utf-8"))["requisicao"]["headers"] or {}
        autorizacao = cabecalhos.get("authorization")
        # "chave-de-captura" é a API_KEY fictícia das instâncias de captura
        # (capturar.mjs), enviada sem o prefixo no caso erro-auth-sem-bearer-401.
        assert autorizacao in (None, "Bearer <API_KEY>", "Bearer errado", "chave-de-captura"), arquivo.name


def test_logs_nao_carregam_identificadores_da_maquina_de_captura() -> None:
    # Hostname, IP de rede interna e caminhos locais (usuário, pasta temporária)
    # foram trocados por valores fixos de exemplo antes do primeiro commit. O
    # valor das fixtures está nos nomes de campo e na ordem do envelope.
    for arquivo in (PASTA / "logs").glob("*.ndjson"):
        texto = arquivo.read_text(encoding="utf-8")
        for linha in texto.splitlines():
            if linha.strip():
                assert json.loads(linha)["hostname"] == "maquina-de-captura"
        assert "AppData" not in texto
        assert "Users" + "\\" not in texto.replace("\\\\", "\\")
        for octetos in ("10.", "172.", "192.168."):
            assert f"http://{octetos}" not in texto


def test_logs_brutos_sao_ndjson_no_envelope_do_pino() -> None:
    arquivos = sorted((PASTA / "logs").glob("*.ndjson"))
    assert len(arquivos) == 5
    for arquivo in arquivos:
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), start=1):
            if not linha.strip():
                continue
            registro = json.loads(linha)
            chaves = list(registro)
            assert chaves[:4] == ["level", "time", "pid", "hostname"], f"{arquivo.name}:{numero}"
            assert chaves[-1] == "msg", f"{arquivo.name}:{numero}"
