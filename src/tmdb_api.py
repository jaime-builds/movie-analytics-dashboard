import requests
from config.config import Config
from typing import Dict, List, Optional

class TMDBClient:
    """Client for interacting with TMDB API"""
    
    def __init__(self):
        self.api_key = Config.TMDB_API_KEY
        self.base_url = Config.TMDB_BASE_URL
        
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a request to TMDB API"""
        if params is None:
            params = {}
        
        params['api_key'] = self.api_key
        url = f"{self.base_url}/{endpoint}"
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error making request to {url}: {e}")
            return {}
    
    def get_popular_movies(self, page: int = 1) -> Dict:
        """Get popular movies"""
        return self._make_request('movie/popular', {'page': page})
    
    def get_top_rated_movies(self, page: int = 1) -> Dict:
        """Get top rated movies"""
        return self._make_request('movie/top_rated', {'page': page})
    
    def get_now_playing(self, page: int = 1) -> Dict:
        """Get movies now playing in theaters"""
        return self._make_request('movie/now_playing', {'page': page})
    
    def get_upcoming_movies(self, page: int = 1) -> Dict:
        """Get upcoming movies"""
        return self._make_request('movie/upcoming', {'page': page})
    
    def get_movie_details(self, movie_id: int) -> Dict:
        """Get detailed information about a movie"""
        return self._make_request(f'movie/{movie_id}')
    
    def get_movie_credits(self, movie_id: int) -> Dict:
        """Get cast and crew for a movie"""
        return self._make_request(f'movie/{movie_id}/credits')
    
    def search_movies(self, query: str, page: int = 1) -> Dict:
        """Search for movies"""
        return self._make_request('search/movie', {'query': query, 'page': page})
    
    def get_genres(self) -> List[Dict]:
        """Get all movie genres"""
        result = self._make_request('genre/movie/list')
        return result.get('genres', [])
    
    def get_person_details(self, person_id: int) -> Dict:
        """Get details about a person (actor, director, etc.)"""
        return self._make_request(f'person/{person_id}')
    
    def discover_movies(self, **kwargs) -> Dict:
        """
        Discover movies with filters
        Examples:
        - with_genres: genre IDs (comma-separated)
        - year: release year
        - sort_by: popularity.desc, vote_average.desc, etc.
        """
        return self._make_request('discover/movie', kwargs)

# Test the API connection
if __name__ == '__main__':
    client = TMDBClient()
    
    # Test getting popular movies
    print("Testing TMDB API connection...")
    popular = client.get_popular_movies()
    
    if popular and 'results' in popular:
        print(f"✓ Successfully retrieved {len(popular['results'])} popular movies")
        print(f"First movie: {popular['results'][0]['title']}")
    else:
        print("✗ Failed to retrieve movies. Check your API key.")