"""Content classification shared by the sync, the backfill and the app.

A movie is "mature" when TMDB tags it with one of MATURE_KEYWORDS. Mature
movies never appear on the home page or as Movie of the Day, and the
family-friendly toggle hides them everywhere else.

The list is deliberately narrow (Jaime, 2026-11-02): it targets erotic and
softcore films, not mainstream films with a sex scene. Broad tags such as
"nudity", "sex scene" or "erotic thriller" are left out on purpose, because
they also cover films like Titanic or Basic Instinct.
"""

from typing import Iterable

MATURE_KEYWORDS = frozenset(
    {
        "softcore",
        "sexploitation",
        "erotic",
        "erotica",
        "erotic movie",
        "erotic film",
        "erotic comedy",
        "erotic romance",
        "erotic drama",
        "erotic fantasy",
        "erotic vignettes",
        "erotic anthology",
        "pink film",
        "pinku eiga",
    }
)


def is_mature(keyword_names: Iterable[str]) -> bool:
    """True if any TMDB keyword name is on the mature list (case-insensitive)."""
    return any((name or "").strip().lower() in MATURE_KEYWORDS for name in keyword_names)


def keyword_names(details: dict) -> list:
    """Keyword names from a TMDB movie payload fetched with append_to_response=keywords."""
    keywords = (details or {}).get("keywords") or {}
    return [k.get("name", "") for k in keywords.get("keywords", [])]
