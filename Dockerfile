FROM python:3.12-slim AS builder
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.1.4 \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=false \
    POETRY_CACHE_DIR=/tmp/.cache \
    POETRY_NO_INTERACTION=1

# Install build deps and Poetry
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install "poetry==$POETRY_VERSION"

# Copy poetry files (for layer caching optimization)
COPY pyproject.toml poetry.lock* ./

# Create a slim runtime venv and install only main deps
RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && poetry install --only=main --no-root --no-ansi \
    && poetry cache clear pypi --all

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
# Copy the built venv
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Copy application code
COPY app/ ./app/
# Copy Alembic migration files
COPY alembic/ ./alembic/
COPY alembic.ini ./
# Copy entrypoint script
COPY entrypoint.sh ./

# Create non-root user and data dir
RUN useradd -r -u 10001 -g users appuser \
    && mkdir -p /app/data \
    && chown -R appuser:users /app \
    && chmod +x /app/entrypoint.sh
USER appuser

# Expose port 8000
EXPOSE 8000

# Use entrypoint script to run migrations before starting app
CMD ["./entrypoint.sh"]