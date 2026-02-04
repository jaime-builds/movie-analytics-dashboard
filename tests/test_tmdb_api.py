"""
Tests for TMDB API client
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.tmdb_api import TMDBClient


class TestTMDBClientInitialization:
    """Tests for TMDB client initialization"""

    def test_client_creates_successfully(self):
        """Test that TMDB client initializes"""
        client = TMDBClient()
        assert client is not None
        assert hasattr(client, "api_key")
        assert hasattr(client, "base_url")

    def test_client_has_correct_base_url(self):
        """Test that client has correct API base URL"""
        client = TMDBClient()
        assert client.base_url == "https://api.themoviedb.org/3"

    def test_client_has_api_key(self):
        """Test that client has API key configured"""
        client = TMDBClient()
        assert client.api_key is not None
        assert len(client.api_key) > 0


class TestGetPopularMovies:
    """Tests for fetching popular movies"""

    @patch("src.tmdb_api.requests.get")
    def test_get_popular_movies_success(self, mock_get):
        """Test successful API call for popular movies"""
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "page": 1,
            "results": [
                {"id": 550, "title": "Fight Club", "vote_average": 8.4, "popularity": 50.5},
                {"id": 680, "title": "Pulp Fiction", "vote_average": 8.5, "popularity": 60.0},
            ],
            "total_pages": 10,
            "total_results": 200,
        }
        mock_get.return_value = mock_response

        client = TMDBClient()
        result = client.get_popular_movies(page=1)

        assert "results" in result
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "Fight Club"
        assert result["page"] == 1

    @patch("src.tmdb_api.requests.get")
    def test_get_popular_movies_with_page_parameter(self, mock_get):
        """Test API call with specific page number"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"page": 2, "results": []}
        mock_get.return_value = mock_response

        client = TMDBClient()
        result = client.get_popular_movies(page=2)

        # Verify the API was called with correct page parameter
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "page=2" in str(call_args) or call_args[1].get("params", {}).get("page") == 2

    @patch("src.tmdb_api.requests.get")
    def test_get_popular_movies_api_error(self, mock_get):
        """Test handling of API errors"""
        mock_get.side_effect = Exception("API Error")

        client = TMDBClient()
        result = client.get_popular_movies(page=1)

        # Should handle error gracefully
        assert result is not None or result == {} or result == []


class TestGetMovieDetails:
    """Tests for fetching movie details"""

    @patch("src.tmdb_api.requests.get")
    def test_get_movie_details_success(self, mock_get):
        """Test successful fetch of movie details"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 550,
            "title": "Fight Club",
            "overview": "An insomniac office worker...",
            "release_date": "1999-10-15",
            "vote_average": 8.4,
            "vote_count": 25000,
            "budget": 63000000,
            "revenue": 100853753,
            "runtime": 139,
        }
        mock_get.return_value = mock_response

        client = TMDBClient()
        result = client.get_movie_details(movie_id=550)

        assert result["id"] == 550
        assert result["title"] == "Fight Club"
        assert result["budget"] == 63000000

    @patch("src.tmdb_api.requests.get")
    def test_get_movie_details_not_found(self, mock_get):
        """Test handling of non-existent movie"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.json.return_value = {
            "success": False,
            "status_message": "The resource you requested could not be found.",
        }
        mock_get.return_value = mock_response

        client = TMDBClient()
        result = client.get_movie_details(movie_id=999999)

        # Should handle 404 gracefully
        assert result is not None


