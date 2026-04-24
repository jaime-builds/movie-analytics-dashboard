web: /app/.venv/bin/alembic upgrade head && /app/.venv/bin/python -m gunicorn --bind "0.0.0.0:$PORT" --workers 2 --timeout 120 src.app:app
