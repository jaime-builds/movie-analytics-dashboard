"""
Smoke test for a running Movie Analytics Dashboard.

This is NOT part of the pytest suite. Run it against a live server after a
deployment or environment change. It exits 0 when every check passes and 1
otherwise, so it can gate a deploy step.

Usage:
    python scripts/smoke_test.py                      # http://127.0.0.1:5000
    python scripts/smoke_test.py http://192.168.0.12:8101
    SMOKE_BASE_URL=https://movie-dashboard.jaime.build python scripts/smoke_test.py
"""

import os
import sys

import requests

TIMEOUT = (3.05, 15)


def _checks():
    """(label, path, check) triples; check takes the parsed JSON and returns a problem or None."""
    return [
        ("health", "/api/v1/health", lambda d: None if d.get("status") == "healthy" else d),
        ("genres", "/api/v1/genres", lambda d: None if d.get("genres") else "no genres"),
        ("movies", "/api/v1/movies?per_page=5", lambda d: None if d.get("movies") else "no movies"),
        ("search", "/api/v1/movies/search?q=the", lambda d: None if "movies" in d else d),
        (
            "analytics overview",
            "/api/v1/analytics/overview",
            lambda d: None if d.get("total_movies") else "no movies counted",
        ),
        ("analytics genres", "/api/v1/analytics/genres", lambda d: None if "genres" in d else d),
        ("top movies", "/api/v1/analytics/top-movies", lambda d: None if "movies" in d else d),
        ("actors", "/api/v1/actors?per_page=5", lambda d: None if "actors" in d else d),
        ("docs", "/api/v1/docs", lambda d: None if "endpoints" in d else d),
    ]


def run(base_url: str) -> int:
    base_url = base_url.rstrip("/")
    failures = 0
    print(f"Smoke testing {base_url}\n")

    for label, path, check in _checks():
        try:
            response = requests.get(base_url + path, timeout=TIMEOUT)
            problem = None
            if response.status_code != 200:
                problem = f"HTTP {response.status_code}"
            else:
                problem = check(response.json())
        except (requests.RequestException, ValueError) as exc:
            problem = f"{type(exc).__name__}: {exc}"

        if problem:
            failures += 1
            print(f"FAIL  {label:<20} {path}  ->  {problem}")
        else:
            print(f"ok    {label:<20} {path}")

    # One HTML page, to catch template errors the JSON API can't
    try:
        response = requests.get(base_url + "/", timeout=TIMEOUT)
        if response.status_code == 200 and b"<html" in response.content:
            print(f"ok    {'home page':<20} /")
        else:
            failures += 1
            print(f"FAIL  {'home page':<20} /  ->  HTTP {response.status_code}")
    except requests.RequestException as exc:
        failures += 1
        print(f"FAIL  {'home page':<20} /  ->  {type(exc).__name__}: {exc}")

    print(f"\n{'All checks passed' if not failures else f'{failures} check(s) failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:5000")
    sys.exit(run(url))
