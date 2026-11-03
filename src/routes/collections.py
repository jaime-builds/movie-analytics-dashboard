"""User-curated movie collections."""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import desc, func

from config.config import Config
from src.helpers import (
    _association_exists,
    _association_filters,
    _current_relative_url,
    _html_page_arg,
    _insert_association,
    get_current_user,
    get_db_session,
)
from src.models import Collection, Movie, collection_movies_table, utcnow

bp = Blueprint("collections", __name__)


MAX_COLLECTION_DESCRIPTION_LENGTH = 2000


def _association_count(session_db, table, **column_values):
    return (
        session_db.query(func.count())
        .select_from(table)
        .filter(*_association_filters(table, **column_values))
        .scalar()
        or 0
    )


def _collection_movies_page(session_db, collection_id, offset, limit):
    return (
        session_db.query(Movie)
        .join(collection_movies_table, Movie.id == collection_movies_table.c.movie_id)
        .filter(collection_movies_table.c.collection_id == collection_id)
        .order_by(collection_movies_table.c.added_at, Movie.id)
        .offset(offset)
        .limit(limit)
        .all()
    )


@bp.route("/collections")
def index():
    """User's collections listing page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your collections", "warning")
            return redirect(url_for("auth.login", next=_current_relative_url()))

        user_collections = (
            session_db.query(Collection)
            .filter_by(user_id=user.id)
            .order_by(desc(Collection.updated_at), Collection.id)
            .all()
        )

        # Counts and the first four posters, without loading every movie
        collection_ids = [c.id for c in user_collections]
        counts = dict(
            session_db.query(
                collection_movies_table.c.collection_id,
                func.count(collection_movies_table.c.movie_id),
            )
            .filter(collection_movies_table.c.collection_id.in_(collection_ids))
            .group_by(collection_movies_table.c.collection_id)
            .all()
        )
        previews = {
            c.id: _collection_movies_page(session_db, c.id, 0, 4)
            for c in user_collections
            if counts.get(c.id)
        }

        return render_template(
            "collections.html",
            collections=user_collections,
            counts=counts,
            previews=previews,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@bp.route("/collections/create", methods=["POST"])
def create():
    """Create a new collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to manage collections", "warning")
            return redirect(url_for("auth.login", next=url_for("collections.index")))

        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Collection name is required", "danger")
            return redirect(url_for("collections.index"))

        if len(name) > 255:
            flash("Collection name must be 255 characters or fewer", "danger")
            return redirect(url_for("collections.index"))

        if len(description) > MAX_COLLECTION_DESCRIPTION_LENGTH:
            flash(
                f"Description must be {MAX_COLLECTION_DESCRIPTION_LENGTH} characters or fewer",
                "danger",
            )
            return redirect(url_for("collections.index"))

        collection = Collection(
            user_id=user.id,
            name=name,
            description=description or None,
        )
        session_db.add(collection)
        session_db.commit()

        flash(f'Collection "{name}" created', "success")
        return redirect(url_for("collections.detail", collection_id=collection.id))
    finally:
        session_db.close()


@bp.route("/collection/<int:collection_id>")
def detail(collection_id):
    """Individual collection detail page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view collections", "warning")
            return redirect(url_for("auth.login", next=_current_relative_url()))

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            flash("Collection not found", "danger")
            return redirect(url_for("collections.index"))

        # Paginate the movies in this collection
        page = _html_page_arg()
        per_page = 24
        total = _association_count(session_db, collection_movies_table, collection_id=collection.id)
        total_pages = (total + per_page - 1) // per_page if total else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page
        paged_movies = _collection_movies_page(session_db, collection.id, offset, per_page)

        return render_template(
            "collection_detail.html",
            collection=collection,
            movies=paged_movies,
            total=total,
            page=page,
            total_pages=total_pages,
            per_page=per_page,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@bp.route("/collection/<int:collection_id>/delete", methods=["POST"])
def delete(collection_id):
    """Delete a collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to manage collections", "warning")
            return redirect(url_for("auth.login", next=url_for("collections.index")))

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            flash("Collection not found", "danger")
            return redirect(url_for("collections.index")), 404

        name = collection.name
        session_db.delete(collection)
        session_db.commit()

        flash(f'Collection "{name}" deleted', "success")
        return redirect(url_for("collections.index"))
    finally:
        session_db.close()


@bp.route("/collection/<int:collection_id>/add/<int:movie_id>", methods=["POST"])
def add_movie(collection_id, movie_id):
    """Add a movie to a collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            return jsonify({"error": "Collection not found"}), 404

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        status = "already_added"
        if not _association_exists(
            session_db,
            collection_movies_table,
            collection_id=collection.id,
            movie_id=movie.id,
        ):
            collection.updated_at = utcnow()
            if _insert_association(
                session_db,
                collection_movies_table,
                collection_id=collection.id,
                movie_id=movie.id,
            ):
                status = "added"

        count = _association_count(session_db, collection_movies_table, collection_id=collection.id)
        return jsonify({"status": status, "count": count})
    finally:
        session_db.close()


@bp.route("/collection/<int:collection_id>/remove/<int:movie_id>", methods=["POST"])
def remove_movie(collection_id, movie_id):
    """Remove a movie from a collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            return jsonify({"error": "Collection not found"}), 404

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        if _association_exists(
            session_db,
            collection_movies_table,
            collection_id=collection.id,
            movie_id=movie.id,
        ):
            session_db.execute(
                collection_movies_table.delete().where(
                    collection_movies_table.c.collection_id == collection.id,
                    collection_movies_table.c.movie_id == movie.id,
                )
            )
            collection.updated_at = utcnow()
            count = _association_count(
                session_db, collection_movies_table, collection_id=collection.id
            )
            session_db.commit()
            return jsonify({"status": "removed", "count": count})

        count = _association_count(session_db, collection_movies_table, collection_id=collection.id)
        return jsonify({"status": "not_found", "count": count}), 404
    finally:
        session_db.close()
