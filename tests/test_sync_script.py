"""
Tests for scripts/sync_tmdb_data.py and scripts/backfill_mature_flags.py
(RR-21, RR-22, FS-13, FS-19 to FS-23, FS-60).

TMDB is replaced by a small fake client; the database is the test session.
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from src.models import Cast, Genre, Movie, Person
from src.tmdb_api import TMDBError

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load("sync_tmdb_data")
backfill = _load("backfill_mature_flags")


def _details(tmdb_id, title=None, keywords=(), cast=None, genres=None, **extra):
    data = {
        "id": tmdb_id,
        "title": title or f"Movie {tmdb_id}",
        "original_title": title or f"Movie {tmdb_id}",
        "release_date": "2020-05-01",
        "genres": genres if genres is not None else [{"id": 28, "name": "Action"}],
        "production_companies": [],
        "popularity": 10.0,
        "vote_average": 7.5,
        "vote_count": 500,
        "keywords": {"keywords": [{"id": i, "name": k} for i, k in enumerate(keywords)]},
        "credits": {
            "cast": cast
            if cast is not None
            else [{"id": 9000 + tmdb_id, "name": "Lead Actor", "character": "Hero", "order": 0}],
            "crew": [{"id": 8000 + tmdb_id, "name": "A Director", "job": "Director"}],
        },
    }
    data.update(extra)
    return data


class FakeClient:
    """Serves canned TMDB replies; raises TMDBError for IDs listed in `failing`."""

    def __init__(self, movies=None, pages=None, failing=(), failing_pages=(), keywords=None):
        self.movies = movies or {}
        self.pages = pages or {}
        self.failing = set(failing)
        self.failing_pages = set(failing_pages)
        self.keywords = keywords or {}

    def get_movie_details(self, tmdb_id, append=None):
        if tmdb_id in self.failing:
            raise TMDBError(f"movie/{tmdb_id}: HTTP 500")
        return self.movies.get(tmdb_id, {})

    def get_popular_movies(self, page=1):
        if page in self.failing_pages:
            raise TMDBError(f"movie/popular: HTTP 503 (page {page})")
        return self.pages.get(page, {"results": [], "total_pages": len(self.pages)})

    def get_genres(self):
        return [{"id": 28, "name": "Action"}]

    def get_movie_keywords(self, tmdb_id):
        if tmdb_id in self.failing:
            raise TMDBError(f"movie/{tmdb_id}/keywords: HTTP 500")
        return [{"name": k} for k in self.keywords.get(tmdb_id, [])]

    # Keyword mode: search/keyword and discover/movie, built from self.keywords
    def search_keywords(self, query, page=1):
        names = sorted({k for kws in self.keywords.values() for k in kws})
        matches = [n for n in names if query in n.lower()]
        return {
            "results": [{"id": 1000 + names.index(n), "name": n} for n in matches],
            "total_pages": 1,
        }

    def discover_movies(self, **kwargs):
        if "discover" in self.failing:
            raise TMDBError("discover/movie: HTTP 503")
        names = sorted({k for kws in self.keywords.values() for k in kws})
        wanted = names[kwargs["with_keywords"] - 1000]
        ids = sorted(tid for tid, kws in self.keywords.items() if wanted in kws)
        # Two results per page, to exercise paging
        page = kwargs.get("page", 1)
        return {
            "results": [{"id": tid} for tid in ids[(page - 1) * 2 : page * 2]],
            "total_pages": max(1, (len(ids) + 1) // 2),
        }


@pytest.fixture
def action_genre(db_session):
    genre = Genre(tmdb_id=28, name="Action")
    db_session.add(genre)
    db_session.commit()
    return genre


def _syncer(db_session, client, **kwargs):
    return sync.FastTMDBSyncer(client=client, session=db_session, **kwargs)


# ============================================
# RR-21: no blank movies from failed fetches
# ============================================


class TestFetch:
    def test_tmdb_error_returns_none(self):
        client = FakeClient(failing={1})

        assert sync.fetch_movie_data(1, client) is None

    def test_empty_reply_returns_none(self):
        assert sync.fetch_movie_data(2, FakeClient()) is None

    def test_good_reply_carries_credits(self):
        client = FakeClient(movies={3: _details(3)})

        fetched = sync.fetch_movie_data(3, client)

        assert fetched["details"]["id"] == 3
        assert fetched["credits"]["cast"][0]["name"] == "Lead Actor"


# ============================================
# RR-22: one bad movie doesn't lose the batch
# ============================================


class TestWriteIsolation:
    def test_failed_movie_does_not_roll_back_its_neighbours(self, db_session, action_genre):
        syncer = _syncer(db_session, FakeClient())
        bad_cast = [{"id": 1, "name": None, "character": "Nobody", "order": 0}]

        assert (
            syncer.write_movie(
                {"tmdb_id": 10, "details": _details(10), "credits": _details(10)["credits"]}
            )
            == "added"
        )
        assert (
            syncer.write_movie(
                {"tmdb_id": 11, "details": _details(11), "credits": {"cast": bad_cast, "crew": []}}
            )
            is None
        )
        assert (
            syncer.write_movie(
                {"tmdb_id": 12, "details": _details(12), "credits": _details(12)["credits"]}
            )
            == "added"
        )
        assert syncer.commit_batch()

        saved = {m.tmdb_id for m in db_session.query(Movie).all()}
        assert saved == {10, 12}
        assert syncer.stats["movies_added"] == 2
        assert syncer.stats["write_errors"] == 1

    def test_counts_wait_for_the_commit(self, db_session, action_genre):
        syncer = _syncer(db_session, FakeClient())
        syncer.write_movie(
            {"tmdb_id": 20, "details": _details(20), "credits": _details(20)["credits"]}
        )

        assert syncer.stats["movies_added"] == 0

        with patch.object(
            db_session, "commit", side_effect=OperationalError("x", {}, Exception("disk full"))
        ):
            assert syncer.commit_batch() is False

        assert syncer.stats["movies_added"] == 0
        assert syncer.stats["commit_errors"] == 1
        assert syncer.fatal is True

    def test_long_character_names_are_stored(self, db_session, action_genre):
        syncer = _syncer(db_session, FakeClient())
        voices = ", ".join(f"Voice {i}" for i in range(60))  # well over 255 characters
        cast = [{"id": 1, "name": "Voice Actor", "character": voices, "order": 0}]

        assert (
            syncer.write_movie(
                {"tmdb_id": 30, "details": _details(30), "credits": {"cast": cast, "crew": []}}
            )
            == "added"
        )
        syncer.commit_batch()

        assert db_session.query(Cast).one().character_name == voices

    def test_update_existing_keeps_genres_when_an_id_repeats(self, db_session, action_genre):
        syncer = _syncer(db_session, FakeClient(), update_existing=True)
        fetched = {"tmdb_id": 40, "details": _details(40), "credits": _details(40)["credits"]}

        syncer.write_movie(fetched)
        syncer.write_movie(fetched)
        syncer.commit_batch()

        movie = db_session.query(Movie).filter_by(tmdb_id=40).one()
        assert [g.name for g in movie.genres] == ["Action"]
        assert db_session.query(Person).count() == 2

    def test_missing_title_falls_back_to_original_title(self, db_session, action_genre):
        syncer = _syncer(db_session, FakeClient())
        details = _details(41, title="Original")
        details["title"] = ""

        syncer.write_movie({"tmdb_id": 41, "details": details, "credits": details["credits"]})
        syncer.commit_batch()

        assert db_session.query(Movie).filter_by(tmdb_id=41).one().title == "Original"


# ============================================
# FS-60: mature flag from keywords
# ============================================


class TestMatureFlag:
    @pytest.mark.parametrize(
        "keywords, expected",
        [
            (["photography", "softcore"], True),
            (["cousin", "Erotic Comedy"], True),
            (["ship", "tragic love", "nudity"], False),
            (["erotic thriller"], False),
        ],
    )
    def test_sync_sets_is_mature(self, db_session, action_genre, keywords, expected):
        syncer = _syncer(db_session, FakeClient())
        details = _details(50, keywords=keywords)

        syncer.write_movie({"tmdb_id": 50, "details": details, "credits": details["credits"]})
        syncer.commit_batch()

        assert db_session.query(Movie).filter_by(tmdb_id=50).one().is_mature is expected

    def test_backfill_flags_and_unflags(self, db_session):
        db_session.add_all(
            [
                Movie(tmdb_id=60, title="Softcore Film"),
                Movie(tmdb_id=61, title="Was Wrongly Flagged", is_mature=True),
                Movie(tmdb_id=62, title="Lookup Fails"),
            ]
        )
        db_session.commit()
        client = FakeClient(keywords={60: ["softcore"], 61: ["ship"]}, failing={62})

        stats = backfill.backfill(db_session, client, workers=2)

        flags = {m.tmdb_id: m.is_mature for m in db_session.query(Movie).all()}
        assert flags == {60: True, 61: False, 62: False}
        assert stats == {"checked": 2, "flagged": 1, "changed": 2, "failed": 1}

    def test_backfill_dry_run_writes_nothing(self, db_session):
        db_session.add(Movie(tmdb_id=63, title="Softcore Film"))
        db_session.commit()

        stats = backfill.backfill(db_session, FakeClient(keywords={63: ["softcore"]}), dry_run=True)

        assert stats["changed"] == 1
        assert db_session.query(Movie).filter_by(tmdb_id=63).one().is_mature is False

    def test_keyword_mode_flags_listed_movies_and_unflags_others(self, db_session):
        db_session.add_all(
            [
                Movie(tmdb_id=70, title="Softcore One"),
                Movie(tmdb_id=71, title="Softcore Two"),
                Movie(tmdb_id=72, title="Softcore Three"),
                Movie(tmdb_id=73, title="Erotic Comedy"),
                Movie(tmdb_id=74, title="Was Wrongly Flagged", is_mature=True),
                Movie(tmdb_id=75, title="Nudity Only"),
            ]
        )
        db_session.commit()
        client = FakeClient(
            keywords={
                70: ["softcore"],
                71: ["softcore"],
                72: ["softcore"],
                73: ["Erotic Comedy"],
                75: ["nudity"],
                99: ["softcore"],  # on TMDB but not in this database
            }
        )

        stats = backfill.backfill_by_keyword(db_session, client)

        flags = {m.tmdb_id: m.is_mature for m in db_session.query(Movie).all()}
        assert flags == {70: True, 71: True, 72: True, 73: True, 74: False, 75: False}
        assert stats["flagged"] == 4
        assert stats["changed"] == 5

    def test_keyword_mode_changes_nothing_if_tmdb_fails(self, db_session):
        db_session.add(Movie(tmdb_id=80, title="Already Flagged", is_mature=True))
        db_session.commit()
        client = FakeClient(keywords={81: ["softcore"]}, failing={"discover"})

        stats = backfill.backfill_by_keyword(db_session, client)

        assert stats["failed"] == 1
        assert db_session.query(Movie).filter_by(tmdb_id=80).one().is_mature is True

    def test_keyword_mode_dry_run_writes_nothing(self, db_session):
        db_session.add(Movie(tmdb_id=82, title="Softcore Film"))
        db_session.commit()

        stats = backfill.backfill_by_keyword(
            db_session, FakeClient(keywords={82: ["softcore"]}), dry_run=True
        )

        assert stats["changed"] == 1
        assert db_session.query(Movie).filter_by(tmdb_id=82).one().is_mature is False


# ============================================
# FS-13 / FS-21 / FS-22 / FS-23: collecting IDs
# ============================================


def _page(*entries, total_pages=2):
    return {"results": list(entries), "total_pages": total_pages}


class TestCollectIds:
    def test_dedupes_skips_known_movies_and_refreshes_their_numbers(self, db_session):
        db_session.add(Movie(tmdb_id=70, title="Known", popularity=1.0, vote_count=10))
        db_session.commit()
        client = FakeClient(
            pages={
                1: _page({"id": 70, "popularity": 99.5, "vote_count": 1234}, {"id": 71}),
                2: _page({"id": 71}, {"id": 72}),
            }
        )
        syncer = _syncer(db_session, client)

        ids = syncer.collect_ids()

        assert ids == [71, 72]
        known = db_session.query(Movie).filter_by(tmdb_id=70).one()
        assert float(known.popularity) == pytest.approx(99.5)
        assert known.vote_count == 1234
        assert syncer.stats["stats_refreshed"] == 1
        assert syncer.stats["movies_skipped"] == 1

    def test_stops_after_repeated_page_failures(self, db_session):
        client = FakeClient(
            pages={1: _page({"id": 80}, total_pages=500)}, failing_pages={2, 3, 4, 5}
        )
        syncer = _syncer(db_session, client, limit=100)

        ids = syncer.collect_ids()

        assert ids == [80]
        assert syncer.stats["page_errors"] == 3

    def test_respects_the_limit(self, db_session):
        client = FakeClient(pages={1: _page({"id": 90}, {"id": 91}, {"id": 92}, total_pages=1)})

        assert _syncer(db_session, client, limit=2).collect_ids() == [90, 91]


class TestFullRun:
    def test_end_to_end_counts_fetch_failures(self, db_session, action_genre):
        client = FakeClient(
            pages={1: _page({"id": 100}, {"id": 101}, {"id": 102}, total_pages=1)},
            movies={100: _details(100), 102: _details(102)},
            failing={101},
        )
        syncer = _syncer(db_session, client, workers=2)

        syncer.sync_popular_movies()

        assert {m.tmdb_id for m in db_session.query(Movie).all()} == {100, 102}
        assert syncer.stats["fetch_errors"] == 1
        assert syncer.stats["movies_added"] == 2

    def test_failed_id_collection_is_fatal(self, db_session):
        client = FakeClient(failing_pages={1, 2, 3})
        syncer = _syncer(db_session, client)

        syncer.sync_popular_movies()

        assert syncer.exit_code() == sync.EXIT_FAILED


class TestExitCodes:
    def test_clean_run_exits_zero(self, db_session):
        syncer = _syncer(db_session, FakeClient())
        syncer.stats["movies_added"] = 100

        assert syncer.exit_code() == sync.EXIT_OK

    def test_a_few_errors_are_tolerated_unless_strict(self, db_session):
        syncer = _syncer(db_session, FakeClient())
        syncer.stats.update(movies_added=100, fetch_errors=2)

        assert syncer.exit_code() == sync.EXIT_OK
        assert syncer.exit_code(strict=True) == sync.EXIT_FAILED

    def test_high_error_rate_fails(self, db_session):
        syncer = _syncer(db_session, FakeClient())
        syncer.stats.update(movies_added=10, write_errors=5)

        assert syncer.exit_code() == sync.EXIT_FAILED

    def test_interrupt_discards_the_open_batch(self):
        class InterruptedSyncer:
            def __init__(self, **kwargs):
                self.session = type("S", (), {"rollback": lambda self: calls.append("rollback")})()

            def acquire_lock(self):
                pass

            def sync_genres(self):
                raise KeyboardInterrupt

            def close(self):
                calls.append("close")

        calls = []
        with patch.object(sync, "FastTMDBSyncer", InterruptedSyncer), patch.object(
            sync.signal, "signal"
        ):
            assert sync.main(["--limit", "1"]) == sync.EXIT_INTERRUPTED

        assert calls == ["rollback", "close"]

    def test_lock_held_exits_two(self):
        class LockedSyncer:
            def __init__(self, **kwargs):
                pass

            def acquire_lock(self):
                raise sync.SyncAlreadyRunning("another TMDB sync is already running")

            def close(self):
                pass

        with patch.object(sync, "FastTMDBSyncer", LockedSyncer), patch.object(
            sync.signal, "signal"
        ):
            assert sync.main([]) == sync.EXIT_LOCKED
