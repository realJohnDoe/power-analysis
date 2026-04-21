# Multi-stage build for Synology NAS compatibility
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src ./src

# Install dependencies and build
RUN uv sync --frozen && uv pip install -e .

# Production stage - minimal image
FROM python:3.12-slim

WORKDIR /app

# Copy only the installed packages and entry point
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Set environment to use the virtualenv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

# Create output directory for CSV files
RUN mkdir -p /data

# Default command
CMD ["tibber-power", "--help"]