# SentinelEdge Server - Production Dockerfile
# Multi-stage build for optimized image size

# Stage 1: Build
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY server_requirements.txt requirements.txt
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# Stage 2: Production
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 sentinel

# Copy wheels from builder
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code
COPY --chown=sentinel:sentinel . .

# Create necessary directories
RUN mkdir -p /app/logs /app/instance && \
    chown -R sentinel:sentinel /app

# Switch to non-root user
USER sentinel

# Expose port
EXPOSE 5050

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5050/ || exit 1

# Run with gunicorn in production
CMD ["python", "-m", "gunicorn", "--bind", "0.0.0.0:5050", "--workers", "4", "--threads", "2", "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
