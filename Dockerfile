# syntax=docker/dockerfile:1
# ──────────────────────────────────────────────────────────────
# Stage 1: build
#   - Installs all Python dependencies into a virtual environment
#   - Uses BuildKit cache mount so pip packages are cached across
#     builds by Depot's persistent NVMe layer — no re-downloading
#     unless requirements.txt actually changes
# ──────────────────────────────────────────────────────────────
FROM python:3.13-slim AS build

RUN pip install --upgrade pip setuptools wheel

WORKDIR /app

# Create a virtual environment inside the image
RUN python -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy requirements first — this layer is cached separately from
# your app code, so a code-only change won't re-install packages
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

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

USER appuser

EXPOSE 5000

# Gunicorn is a production-grade WSGI server for Flask.
# Adjust workers based on your dyno/instance size.
# Formula: (2 x num_cores) + 1  — 3 works for most small servers.
# Entry point is src/app.py with the Flask app initialized as `app`
# Config is loaded from config/.env via python-dotenv in the app
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "--timeout", "120", "src.app:app"]
