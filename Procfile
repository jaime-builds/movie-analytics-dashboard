web: alembic upgrade head && gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers 2 --timeout 120 src.app:app