class TestGetMovieCredits:
    """Tests for fetching movie credits (cast and crew)"""

    @patch("src.tmdb_api.requests.get")
    def test_get_movie_credits_success(self, mock_get):
        """Test successful fetch of movie credits"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 550,
            "cast": [{"id": 287, "name": "Brad Pitt", "character": "Tyler Durden", "order": 0}],
            "crew": [
                {"id": 7467, "name": "David Fincher", "job": "Director", "department": "Directing"}
            ],
        }
        mock_get.return_value = mock_response

        client = TMDBClient()
        result = client.get_movie_credits(movie_id=550)

        assert "cast" in result
        assert "crew" in result
        assert len(result["cast"]) == 1
        assert result["cast"][0]["name"] == "Brad Pitt"
        assert result["crew"][0]["job"] == "Director"


class TestGetMovieVideos:
    """Tests for fetching movie videos (trailers)"""

    @patch("src.tmdb_api.requests.get")
    def test_get_movie_videos_success(self, mock_get):
        """Test successful fetch of movie videos"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 550,
            "results": [
                {
                    "key": "SUXWAEX2jlg",
                    "name": "Fight Club - Official Trailer",
                    "site": "YouTube",
                    "type": "Trailer",
                    "official": True,
                }
            ],
        }
        mock_get.return_value = mock_response

        client = TMDBClient()
        result = client.get_movie_videos(movie_id=550)

        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["site"] == "YouTube"
        assert result["results"][0]["type"] == "Trailer"

    @patch("src.tmdb_api.requests.get")
    def test_get_movie_videos_no_videos(self, mock_get):
        """Test movie with no videos available"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 123, "results": []}
        mock_get.return_value = mock_response

        client = TMDBClient()
        result = client.get_movie_videos(movie_id=123)

        assert "results" in result
        assert len(result["results"]) == 0


class TestTrailerSelection:
    """Tests for trailer selection logic in app.py"""

    @patch("src.tmdb_api.TMDBClient.get_movie_videos")
    def test_select_official_trailer(self, mock_get_videos):
        """Test that official trailers are prioritized"""
        mock_get_videos.return_value = {
            "results": [
                {"key": "abc", "site": "YouTube", "type": "Teaser", "official": False},
                {"key": "xyz", "site": "YouTube", "type": "Trailer", "official": True},
                {"key": "def", "site": "YouTube", "type": "Trailer", "official": False},
            ]
        }

        from src.app import get_trailer_for_movie

        trailer = get_trailer_for_movie(tmdb_id=550)

        assert trailer is not None
        assert trailer["key"] == "xyz"  # Official trailer should be selected
        assert trailer["official"] is True

    @patch("src.tmdb_api.TMDBClient.get_movie_videos")
    def test_select_any_trailer_if_no_official(self, mock_get_videos):
        """Test fallback to any trailer if no official trailer"""
        mock_get_videos.return_value = {
            "results": [
                {"key": "abc", "site": "YouTube", "type": "Teaser", "official": False},
                {"key": "def", "site": "YouTube", "type": "Trailer", "official": False},
            ]
        }

        from src.app import get_trailer_for_movie

        trailer = get_trailer_for_movie(tmdb_id=550)

        assert trailer is not None
        assert trailer["type"] == "Trailer"  # Should prefer Trailer over Teaser

    @patch("src.tmdb_api.TMDBClient.get_movie_videos")
    def test_no_youtube_videos(self, mock_get_videos):
        """Test handling when no YouTube videos available"""
        mock_get_videos.return_value = {
            "results": [{"key": "abc", "site": "Vimeo", "type": "Trailer", "official": True}]
        }

        from src.app import get_trailer_for_movie

        trailer = get_trailer_for_movie(tmdb_id=550)

        # Should return None if no YouTube videos
        assert trailer is None

    @patch("src.tmdb_api.TMDBClient.get_movie_videos")
    def test_empty_videos(self, mock_get_videos):
        """Test handling when no videos at all"""
        mock_get_videos.return_value = {"results": []}

        from src.app import get_trailer_for_movie

        trailer = get_trailer_for_movie(tmdb_id=550)

        assert trailer is None


class TestRateLimiting:
    """Tests for API rate limiting and retries"""

    @patch("src.tmdb_api.requests.get")
    def test_rate_limit_handling(self, mock_get):
        """Test handling of rate limit errors"""
        mock_response = Mock()
        mock_response.status_code = 429  # Too Many Requests
        mock_response.json.return_value = {
            "status_message": "Your request count is over the allowed limit."
        }
        mock_get.return_value = mock_response

        client = TMDBClient()
        result = client.get_popular_movies(page=1)

        # Should handle rate limiting gracefully
        assert result is not None

    @patch("src.tmdb_api.requests.get")
    def test_network_timeout(self, mock_get):
        """Test handling of network timeouts"""
        mock_get.side_effect = TimeoutError("Connection timed out")

        client = TMDBClient()
        result = client.get_popular_movies(page=1)

        # Should handle timeout gracefully
        assert result is not None or result == {} or result == []


class TestAPIConfiguration:
    """Tests for API configuration"""

    def test_api_key_from_environment(self):
        """Test that API key is loaded from environment"""
        client = TMDBClient()
        # API key should be loaded from config
        assert client.api_key is not None

    def test_image_base_url_configuration(self):
        """Test image URL configuration"""
        from config.config import Config

        assert hasattr(Config, "TMDB_IMAGE_BASE_URL")
        assert "image.tmdb.org" in Config.TMDB_IMAGE_BASE_URL
