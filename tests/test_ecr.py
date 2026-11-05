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
