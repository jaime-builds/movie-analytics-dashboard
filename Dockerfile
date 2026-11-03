# ──────────────────────────────────────────────────────────────
# Stage 1: build
#   - Installs all Python dependencies into a virtual environment
#   - Requirements layer is cached separately from app code so
#     code-only changes don't re-install packages
# ──────────────────────────────────────────────────────────────
FROM python:3.13-slim AS build

RUN pip install --upgrade pip setuptools wheel

WORKDIR /app

# Create a virtual environment inside the image
RUN python -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy requirements first — this layer is cached separately from
# your app code, so a code-only change won't re-install packages.
# requirements.txt is the pinned runtime set; test and lint tools live in
# requirements-dev.txt and never enter the image.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# ──────────────────────────────────────────────────────────────
# Stage 2: runtime
#   - Starts fresh from slim base (no build tools, smaller image)
#   - Copies only the venv and app from the build stage
#   - Runs as a non-root user for security
# ──────────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production

# Create a non-root user to run the app
RUN groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -m -d /app -s /bin/false appuser

WORKDIR /app

# Copy built venv + app from build stage with correct ownership
COPY --from=build --chown=appuser:appgroup /app .

# Writable folders for logs and a local SQLite file. A volume mounted here
# inherits this ownership, so the non-root user can write to it.
RUN mkdir -p /app/logs /app/data && chown appuser:appgroup /app/logs /app/data

USER appuser

EXPOSE 8080

# Docker marks the container unhealthy if the app stops answering
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health' % os.environ.get('PORT', '8080'), timeout=4)" || exit 1

# PORT is set explicitly via Compose env on Unraid (defaults to 8080 if unset).
# Shell form so variable expansion works; `exec` hands PID 1 to gunicorn so
# `docker stop` reaches it directly and in-flight requests finish cleanly.
# Alembic runs migrations first, then gunicorn starts on the assigned port.
# One process with threads keeps the in-memory rate limits, cache and log
# rotation shared by every request (two processes each kept their own).
CMD /app/.venv/bin/alembic upgrade head && exec /app/.venv/bin/python -m gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers 1 --worker-class gthread --threads 8 --timeout 120 src.app:app
