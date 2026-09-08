# Multi-stage Dockerfile for ECU Hockey Calendar Service and Worker
FROM python:3.12-slim AS builder

# Install uv for fast, reliable dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation and copy mode for uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install dependencies using frozen lockfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source and database migration metadata
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini README.md ./

# Install project into isolated virtual environment
RUN uv sync --frozen --no-dev

# Final production runtime stage
FROM python:3.12-slim AS runtime

# Install curl for container health check probes
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create unprivileged application user and group
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

WORKDIR /app

# Copy virtual environment and application code from builder
COPY --from=builder --chown=appuser:appgroup /app /app

# Ensure virtual environment binaries are on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AUTO_MIGRATE=true \
    DATABASE_URL="sqlite:////data/ecu_hockey.db"

# Create persistent storage volume directory
RUN mkdir -p /data && chown -R appuser:appgroup /data

USER appuser

# Expose calendar service port
EXPOSE 8000

# Container liveness health check probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command: launch FastAPI web server
CMD ["ecu-hockey", "serve", "--host", "0.0.0.0", "--port", "8000"]
