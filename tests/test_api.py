import json

import requests

BASE_URL = "http://127.0.0.1:5000/api/v1"


def test_health():
    print("Testing /api/v1/health...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print()


def test_genres():
    print("Testing /api/v1/genres...")
    response = requests.get(f"{BASE_URL}/genres")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Total genres: {len(data['genres'])}")
    print(f"First 3: {json.dumps(data['genres'][:3], indent=2)}")
    print()


def test_movies():
    print("Testing /api/v1/movies...")
    response = requests.get(f"{BASE_URL}/movies?page=1&per_page=5")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Page: {data['page']}, Total: {data['total']}")
    print(f"First movie: {json.dumps(data['movies'][0], indent=2)}")
    print()


def test_movie_detail():
    print("Testing /api/v1/movies/<id>...")
    response = requests.get(f"{BASE_URL}/movies/1")
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Title: {data['title']}")
        print(f"Cast members: {len(data['cast'])}")
    print()


def test_search():
    print("Testing /api/v1/movies/search...")
    response = requests.get(f"{BASE_URL}/movies/search?q=inception")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Query: {data['query']}, Results: {data['total']}")
    print()


def test_analytics_overview():
    print("Testing /api/v1/analytics/overview...")
    response = requests.get(f"{BASE_URL}/analytics/overview")
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print()


def test_analytics_genres():
    print("Testing /api/v1/analytics/genres...")
    response = requests.get(f"{BASE_URL}/analytics/genres")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Total genres: {len(data['genres'])}")
    print(f"Top 3: {json.dumps(data['genres'][:3], indent=2)}")
    print()


def test_top_movies():
    print("Testing /api/v1/analytics/top-movies...")
    response = requests.get(f"{BASE_URL}/analytics/top-movies?metric=rating&limit=5")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Metric: {data['metric']}")
    print(f"Movies: {json.dumps(data['movies'], indent=2)}")
    print()


def test_actors():
    print("Testing /api/v1/actors...")
    response = requests.get(f"{BASE_URL}/actors?page=1&per_page=5")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Page: {data['page']}, Total: {data['total']}")
    print(f"First actor: {json.dumps(data['actors'][0], indent=2)}")
    print()


def test_docs():
    print("Testing /api/v1/docs...")
    response = requests.get(f"{BASE_URL}/docs")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Version: {data['version']}")
    print(f"Endpoint categories: {list(data['endpoints'].keys())}")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("API Test Suite")
    print("=" * 60)
    print()

    try:
        test_health()
        test_genres()
        test_movies()
        test_movie_detail()
        test_search()
        test_analytics_overview()
        test_analytics_genres()
        test_top_movies()
        test_actors()
        test_docs()

        print("=" * 60)
        print("All tests completed!")
        print("=" * 60)
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to API. Make sure the Flask app is running.")
    except Exception as e:
        print(f"ERROR: {e}")
