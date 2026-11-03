import logging
import time
from typing import Dict, List, Optional

import requests

from config.config import Config

logger = logging.getLogger(__name__)

# Longest wait honored from a 429 Retry-After header before giving up
_MAX_RETRY_WAIT_SECONDS = 10


class TMDBError(Exception):
    """A TMDB request failed. The message never contains the API key."""


class TMDBClient:
    """Client for interacting with TMDB API.

    By default a failed request is logged and returns an empty dict, which
    suits page rendering: a missing trailer shouldn't break a movie page.
    The sync script passes ``raise_errors=True`` so it can count failures
    instead of writing empty rows, and ``max_retries`` to wait out HTTP 429.
    """

    def __init__(self, raise_errors: bool = False, max_retries: int = 0):
        self.api_key = Config.TMDB_API_KEY
        self.base_url = Config.TMDB_BASE_URL
        self.timeout = (3.05, 10)
        self.raise_errors = raise_errors
        self.max_retries = max_retries

    def _redact(self, text: str) -> str:
        """Strip the API key from text that may include a request URL."""
        if self.api_key:
            text = text.replace(self.api_key, "***")
        return text

    def _fail(self, endpoint: str, reason: str) -> Dict:
        reason = self._redact(reason)
        logger.warning("TMDB request failed for %s: %s", endpoint, reason)
        if self.raise_errors:
            raise TMDBError(f"{endpoint}: {reason}")
        return {}

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a request to TMDB API"""
        if not self.api_key:
            return self._fail(endpoint, "TMDB_API_KEY is not set")

        params = dict(params or {})
        # TMDB's v3 key travels as a query parameter, so every error message
        # below goes through _redact before it is logged or raised
        params["api_key"] = self.api_key
        url = f"{self.base_url}/{endpoint}"

        attempt = 0
        while True:
            try:
                response = requests.get(url, params=params, timeout=self.timeout)
                if response.status_code == 429 and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(self._retry_wait(response, attempt))
                    continue
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else "error"
                return self._fail(endpoint, f"HTTP {status}")
            except requests.RequestException as e:
                return self._fail(endpoint, f"{type(e).__name__}: {e}")
            except ValueError:
                return self._fail(endpoint, "invalid JSON in response")
            except Exception as e:
                return self._fail(endpoint, f"unexpected {type(e).__name__}: {e}")

    @staticmethod
    def _retry_wait(response, attempt: int) -> float:
        """Seconds to wait before retrying a 429: Retry-After if sane, else backoff."""
        try:
            wait = float(response.headers.get("Retry-After", ""))
        except (TypeError, ValueError):
            wait = 2.0**attempt
        return max(0.5, min(wait, _MAX_RETRY_WAIT_SECONDS))

    def get_popular_movies(self, page: int = 1) -> Dict:
        """Get popular movies"""
        return self._make_request("movie/popular", {"page": page})

    def get_top_rated_movies(self, page: int = 1) -> Dict:
        """Get top rated movies"""
        return self._make_request("movie/top_rated", {"page": page})

    def get_now_playing(self, page: int = 1) -> Dict:
        """Get movies now playing in theaters"""
        return self._make_request("movie/now_playing", {"page": page})

    def get_upcoming_movies(self, page: int = 1) -> Dict:
        """Get upcoming movies"""
        return self._make_request("movie/upcoming", {"page": page})

    def get_movie_details(self, movie_id: int, append: Optional[List[str]] = None) -> Dict:
        """Get detailed information about a movie.

        ``append`` adds TMDB sub-resources (for example ``["credits", "keywords"]``)
        to the same request via ``append_to_response``.
        """
        params = {"append_to_response": ",".join(append)} if append else None
        return self._make_request(f"movie/{movie_id}", params)

    def get_movie_credits(self, movie_id: int) -> Dict:
        """Get cast and crew for a movie"""
        return self._make_request(f"movie/{movie_id}/credits")

    def get_movie_keywords(self, movie_id: int) -> List[Dict]:
        """Get the keyword list for a movie"""
        return self._make_request(f"movie/{movie_id}/keywords").get("keywords", [])

    def get_movie_videos(self, movie_id: int) -> Dict:
        """Get videos (trailers, teasers, etc.) for a movie"""
        return self._make_request(f"movie/{movie_id}/videos")

    def get_watch_providers(self, movie_id: int, region: str = "US") -> Dict:
        """Get streaming/rental/purchase availability for a movie.

        Returns a dict with keys like 'flatrate', 'rent', 'buy', each a list
        of provider dicts with 'provider_name' and 'logo_path'.
        Returns an empty dict if no data is available for the region.
        """
        data = self._make_request(f"movie/{movie_id}/watch/providers")
        results = data.get("results", {})
        return results.get(region, {})

    def search_movies(self, query: str, page: int = 1) -> Dict:
        """Search for movies"""
        return self._make_request("search/movie", {"query": query, "page": page})

    def get_genres(self) -> List[Dict]:
        """Get all movie genres"""
        result = self._make_request("genre/movie/list")
        return result.get("genres", [])

    def get_person_details(self, person_id: int) -> Dict:
        """Get details about a person (actor, director, etc.)"""
        return self._make_request(f"person/{person_id}")

    def discover_movies(self, **kwargs) -> Dict:
        """
        Discover movies with filters
        Examples:
        - with_genres: genre IDs (comma-separated)
        - year: release year
        - sort_by: popularity.desc, vote_average.desc, etc.
        """
        return self._make_request("discover/movie", kwargs)


# Test the API connection
if __name__ == "__main__":
    client = TMDBClient()

    # Test getting popular movies
    print("Testing TMDB API connection...")
    popular = client.get_popular_movies()

    if popular and "results" in popular:
        print(f"✓ Successfully retrieved {len(popular['results'])} popular movies")
        print(f"First movie: {popular['results'][0]['title']}")
    else:
        print("✗ Failed to retrieve movies. Check your API key.")
