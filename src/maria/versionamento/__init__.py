"""Versões dos fluxos para auditoria (#542).

- `manifesto`: lê o código dos fluxos (sem importar nada) e devolve um hash e um snapshot por fluxo.
- `alteracoes`: compara dois snapshots e diz o que mudou (item, antes e depois).
- `meta`: o que a esteira sabe da mudança (PR, solicitante, resumo) e a conferência do PR.
- `registro`: grava a versão nova na tabela `fluxos_versoes` (Postgres), no startup da Maria.
"""
