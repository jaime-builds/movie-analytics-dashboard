"""
Structured logging for Movie Analytics Dashboard.

Writes JSON-formatted log lines to logs/app.log with daily rotation (30-day retention).
Import `get_logger` anywhere in the app to get a named logger.

Log levels:
    INFO    - Normal activity (requests, logins, actions)
    WARNING - Suspicious but valid behavior (failed logins, 404s, rate limit hits)
    ERROR   - Unexpected failures (unhandled exceptions, DB errors)
"""

import json
import logging
import os
from logging.handlers import TimedRotatingFileHandler

# Resolve logs/ directory relative to project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")

os.makedirs(_LOG_DIR, exist_ok=True)


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON for easy parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include any extra fields passed via the `extra` kwarg
        standard_keys = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in standard_keys:
                log_obj[key] = value

        # Append exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def _build_logger(name: str = "app") -> logging.Logger:
    """Build and configure the application logger. Called once at import time."""
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if module is reloaded
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    # --- File handler: daily rotation, 30-day retention ---
    file_handler = TimedRotatingFileHandler(
        _LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(JSONFormatter())
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    # --- Console handler: human-readable for development ---
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", "%H:%M:%S")
    )
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    # Don't propagate to the root logger (avoids duplicate output)
    logger.propagate = False

    return logger


def get_logger(name: str = "app") -> logging.Logger:
    """
    Return a named child logger that writes to the same handlers.

    Usage:
        from src.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Something happened", extra={"user_id": 1})
    """
    return logging.getLogger(f"app.{name}") if name != "app" else logging.getLogger("app")


# Build the root app logger when this module is first imported
_build_logger("app")
