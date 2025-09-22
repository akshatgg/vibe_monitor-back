# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set Poetry environment variables for optimal Docker performance
ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.7.1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VIRTUALENVS_IN_PROJECT=false \
    POETRY_CACHE_DIR=/tmp/.cache

# Install system dependencies and Poetry
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && pip install "poetry==$POETRY_VERSION"

# Copy poetry files (for layer caching optimization)
COPY pyproject.toml poetry.lock* ./

# Install dependencies (this layer will be cached unless dependencies change)
RUN poetry install --only=main --no-root

# Copy application code
COPY app/ ./app/

# Create data directory
RUN mkdir -p data

# Expose port 8000
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]