"""Pools das stores: testes novos 15 e 17 da spec do módulo persistencia."""

import os

import pytest

from maria.shared import atendimentos_db, embeddings_fluxos, fluxos_planejados_db, perguntas_db
from maria.shared.pool import criar_pool

pytestmark = pytest.mark.usefixtures("stores_limpas")


class _PoolQueNaoAbre:
    async def open(self) -> None:
        raise OSError("sem banco neste teste")

    async def close(self) -> None:
        return None


async def test_as_quatro_stores_criam_o_pool_pela_funcao_comum(monkeypatch: pytest.MonkeyPatch) -> None:
    # Spec, teste 17: nenhuma store cria AsyncConnectionPool direto; os parâmetros
    # (provados em test_pool.py) valem para todas.
    chamadas: list[str] = []

    def registrar(modulo: str):
        def fabrica(url: str) -> _PoolQueNaoAbre:
            chamadas.append(f"{modulo}:{url}")
            return _PoolQueNaoAbre()

        return fabrica

    url = "postgresql://usuario@host-falso/banco"
    monkeypatch.setenv("DATABASE_URL", url)
    for modulo in (atendimentos_db, perguntas_db, fluxos_planejados_db, embeddings_fluxos):
        monkeypatch.setattr(modulo, "criar_pool", registrar(modulo.__name__.rsplit(".", 1)[1]))

    with pytest.raises(OSError, match="sem banco"):
        await atendimentos_db.obter_atendimentos_store()
    await perguntas_db.obter_perguntas_store()
    with pytest.raises(OSError, match="sem banco"):
        await fluxos_planejados_db.listar_fluxos_planejados()
    with pytest.raises(OSError, match="sem banco"):
        await embeddings_fluxos.aquecer_catalogo([])

    assert sorted(chamadas) == sorted(
        f"{m}:{url}" for m in ("atendimentos_db", "perguntas_db", "fluxos_planejados_db", "embeddings_fluxos")
    )
    for modulo in (atendimentos_db, perguntas_db, fluxos_planejados_db, embeddings_fluxos):
        assert "AsyncConnectionPool" not in vars(modulo), f"{modulo.__name__} não deveria importar AsyncConnectionPool"


@pytest.mark.postgres
async def test_postgres_pool_sem_conexao_ate_a_primeira_consulta() -> None:
    # Spec, teste 15: min_size=0 reproduz a abertura preguiçosa do pg. Medido pelas
    # estatísticas do pool, e não por pg_stat_activity: o pool do checkpointer
    # mantém conexão no mesmo banco.
    pool = criar_pool(os.environ["DATABASE_URL"])
    await pool.open()
    try:
        assert pool.get_stats()["pool_size"] == 0
        async with pool.connection() as conexao:
            await conexao.execute("SELECT 1")
        assert pool.get_stats()["pool_size"] == 1
    finally:
        await pool.close()
