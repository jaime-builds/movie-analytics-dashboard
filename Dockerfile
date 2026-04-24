# ──────────────────────────────────────────────────────────────
# Stage 1: build
#   - Installs all Python dependencies into a virtual environment
#   - Requirements layer is cached separately from app code so
#     code-only changes don't re-install packages
# ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS build

RUN pip install --upgrade pip setuptools wheel

WORKDIR /app

# Create a virtual environment inside the image
RUN python -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy requirements first — this layer is cached separately from
# your app code, so a code-only change won't re-install packages
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy the rest of the application
COPY . .

# ──────────────────────────────────────────────────────────────
# Stage 2: runtime
#   - Starts fresh from slim base (no build tools, smaller image)
#   - Copies only the venv and app from the build stage
#   - Runs as a non-root user for security
# ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

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

USER appuser

EXPOSE 8080

# Railway injects $PORT dynamically. We default to 8080 for local Docker runs.
# Run Alembic migrations then start gunicorn using the shell form so $PORT expands.
CMD /app/.venv/bin/alembic upgrade head && /app/.venv/bin/python -m gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 src.app:app
