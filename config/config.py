import os

from dotenv import load_dotenv

# Resolve the project root directory regardless of where the server is launched from
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = f"sqlite:///{os.path.join(_PROJECT_ROOT, 'movies.db')}"

# Load environment variables — explicitly point to config/.env so it works
# regardless of which directory the server is launched from.
# override=False means existing environment variables take precedence over .env
# This allows DATABASE_URL and other vars to be set externally (e.g. Railway, CI)
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH, override=False)

_DEV_SECRET_KEY = "dev-secret-key-change-in-production"
_PRODUCTION_ENV_VALUES = {"production", "prod"}
_LOCAL_ENV_VALUES = {"development", "dev", "local"}
_RAILWAY_ENV_MARKERS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
)


def _current_environment():
    """Return the explicit runtime environment, defaulting to local development."""
    return (
        os.getenv("FLASK_ENV") or os.getenv("APP_ENV") or os.getenv("ENV") or "development"
    ).lower()


def _is_production_environment():
    """Detect production only from explicit production/Railway environment signals."""
    environment = _current_environment()
    return environment in _PRODUCTION_ENV_VALUES or any(
        os.getenv(name) for name in _RAILWAY_ENV_MARKERS
    )


def _debug_default():
    """Enable debug only for local development unless DEBUG explicitly overrides it."""
    debug_value = os.getenv("DEBUG")
    if debug_value:
        return debug_value.lower() in {"1", "true", "yes", "on"}
    return _current_environment() in _LOCAL_ENV_VALUES


def _secret_key():
    secret_key = os.getenv("SECRET_KEY") or _DEV_SECRET_KEY
    if _is_production_environment() and secret_key == _DEV_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY must be set to a non-default value when running in production."
        )
    return secret_key


class Config:
    # TMDB API
    TMDB_API_KEY = os.getenv("TMDB_API_KEY")
    TMDB_BASE_URL = "https://api.themoviedb.org/3"
    TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

    # Database
    # Railway injects DATABASE_URL as postgresql:// but SQLAlchemy 2.0 requires
    # postgresql+psycopg2://. Fix the scheme if needed.
    _raw_db_url = os.getenv("DATABASE_URL", _DEFAULT_DB)
    DATABASE_URL = (
        _raw_db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        if _raw_db_url.startswith("postgresql://")
        else _raw_db_url
    )

    # Redis -- optional, used for caching and rate limiting in production
    # Set REDIS_URL in the environment to enable. Falls back to in-memory if not set.
    REDIS_URL = os.getenv("REDIS_URL", None)

    # Flask
    ENVIRONMENT = _current_environment()
    IS_PRODUCTION = _is_production_environment()
    SECRET_KEY = _secret_key()
    DEBUG = _debug_default()
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Pagination
    MOVIES_PER_PAGE = 20

    @staticmethod
    def get_poster_url(poster_path, size="w500"):
        """Generate full URL for movie poster"""
        if not poster_path:
            return None
        return f"{Config.TMDB_IMAGE_BASE_URL}/{size}{poster_path}"

    @staticmethod
    def get_poster_srcset(poster_path):
        """Generate a srcset string for responsive poster images.

        Returns a tuple of (srcset, sizes) strings for use in <img> or <picture> tags.
        TMDB provides w185, w342, and w500 variants.
        """
        if not poster_path:
            return None, None
        base = Config.TMDB_IMAGE_BASE_URL
        srcset = (
            f"{base}/w185{poster_path} 185w, "
            f"{base}/w342{poster_path} 342w, "
            f"{base}/w500{poster_path} 500w"
        )
        # Render at ~100% of its container up to 342px, then cap at 500px
        sizes = "(max-width: 576px) 185px, (max-width: 992px) 342px, 500px"
        return srcset, sizes

    @staticmethod
    def get_backdrop_url(backdrop_path, size="w1280"):
        """Generate full URL for movie backdrop"""
        if not backdrop_path:
            return None
        return f"{Config.TMDB_IMAGE_BASE_URL}/{size}{backdrop_path}"
