"""Ponto de entrada do servidor (equivale ao `server.ts` de develop).

Um único worker: a ponte do WhatsApp guarda estado em memória por número, e
com mais de um processo esse estado divergiria. Host 0.0.0.0 porque o ALB
conecta na interface da task, e não no loopback.
"""

from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

from maria.shared.logger import configurar_logging_stdlib


def main() -> None:
    load_dotenv()
    configurar_logging_stdlib()
    uvicorn.run(
        "maria.app:criar_app",
        factory=True,
        host="0.0.0.0",
        port=3001,
        workers=1,
        log_config=None,
        # O log de requisição no formato do Fastify (incoming request /
        # request completed) é reproduzido no módulo api.
        access_log=False,
    )


if __name__ == "__main__":
    main()
