FROM python:3.14-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependency layer first (cache-friendly): install deps without the project
# itself, so editing app/ doesn't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
RUN uv sync --frozen --no-dev

FROM python:3.14-slim

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app

COPY --from=build --chown=app:app /app /app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

USER app
CMD ["simple-activity-tracker-server", "run"]
