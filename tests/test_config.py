import importlib
import os

import pytest

import config.config as config_module

_ENV_KEYS = (
    "APP_ENV",
    "DEBUG",
    "ENV",
    "FLASK_ENV",
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
    "SECRET_KEY",
)


@pytest.fixture(autouse=True)
def restore_config_module():
    original_env = {key: os.environ.get(key) for key in _ENV_KEYS}
    yield
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    importlib.reload(config_module)


def _reload_config(monkeypatch, **env):
    for key in _ENV_KEYS:
        monkeypatch.setenv(key, "")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(config_module).Config


def test_local_defaults_allow_dev_secret_and_debug(monkeypatch):
    config = _reload_config(monkeypatch)

    assert config.SECRET_KEY == "dev-secret-key-change-in-production"
    assert config.DEBUG is True
    assert config.SESSION_COOKIE_SECURE is False
    assert config.SESSION_COOKIE_HTTPONLY is True
    assert config.SESSION_COOKIE_SAMESITE == "Lax"


def test_testing_environment_allows_dev_secret_without_debug(monkeypatch):
    config = _reload_config(monkeypatch, FLASK_ENV="testing")

    assert config.SECRET_KEY == "dev-secret-key-change-in-production"
    assert config.DEBUG is False
    assert config.IS_PRODUCTION is False


def test_production_requires_non_default_secret(monkeypatch):
    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        _reload_config(monkeypatch, FLASK_ENV="production")


def test_production_secret_sets_secure_cookie_defaults(monkeypatch):
    config = _reload_config(monkeypatch, FLASK_ENV="production", SECRET_KEY="real-secret")

    assert config.DEBUG is False
    assert config.IS_PRODUCTION is True
    assert config.SESSION_COOKIE_SECURE is True
    assert config.SESSION_COOKIE_HTTPONLY is True
    assert config.SESSION_COOKIE_SAMESITE == "Lax"
