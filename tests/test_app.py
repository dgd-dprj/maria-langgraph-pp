"""Ordem de inicialização (#208, ponto de atenção 1; issue #114; plano de corte, item 2).

O teste prova a SEQUÊNCIA, não só que a inicialização funciona: com o
uvicorn de verdade, enquanto o inicializador do checkpointer está bloqueado,
uma conexão TCP na porta do servidor é recusada. Depois que o checkpointer e
o schema de negócio terminam, o `/health` responde.
"""

import asyncio
import socket
from collections.abc import AsyncIterator

import httpx
import pytest
import uvicorn

from maria.app import INICIALIZADORES_PADRAO, criar_app
from maria.shared import checkpointer
from maria.shared.checkpointer import fechar_checkpointer, inicializar_checkpointer


@pytest.fixture(autouse=True)
async def _checkpointer_limpo() -> AsyncIterator[None]:
    await fechar_checkpointer()
    yield
    await fechar_checkpointer()


def _socket_reservado() -> socket.socket:
    # Ligado à porta, mas ainda sem listen(): quem chama listen() é o uvicorn, e
    # ele só faz isso depois do lifespan. Sem corrida para descobrir porta livre.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    return sock


async def _conexao_recusada(porta: int) -> bool:
    try:
        _leitor, escritor = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", porta), timeout=5)
    except (ConnectionRefusedError, OSError, TimeoutError):
        return True
    escritor.close()
    return False


async def test_health_so_responde_depois_do_checkpointer_e_do_schema_de_negocio() -> None:
    ordem: list[str] = []
    liberar_checkpointer = asyncio.Event()
    checkpointer_comecou = asyncio.Event()

    async def checkpointer_lento() -> None:
        ordem.append("checkpointer:inicio")
        checkpointer_comecou.set()
        await liberar_checkpointer.wait()
        ordem.append("checkpointer:fim")

    async def schema_de_negocio() -> None:
        ordem.append("schema_de_negocio")

    app = criar_app(inicializadores=[checkpointer_lento, schema_de_negocio])
    sock = _socket_reservado()
    porta = sock.getsockname()[1]
    servidor = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, lifespan="on"))
    tarefa = asyncio.create_task(servidor.serve(sockets=[sock]))
    try:
        await asyncio.wait_for(checkpointer_comecou.wait(), timeout=10)

        # Inicialização em andamento: nada aceita conexão, nem o /health.
        assert await _conexao_recusada(porta)
        assert ordem == ["checkpointer:inicio"]

        liberar_checkpointer.set()

        async with httpx.AsyncClient() as cliente:
            for _ in range(200):
                try:
                    resposta = await cliente.get(f"http://127.0.0.1:{porta}/health")
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.05)
            else:
                pytest.fail("o servidor não passou a aceitar conexões depois da inicialização")

        assert resposta.status_code == 200
        assert resposta.json() == {"status": "ok"}
        # Quando o /health respondeu, os dois inicializadores já tinham terminado, nessa ordem.
        assert ordem == ["checkpointer:inicio", "checkpointer:fim", "schema_de_negocio"]
    finally:
        servidor.should_exit = True
        await asyncio.wait_for(tarefa, timeout=10)


async def test_falha_na_inicializacao_encerra_o_processo_sem_aceitar_conexoes() -> None:
    # O uvicorn encerra o processo (código 3) quando o lifespan falha; no ECS, a
    # task morre e é recriada, sem nunca ter passado no health check.
    async def checkpointer_quebrado() -> None:
        raise RuntimeError("banco fora do ar")

    app = criar_app(inicializadores=[checkpointer_quebrado])
    sock = _socket_reservado()
    porta = sock.getsockname()[1]
    servidor = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, lifespan="on"))
    with pytest.raises(SystemExit) as saida:
        await asyncio.wait_for(servidor.serve(sockets=[sock]), timeout=10)
    assert saida.value.code == 3
    assert not servidor.started
    assert await _conexao_recusada(porta)


def test_inicializadores_padrao_comecam_pelo_checkpointer() -> None:
    assert INICIALIZADORES_PADRAO[0] is inicializar_checkpointer


def test_inicializadores_padrao_seguem_a_ordem_de_develop() -> None:
    # Spec do módulo persistencia, teste 16: checkpointer e, depois, as três stores
    # na ordem de app.ts:40-43. O fluxo_embeddings não entra no startup.
    from maria.app import _preparar_esquema_perguntas
    from maria.shared.atendimentos_db import obter_atendimentos_store
    from maria.shared.fluxos_planejados_db import listar_fluxos_planejados

    assert INICIALIZADORES_PADRAO == (
        inicializar_checkpointer,
        obter_atendimentos_store,
        _preparar_esquema_perguntas,
        listar_fluxos_planejados,
    )


async def test_nenhuma_criacao_de_checkpointer_na_primeira_requisicao(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: list[str] = []
    original = checkpointer._criar_checkpointer

    async def contando():
        chamadas.append("criar")
        return await original()

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(checkpointer, "_criar_checkpointer", contando)
    app = criar_app()
    async with app.router.lifespan_context(app):
        assert chamadas == ["criar"]
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
            assert (await cliente.get("/health")).status_code == 200
            assert (await cliente.get("/health")).status_code == 200
        assert chamadas == ["criar"]
