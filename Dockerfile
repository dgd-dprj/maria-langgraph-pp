# API da Maria (LangGraph Python): ponte Tykhe↔Verde.
# Python 3.12: mesma versão do pyproject.toml, do .python-version e do CI (#208).
FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# uv fixado por versão (e não `latest`), para o build ser reproduzível.
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv

# Só as dependências de produção, sem o grupo dev (ruff, mypy, pytest). Instaladas
# antes de copiar o código, para o cache de camada sobreviver a mudanças no código.
FROM base AS deps
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project

FROM deps AS build
COPY src ./src
# --no-editable: o pacote vai inteiro para o .venv, e o runner não precisa do código-fonte solto.
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runner
WORKDIR /app
# APP_ENV substitui o NODE_ENV de develop (#208): test, development ou production.
ENV APP_ENV=production \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
COPY --from=build /app/.venv ./.venv
EXPOSE 3001
# Um único processo (sem --workers): a ponte do WhatsApp guarda estado em memória.
CMD ["python", "-m", "maria.main"]
