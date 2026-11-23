"""Política de ciclo de vida do ECR (#384).

A produção puxa a tag `latest`, publicada só pelo deploy da main, e cada push
em develop publica uma imagem nova com a tag `release`. A regra antiga
("10 últimas, de qualquer tag") apagou a `latest` em 2026-10-29. Aqui a
política é avaliada com a mesma regra do ECR: as regras por prioridade, cada
imagem pega pela primeira regra que a seleciona, e `imageCountMoreThan` mantém
as N mais novas por data de push.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

POLITICA = Path(__file__).parent.parent / "infra" / "terraform" / "ecr-lifecycle.json"
POLITICA_SP = Path(__file__).parent.parent / "infra" / "terraform-sp" / "ecr-lifecycle.json"
N_SHA = 30  # quantas imagens sha- ficam em São Paulo (#544)

# A regra que apagou a `latest` (infra/terraform/ecr.tf até a #384).
POLITICA_ANTIGA: dict[str, Any] = {
    "rules": [
        {
            "rulePriority": 1,
            "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 10},
            "action": {"type": "expire"},
        }
    ]
}


@dataclass(eq=False)
class Imagem:
    publicada_em: int
    tags: set[str] = field(default_factory=set)


def _seleciona(selecao: dict[str, Any], imagem: Imagem) -> bool:
    status = selecao["tagStatus"]
    if status == "any":
        return True
    if status == "untagged":
        return not imagem.tags
    prefixos = selecao.get("tagPrefixList", [])
    return any(tag.startswith(p) for tag in imagem.tags for p in prefixos)


def _expirar(politica: dict[str, Any], imagens: list[Imagem]) -> list[Imagem]:
    """Devolve as imagens que sobram depois de uma avaliação da política."""
    ja_pegas: list[Imagem] = []
    expiradas: list[Imagem] = []
    for regra in sorted(politica["rules"], key=lambda r: r["rulePriority"]):
        selecao = regra["selection"]
        assert selecao["countType"] == "imageCountMoreThan", "só esse tipo é usado aqui"
        # Imagem pega por uma regra não é avaliada pelas seguintes.
        pegas = sorted(
            (i for i in imagens if i not in ja_pegas and _seleciona(selecao, i)),
            key=lambda i: i.publicada_em,
            reverse=True,
        )
        ja_pegas += pegas
        expiradas += pegas[selecao["countNumber"] :]
    return [i for i in imagens if i not in expiradas]


def _publicar(imagens: list[Imagem], tag: str, quando: int) -> list[Imagem]:
    # A tag é mutável: sai da imagem anterior, que fica sem tag.
    for imagem in imagens:
        imagem.tags.discard(tag)
    return [*imagens, Imagem(quando, {tag})]


def _repositorio_de_29_10() -> list[Imagem]:
    # O ECR depois de restaurar a `latest` em 2026-10-29: 8 imagens sem tag,
    # a `release` e a `latest`, nessa ordem de push.
    return [Imagem(t) for t in range(8)] + [Imagem(8, {"release"}), Imagem(9, {"latest"})]


def _pushes_em_develop(politica: dict[str, Any], quantos: int) -> list[Imagem]:
    imagens = _repositorio_de_29_10()
    for n in range(quantos):
        imagens = _expirar(politica, _publicar(imagens, "release", 10 + n))
    return imagens


def _tags(imagens: list[Imagem]) -> set[str]:
    return {tag for imagem in imagens for tag in imagem.tags}


def _carregar() -> dict[str, Any]:
    politica = json.loads(POLITICA.read_text(encoding="utf-8"))
    assert isinstance(politica, dict)
    return politica


def test_latest_continua_depois_de_15_pushes_em_develop() -> None:
    assert {"latest", "release"} <= _tags(_pushes_em_develop(_carregar(), 15))


def test_imagens_sem_tag_ainda_expiram() -> None:
    imagens = _pushes_em_develop(_carregar(), 15)
    sem_tag = [i for i in imagens if not i.tags]
    assert len(sem_tag) == 10
    # Ficam as mais novas, para rollback.
    assert min(i.publicada_em for i in sem_tag) == 14


def test_controle_a_regra_antiga_apaga_a_latest() -> None:
    # Prova que o teste pega o defeito: com a regra antiga, a `latest` some no
    # 10º push em develop.
    assert "latest" in _tags(_pushes_em_develop(POLITICA_ANTIGA, 9))
    assert "latest" not in _tags(_pushes_em_develop(POLITICA_ANTIGA, 10))


def test_terraform_usa_o_arquivo_da_politica() -> None:
    ecr = (POLITICA.parent / "ecr.tf").read_text(encoding="utf-8")
    assert 'file("${path.module}/ecr-lifecycle.json")' in ecr


# --- São Paulo (#544): tags sha- expiram, latest e release nunca ---


def _carregar_sp() -> dict[str, Any]:
    politica = json.loads(POLITICA_SP.read_text(encoding="utf-8"))
    assert isinstance(politica, dict)
    return politica


def _deploys_sp(quantos: int, *, latest_em: int | None = None) -> list[Imagem]:
    """Cada deploy publica uma imagem `sha-<n>` e move a `release` para ela.

    `latest_em` marca qual deploy (a produção) também carrega a `latest`.
    """
    politica = _carregar_sp()
    imagens: list[Imagem] = []
    for n in range(quantos):
        for imagem in imagens:
            imagem.tags.discard("release")  # a tag é mutável: sai da anterior
        imagens.append(Imagem(n, {"release", f"sha-{n}"}))
        if latest_em == n:
            imagens[-1].tags.add("latest")
        imagens = _expirar(politica, imagens)
    return imagens


def _shas(imagens: list[Imagem]) -> set[str]:
    return {t for i in imagens for t in i.tags if t.startswith("sha-")}


def test_sp_mais_de_n_imagens_sha_so_as_mais_antigas_expiram() -> None:
    imagens = _deploys_sp(N_SHA + 5)
    # A imagem protegida (release, a mais nova) não entra na contagem: ficam as
    # N mais novas sem proteção (4 a 33) mais ela (34). Antes disso, nada expira.
    assert _shas(imagens) == {f"sha-{n}" for n in range(4, N_SHA + 5)}
    assert len(_shas(_deploys_sp(N_SHA))) == N_SHA


def test_sp_latest_antiga_com_sha_sobrevive() -> None:
    # A produção (latest) foi publicada no deploy 0 e nunca mais; vêm 2N deploys.
    imagens = _deploys_sp(2 * N_SHA, latest_em=0)
    assert "latest" in _tags(imagens)
    assert "sha-0" in _shas(imagens)  # a imagem da latest guarda a tag sha- junto


def test_sp_release_sobrevive_e_sem_tag_continua_limitada() -> None:
    politica = _carregar_sp()
    imagens = [Imagem(t) for t in range(20)] + [Imagem(20, {"release", "sha-a"})]
    restantes = _expirar(politica, imagens)
    assert "release" in _tags(restantes)
    assert len([i for i in restantes if not i.tags]) == 10


def test_sp_controle_sem_a_protecao_a_latest_com_sha_expira() -> None:
    # Prova que o teste pega o defeito: sem a regra de proteção, a imagem
    # `latest` + `sha-0` cai no limite das sha- e some.
    politica = {"rules": [r for r in _carregar_sp()["rules"] if r["rulePriority"] != 1]}
    imagens = [Imagem(0, {"latest", "sha-0"})] + [Imagem(n, {f"sha-{n}"}) for n in range(1, N_SHA + 2)]
    assert "latest" not in _tags(_expirar(politica, imagens))


def test_sp_terraform_usa_o_arquivo_da_politica() -> None:
    ecr = (POLITICA_SP.parent / "ecr.tf").read_text(encoding="utf-8")
    assert 'file("${path.module}/ecr-lifecycle.json")' in ecr
