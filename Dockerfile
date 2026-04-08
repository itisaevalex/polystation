FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir . && pip install --no-cache-dir prometheus_client redis

# Copy application code
COPY polystation/ polystation/
COPY config/ config/

# Create data directory for SQLite
RUN mkdir -p data

EXPOSE 8420

CMD ["uvicorn", "polystation.dashboard.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8420"]
