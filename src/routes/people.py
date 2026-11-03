"""Actors and directors: listings, detail pages, shared films and networks."""

from flask import Blueprint, abort, render_template, request
from sqlalchemy import desc, func, select
from sqlalchemy.orm import aliased, selectinload

from config.config import Config
from src.helpers import (
    _cached,
    _contains_pattern,
    _content_filtered,
    _html_page_arg,
    get_current_user,
    get_db_session,
)
from src.models import Cast, Crew, Genre, Movie, Person

bp = Blueprint("people", __name__)


# Director and studio listings count a movie once it has this many votes;
# the detail pages use the same rule so the counts agree
LISTING_MIN_VOTES = 10

_DIRECTOR_SORTS = {
    "movies": lambda q: (desc("movie_count"), Person.id),
    "avg_rating": lambda q: (desc("avg_rating"), desc("movie_count"), Person.id),
    "total_revenue": lambda q: (desc("total_revenue"), Person.id),
    "name": lambda q: (Person.name, Person.id),
}


_DIRECTOR_MIN_MOVIES = (1, 3, 5, 10)


@bp.route("/directors")
def directors():
    """Director spotlight page: search, sort and minimum count run in SQL"""
    session_db = get_db_session()
    try:
        page = _html_page_arg()
        per_page = 24

        user = get_current_user(session_db)

        search = request.args.get("q", "").strip()
        sort_by = request.args.get("sort", "movies")
        if sort_by not in _DIRECTOR_SORTS:
            sort_by = "movies"
        min_movies = request.args.get("min_movies", default=3, type=int)
        if min_movies not in _DIRECTOR_MIN_MOVIES:
            min_movies = 3

        directors_query = (
            session_db.query(
                Person.id,
                Person.name,
                func.count(Movie.id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
                func.sum(Movie.revenue).label("total_revenue"),
            )
            .join(Crew, Person.id == Crew.person_id)
            .join(Movie, Crew.movie_id == Movie.id)
            .filter(Crew.job == "Director")
            .filter(Movie.vote_count > LISTING_MIN_VOTES)
        )
        if search:
            directors_query = directors_query.filter(
                Person.name.ilike(_contains_pattern(search), escape="\\")
            )
        directors_query = (
            directors_query.group_by(Person.id, Person.name)
            .having(func.count(Movie.id) >= min_movies)
            .order_by(*_DIRECTOR_SORTS[sort_by](directors_query))
        )

        total = directors_query.order_by(None).count()
        total_pages = (total + per_page - 1) // per_page if total else 1
        page = max(1, min(page, total_pages))
        directors_data = directors_query.limit(per_page).offset((page - 1) * per_page).all()

        # Top 3 rated movies for every director on the page, in one query
        director_ids = [d.id for d in directors_data]
        top_by_director = {director_id: [] for director_id in director_ids}
        if director_ids:
            rank = (
                func.row_number()
                .over(
                    partition_by=Crew.person_id,
                    order_by=(
                        desc(Movie.vote_average),
                        desc(Movie.vote_count),
                        Movie.id,
                    ),
                )
                .label("rank")
            )
            ranked = (
                select(
                    Crew.person_id,
                    Movie.id,
                    Movie.title,
                    Movie.release_date,
                    Movie.vote_average,
                    rank,
                )
                .join(Movie, Crew.movie_id == Movie.id)
                .where(
                    Crew.person_id.in_(director_ids),
                    Crew.job == "Director",
                    Movie.vote_count > LISTING_MIN_VOTES,
                )
                .subquery()
            )
            for row in session_db.execute(
                select(ranked).where(ranked.c.rank <= 3).order_by(ranked.c.person_id, ranked.c.rank)
            ):
                top_by_director[row.person_id].append(
                    {
                        "id": row.id,
                        "title": row.title,
                        "year": row.release_date.year if row.release_date else None,
                        "vote_average": row.vote_average,
                    }
                )

        directors_list = [
            {
                "id": d.id,
                "name": d.name,
                "movie_count": d.movie_count,
                "avg_rating": d.avg_rating or 0,
                "total_revenue": int(d.total_revenue or 0),
                "top_movies": top_by_director[d.id],
            }
            for d in directors_data
        ]

        return render_template(
            "directors.html",
            directors=directors_list,
            page=page,
            total_pages=total_pages,
            total=total,
            search=search,
            sort_by=sort_by,
            min_movies=min_movies,
            min_movie_options=_DIRECTOR_MIN_MOVIES,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@bp.route("/director/<int:director_id>")
def director_detail(director_id):
    """Individual director filmography page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)

        # Get director info
        director = session_db.query(Person).filter_by(id=director_id).first()
        if not director:
            abort(404)

        # Every movie directed by this person, newest first (undated last on
        # every database: Postgres would otherwise put NULL dates first)
        movies = (
            session_db.query(Movie)
            .join(Crew, Movie.id == Crew.movie_id)
            .filter(Crew.person_id == director_id)
            .filter(Crew.job == "Director")
            .options(selectinload(Movie.genres))
            .order_by(desc(Movie.release_date).nulls_last(), Movie.id)
            .distinct()
            .all()
        )
        if not movies:
            # A real person, but not a director (an actor-only id, for example)
            abort(404)

        # Calculate statistics. Averages use rated movies only: TMDB reports
        # 0.0 for movies nobody has voted on yet.
        total_movies = len(movies)
        rated_values = [
            float(m.vote_average) for m in movies if m.vote_average is not None and m.vote_count
        ]
        avg_rating = sum(rated_values) / len(rated_values) if rated_values else None
        total_revenue = sum(m.revenue or 0 for m in movies)

        years = [m.release_date.year for m in movies if m.release_date]
        first_year = min(years) if years else None
        last_year = max(years) if years else None
        years_active = (last_year - first_year + 1) if first_year and last_year else 0

        # Genre distribution
        genre_counts = {}
        for movie in movies:
            for genre in movie.genres:
                genre_counts[genre.name] = genre_counts.get(genre.name, 0) + 1

        genres = [
            {"name": name, "count": count}
            for name, count in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        # Chart data (movies by year)
        year_data = {}
        for movie in movies:
            if movie.release_date:
                year = movie.release_date.year
                if year not in year_data:
                    year_data[year] = {"ratings": [], "revenues": []}
                if movie.vote_average is not None and movie.vote_count:
                    year_data[year]["ratings"].append(float(movie.vote_average))
                year_data[year]["revenues"].append((movie.revenue or 0) / 1000000)

        chart_years = sorted(year_data.keys())
        # None leaves a gap in the chart for years with no rated movie, instead
        # of plotting a misleading 0
        chart_ratings = [
            (
                round(sum(year_data[y]["ratings"]) / len(year_data[y]["ratings"]), 2)
                if year_data[y]["ratings"]
                else None
            )
            for y in chart_years
        ]
        chart_revenues = [sum(year_data[y]["revenues"]) for y in chart_years]

        stats = {
            "total_movies": total_movies,
            "avg_rating": avg_rating,
            "total_revenue": total_revenue,
            "years_active": years_active,
            "first_year": first_year,
            "last_year": last_year,
            "genres": genres,
        }

        chart_data = {
            "years": chart_years,
            "ratings": chart_ratings,
            "revenues": chart_revenues,
        }

        movies_list = [
            {
                "id": m.id,
                "title": m.title,
                "year": m.release_date.year if m.release_date else None,
                "poster_path": m.poster_path,
                "vote_average": m.vote_average,
                "revenue": m.revenue,
                "runtime": m.runtime,
                "genres": [g.name for g in m.genres],
            }
            for m in movies
        ]

        return render_template(
            "director_detail.html",
            director=director,
            movies=movies_list,
            stats=stats,
            chart_data=chart_data,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@bp.route("/top-actors")
def top_actors():
    """Top actors page - actors who appear in most movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        sort_by = request.args.get("sort", default="movie_count")
        if sort_by not in ("movie_count", "avg_rating", "avg_popularity", "name"):
            sort_by = "movie_count"
        page = _html_page_arg()
        per_page = 24

        def compute():
            # Count movies per actor. The aggregate scans the whole cast table,
            # so the result is cached; Person.id last keeps pages stable.
            query = (
                session.query(
                    Person.id,
                    Person.name,
                    Person.profile_path,
                    func.count(func.distinct(Cast.movie_id)).label("movie_count"),
                    func.avg(Movie.vote_average).label("avg_rating"),
                    func.avg(Movie.popularity).label("avg_popularity"),
                    func.count().over().label("total_actors"),
                )
                .join(Cast, Person.id == Cast.person_id)
                .join(Movie, Cast.movie_id == Movie.id)
                .filter(Movie.vote_count > 20)
                .group_by(Person.id, Person.name, Person.profile_path)
                .having(func.count(func.distinct(Cast.movie_id)) >= 2)
            )
            orderings = {
                "avg_rating": (desc("avg_rating"), Person.id),
                "avg_popularity": (desc("avg_popularity"), Person.id),
                "name": (Person.name, Person.id),
                "movie_count": (desc("movie_count"), Person.id),
            }
            rows = (
                query.order_by(*orderings[sort_by])
                .limit(per_page)
                .offset((page - 1) * per_page)
                .all()
            )
            total = rows[0].total_actors if rows else query.order_by(None).count()
            return total, [
                {
                    "person": {
                        "id": r.id,
                        "name": r.name,
                        "profile_path": r.profile_path,
                    },
                    "movie_count": r.movie_count,
                    "avg_rating": float(r.avg_rating) if r.avg_rating is not None else None,
                    "avg_popularity": (
                        float(r.avg_popularity) if r.avg_popularity is not None else None
                    ),
                }
                for r in rows
            ]

        total_actors, actors_list = _cached(f"top_actors:{sort_by}:{page}", compute)

        # Calculate pagination info
        total_pages = (total_actors + per_page - 1) // per_page

        return render_template(
            "top_actors.html",
            actors=actors_list,
            sort_by=sort_by,
            page=page,
            total_pages=total_pages,
            total_actors=total_actors,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@bp.route("/actor/<int:actor_id>")
def actor_detail(actor_id):
    """Actor detail page with filmography"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Get actor info
        actor = session.query(Person).filter_by(id=actor_id).first()

        if not actor:
            abort(404)

        # Filmography, newest first (undated movies last on every database)
        filmography_raw = (
            session.query(Movie, Cast)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .order_by(desc(Movie.release_date).nulls_last(), Movie.id, Cast.cast_order)
            .all()
        )
        if not filmography_raw:
            # A real person, but not in any cast (a director-only id, for example)
            abort(404)

        # (movie, character, cast_order), one entry per movie: an actor with two
        # roles in one film gets them joined rather than listed twice
        filmography = []
        by_movie = {}
        for movie, cast in filmography_raw:
            character = cast.character_name or "Unknown"
            if movie.id in by_movie:
                index = by_movie[movie.id]
                previous_movie, previous_character, order = filmography[index]
                filmography[index] = (
                    previous_movie,
                    f"{previous_character} / {character}",
                    order,
                )
                continue
            by_movie[movie.id] = len(filmography)
            filmography.append((movie, character, cast.cast_order or 0))

        # Calculate statistics
        total_movies = len(filmography)
        avg_rating = (
            session.query(func.avg(Movie.vote_average))
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id, Movie.vote_count > 20)
            .scalar()
        )

        # Get genres this actor appears in most
        top_genres = (
            session.query(Genre.name, func.count(func.distinct(Movie.id)).label("count"))
            .join(Movie.genres)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
            .limit(5)
            .all()
        )

        return render_template(
            "actor_detail.html",
            actor=actor,
            filmography=filmography,
            total_movies=total_movies,
            avg_rating=round(avg_rating, 1) if avg_rating else None,
            top_genres=top_genres,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@bp.route("/common-films")
def common_films():
    """Find movies shared by a set of selected actors."""
    session = get_db_session()
    try:
        user = get_current_user(session)
        # Unique ids in selection order, capped at 5 to keep the query sane
        actor_ids = list(dict.fromkeys(request.args.getlist("actor", type=int)))[:5]

        actors = []
        movies = []

        if actor_ids:
            actors = session.query(Person).filter(Person.id.in_(actor_ids)).all()
            # Preserve selection order
            actor_map = {a.id: a for a in actors}
            actors = [actor_map[aid] for aid in actor_ids if aid in actor_map]

            if actors:
                # Movies where ALL selected actors appear, found in SQL
                shared_movie_ids = (
                    select(Cast.movie_id)
                    .where(Cast.person_id.in_([a.id for a in actors]))
                    .group_by(Cast.movie_id)
                    .having(func.count(func.distinct(Cast.person_id)) == len(actors))
                )
                movies = (
                    _content_filtered(session.query(Movie))
                    .filter(Movie.id.in_(shared_movie_ids))
                    .filter(Movie.vote_count > 0)
                    .order_by(desc(Movie.popularity), Movie.id)
                    .all()
                )

        return render_template(
            "common_films.html",
            actors=actors,
            movies=movies,
            actor_ids=actor_ids,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


NETWORK_MAX_COLLABORATORS = 30


@bp.route("/actor/<int:actor_id>/network")
def actor_network(actor_id):
    """Collaboration network for a given actor.

    Nodes  = the focal actor + everyone who has shared at least one movie with them.
    Edges  = (actor_a, actor_b, shared_movie_count) for every collaborating pair,
             including edges between collaborators themselves (second-ring links).
    Capped at 30 collaborators so the graph stays readable.
    """
    session = get_db_session()
    try:
        user = get_current_user(session)

        actor = session.query(Person).filter_by(id=actor_id).first()
        if not actor:
            abort(404)

        # ── Step 1: movies the focal actor appeared in ──────────────────────
        focal_movie_ids = [
            row.movie_id
            for row in session.query(Cast.movie_id).filter(Cast.person_id == actor_id).all()
        ]

        if not focal_movie_ids:
            return render_template(
                "actor_network.html",
                actor=actor,
                graph_data={"nodes": [], "links": []},
                collaborator_count=0,
                current_user=user,
                config=Config,
            )

        # ── Step 2: direct collaborators (other actors in the same movies) ──
        collaborators_raw = (
            session.query(
                Person.id,
                Person.name,
                Person.profile_path,
                func.count(func.distinct(Cast.movie_id)).label("shared_movies"),
            )
            .join(Cast, Person.id == Cast.person_id)
            .filter(
                Cast.movie_id.in_(focal_movie_ids),
                Person.id != actor_id,
            )
            .group_by(Person.id, Person.name, Person.profile_path)
            .order_by(desc("shared_movies"), Person.id)
            .limit(NETWORK_MAX_COLLABORATORS)
            .all()
        )

        if not collaborators_raw:
            return render_template(
                "actor_network.html",
                actor=actor,
                graph_data={"nodes": [], "links": []},
                collaborator_count=0,
                current_user=user,
                config=Config,
            )

        collab_ids = [r.id for r in collaborators_raw]

        # ── Step 3: edges between collaborators (second-ring links) ─────────
        # Find movies shared between any two collaborators (excluding focal actor)
        c1 = aliased(Cast)
        c2 = aliased(Cast)
        collab_edges_raw = (
            session.query(
                c1.person_id.label("actor_a"),
                c2.person_id.label("actor_b"),
                func.count(func.distinct(c1.movie_id)).label("shared"),
            )
            .join(c2, c1.movie_id == c2.movie_id)
            .filter(
                c1.person_id.in_(collab_ids),
                c2.person_id.in_(collab_ids),
                c1.person_id < c2.person_id,  # avoid duplicates
            )
            .group_by(c1.person_id, c2.person_id)
            .all()
        )

        # ── Step 4: build D3-ready graph data ────────────────────────────────
        focal_movie_set = set(focal_movie_ids)

        # Per-person movie sets, built once and reused for every edge
        person_movie_sets = {}
        for row in (
            session.query(Cast.person_id, Cast.movie_id)
            .filter(Cast.person_id.in_(collab_ids + [actor_id]))
            .all()
        ):
            person_movie_sets.setdefault(row.person_id, set()).add(row.movie_id)

        # Titles are only needed for movies an edge actually shows
        edge_movie_ids = set()
        for r in collaborators_raw:
            edge_movie_ids |= focal_movie_set & person_movie_sets.get(r.id, set())
        for edge in collab_edges_raw:
            edge_movie_ids |= person_movie_sets.get(edge.actor_a, set()) & person_movie_sets.get(
                edge.actor_b, set()
            )
        movies_lookup = {
            m.id: m.title
            for m in session.query(Movie.id, Movie.title).filter(Movie.id.in_(edge_movie_ids)).all()
        }

        nodes = [
            {
                "id": actor.id,
                "name": actor.name,
                "profile_path": actor.profile_path,
                "shared_movies": 0,
                "focal": True,
            }
        ]
        for r in collaborators_raw:
            nodes.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "profile_path": r.profile_path,
                    "shared_movies": r.shared_movies,
                    "focal": False,
                }
            )

        # Focal-actor → collaborator edges with movie titles
        links = []
        for r in collaborators_raw:
            shared_ids = focal_movie_set & person_movie_sets.get(r.id, set())
            links.append(
                {
                    "source": actor.id,
                    "target": r.id,
                    "value": r.shared_movies,
                    "movies": sorted(
                        movies_lookup[mid] for mid in shared_ids if mid in movies_lookup
                    ),
                }
            )

        # Collaborator → collaborator edges with movie titles
        for edge in collab_edges_raw:
            shared_ids = person_movie_sets.get(edge.actor_a, set()) & person_movie_sets.get(
                edge.actor_b, set()
            )
            links.append(
                {
                    "source": edge.actor_a,
                    "target": edge.actor_b,
                    "value": edge.shared,
                    "movies": sorted(
                        movies_lookup[mid] for mid in shared_ids if mid in movies_lookup
                    ),
                }
            )

        graph_data = {"nodes": nodes, "links": links}

        return render_template(
            "actor_network.html",
            actor=actor,
            graph_data=graph_data,
            collaborator_count=len(collaborators_raw),
            # The graph shows at most NETWORK_MAX_COLLABORATORS; say so when capped
            collaborators_capped=len(collaborators_raw) >= NETWORK_MAX_COLLABORATORS,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()
