"""Leitor do literal `DADOS_SEED` de develop, independente do Node (spec 08, seção 2.3).

Cobre só o que o literal usa: objetos com chaves identificadoras, listas, strings entre aspas
duplas e inteiros, com vírgula final opcional. O único escape aceito é o da aspa dupla, que o
literal usa uma vez: a palavra-chave `"sofri preconceito`, com a aspa solta de develop (spec 08,
achado B4). Qualquer outra construção (outro escape, aspas simples, template, comentário,
número com ponto, identificador como valor)
levanta `LiteralInvalido` em vez de ser ignorada: uma construção nova no seed precisa de
revisão do leitor, e não de um palpite.
"""

import re
from typing import Any

_ESPACO = re.compile(r"[ \t\r\n]*")
_CHAVE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_STRING = re.compile(r'"((?:[^"\\\n]|\\")*)"')
_INTEIRO = re.compile(r"-?[0-9]+(?![0-9.eE])")


class LiteralInvalido(ValueError):
    pass


class _Leitor:
    def __init__(self, texto: str, pos: int) -> None:
        self.texto = texto
        self.pos = pos

    def _pular_espaco(self) -> None:
        m = _ESPACO.match(self.texto, self.pos)
        assert m is not None
        self.pos = m.end()

    def _erro(self, esperado: str) -> LiteralInvalido:
        trecho = self.texto[self.pos : self.pos + 30]
        return LiteralInvalido(f"esperava {esperado} na posição {self.pos}: {trecho!r}")

    def _consumir(self, simbolo: str) -> bool:
        self._pular_espaco()
        if self.texto.startswith(simbolo, self.pos):
            self.pos += len(simbolo)
            return True
        return False

    def valor(self) -> Any:
        self._pular_espaco()
        c = self.texto[self.pos : self.pos + 1]
        if c == "[":
            return self._lista()
        if c == "{":
            return self._objeto()
        m = _STRING.match(self.texto, self.pos)
        if m:
            self.pos = m.end()
            return m.group(1).replace('\\"', '"')
        m = _INTEIRO.match(self.texto, self.pos)
        if m:
            self.pos = m.end()
            return int(m.group(0))
        raise self._erro("string, inteiro, lista ou objeto")

    def _lista(self) -> list[Any]:
        self.pos += 1
        itens: list[Any] = []
        while not self._consumir("]"):
            itens.append(self.valor())
            if not self._consumir(","):
                if not self._consumir("]"):
                    raise self._erro("',' ou ']'")
                break
        return itens

    def _objeto(self) -> dict[str, Any]:
        self.pos += 1
        obj: dict[str, Any] = {}
        while not self._consumir("}"):
            self._pular_espaco()
            m = _CHAVE.match(self.texto, self.pos)
            if not m:
                raise self._erro("chave")
            chave = m.group(0)
            if chave in obj:
                raise LiteralInvalido(f"chave repetida {chave!r} na posição {self.pos}")
            self.pos = m.end()
            if not self._consumir(":"):
                raise self._erro("':'")
            obj[chave] = self.valor()
            if not self._consumir(","):
                if not self._consumir("}"):
                    raise self._erro("',' ou '}'")
                break
        return obj


def ler_dados_seed(fonte: str) -> list[dict[str, Any]]:
    """Devolve os registros de `const DADOS_SEED: FluxoPlanejado[] = [...];`."""
    m = re.search(r"^const DADOS_SEED: FluxoPlanejado\[\] = (?=\[)", fonte, flags=re.M)
    if not m:
        raise LiteralInvalido("declaração de DADOS_SEED não encontrada")
    leitor = _Leitor(fonte, m.end())
    dados = leitor.valor()
    if not leitor._consumir(";"):
        raise leitor._erro("';' depois do literal")
    if not isinstance(dados, list) or not all(isinstance(d, dict) for d in dados):
        raise LiteralInvalido("DADOS_SEED não é uma lista de objetos")
    return dados
