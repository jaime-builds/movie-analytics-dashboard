import os

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    # TMDB API
    TMDB_API_KEY = os.getenv("TMDB_API_KEY")
    TMDB_BASE_URL = "https://api.themoviedb.org/3"
    TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///movies.db")

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG = os.getenv("DEBUG", "True") == "True"

    # Pagination
    MOVIES_PER_PAGE = 20

    @staticmethod
    def get_poster_url(poster_path, size="w500"):
        """Generate full URL for movie poster"""
        if not poster_path:
            return None
        return f"{Config.TMDB_IMAGE_BASE_URL}/{size}{poster_path}"

    @staticmethod
    def get_backdrop_url(backdrop_path, size="w1280"):
        """Generate full URL for movie backdrop"""
        if not backdrop_path:
            return None
        return f"{Config.TMDB_IMAGE_BASE_URL}/{size}{backdrop_path}"
