"""Configuração comum da suíte.

O ambiente de teste é definido aqui, no topo, antes de qualquer import do
pacote `maria`. Equivale ao `cross-env NODE_ENV=test API_KEY=teste-fixo-chave`
do `pnpm test` de develop. Isso importa porque alguns módulos leem variáveis
na importação, como em develop (por exemplo, `VERDE_JWT_TOKEN`, que decide o
modo mock do Verde).

`APP_ENV` substitui `NODE_ENV` (#208): `test`, `development` ou `production`.
"""

import asyncio
import os
import sys

os.environ["APP_ENV"] = "test"
os.environ["API_KEY"] = "teste-fixo-chave"

# O psycopg assíncrono não funciona com o ProactorEventLoop, padrão do Windows.
# Só afeta quem roda a suíte no Windows; o CI e a imagem são Linux.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
