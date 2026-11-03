from datetime import datetime, timezone

from sqlalchemy import (
    DECIMAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    false,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

from config.config import Config


def utcnow():
    """Current UTC time as a naive datetime, matching the existing DateTime columns.

    Use for stored timestamps (created_at, banned_at and the like).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_today():
    """Today's date in the server's time zone (the container sets TZ).

    Use for "which day is it" logic that people see: Movie of the Day rolls
    over at local midnight, and page views are counted per local day.
    """
    return datetime.now().date()


# Predictable constraint names, so later migrations can find and drop them
# (Postgres otherwise generates names like movies_tmdb_id_key)
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Base = declarative_base(metadata=MetaData(naming_convention=NAMING_CONVENTION))
# pool_pre_ping replaces connections that died while idle (a Postgres restart,
# for example) instead of failing the first request that picks one up
engine = create_engine(Config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# Association tables for many-to-many relationships
movie_genres_table = Table(
    "movie_genres",
    Base.metadata,
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
    Column("genre_id", Integer, ForeignKey("genres.id"), primary_key=True),
    Index("idx_movie_genres_genre_id", "genre_id"),
)

movie_companies_table = Table(
    "movie_companies",
    Base.metadata,
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
    Column("company_id", Integer, ForeignKey("production_companies.id"), primary_key=True),
    Index("idx_movie_companies_company_id", "company_id"),
)

collection_movies_table = Table(
    "collection_movies",
    Base.metadata,
    Column("collection_id", Integer, ForeignKey("collections.id"), primary_key=True),
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
    Column("added_at", DateTime, nullable=False, default=utcnow),
    Index("idx_collection_movies_movie_id", "movie_id"),
)

# Association tables for favorites and watchlist
# added_at is NULL for rows added before migration 009 recorded it
user_favorites_table = Table(
    "user_favorites",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
    Column("added_at", DateTime, nullable=True, default=utcnow),
    Index("idx_user_favorites_movie_id", "movie_id"),
)

user_watchlist_table = Table(
    "user_watchlist",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
    Column("added_at", DateTime, nullable=True, default=utcnow),
    Index("idx_user_watchlist_movie_id", "movie_id"),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    # Admin dashboard: access control
    is_admin = Column(Boolean, nullable=False, default=False, server_default=false())
    is_banned = Column(Boolean, nullable=False, default=False, server_default=false())
    banned_at = Column(DateTime)

    # Bumped on logout and ban; sessions carrying an older value are rejected
    session_version = Column(Integer, nullable=False, default=0, server_default="0")

    # Opt out of the public activity feed
    hide_activity = Column(Boolean, nullable=False, default=False, server_default=false())

    # Relationships
    favorites = relationship(
        "Movie",
        secondary=user_favorites_table,
        back_populates="favorited_by_users",
        lazy="dynamic",
    )
    watchlist = relationship(
        "Movie",
        secondary=user_watchlist_table,
        back_populates="watchlisted_by_users",
        lazy="dynamic",
    )

    # NEW: Relationships for ratings and reviews
    ratings = relationship("Rating", back_populates="user", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="user", cascade="all, delete-orphan")
    collections = relationship("Collection", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User(username='{self.username}')>"


class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True)
    tmdb_id = Column(Integer, unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    original_title = Column(String(255))
    overview = Column(Text)
    release_date = Column(Date)
    runtime = Column(Integer)
    budget = Column(BigInteger)
    revenue = Column(BigInteger)
    popularity = Column(DECIMAL(10, 2))
    vote_average = Column(DECIMAL(3, 1))
    vote_count = Column(Integer)
    poster_path = Column(String(255))
    backdrop_path = Column(String(255))
    imdb_id = Column(String(20))
    status = Column(String(50))
    tagline = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Content flags (see src/content.py). is_mature comes from TMDB keywords;
    # hide_from_featured is an admin's manual "keep off the home page".
    is_mature = Column(Boolean, nullable=False, default=False, server_default=false())
    hide_from_featured = Column(Boolean, nullable=False, default=False, server_default=false())

    __table_args__ = (
        Index("idx_movies_vote_count", "vote_count"),
        Index("idx_movies_title", "title"),
        Index("idx_movies_release_date", "release_date"),
        Index("idx_movies_vote_average", "vote_average"),
        Index("idx_movies_popularity", "popularity"),
    )

    # Relationships
    genres = relationship("Genre", secondary=movie_genres_table, back_populates="movies")
    cast_members = relationship("Cast", back_populates="movie", cascade="all, delete-orphan")
    crew_members = relationship("Crew", back_populates="movie", cascade="all, delete-orphan")
    companies = relationship(
        "ProductionCompany", secondary=movie_companies_table, back_populates="movies"
    )

    # Relationships for favorites/watchlist
    favorited_by_users = relationship(
        "User",
        secondary=user_favorites_table,
        back_populates="favorites",
        lazy="dynamic",
    )
    watchlisted_by_users = relationship(
        "User",
        secondary=user_watchlist_table,
        back_populates="watchlist",
        lazy="dynamic",
    )

    # NEW: Relationships for ratings and reviews
    ratings = relationship("Rating", back_populates="movie", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="movie", cascade="all, delete-orphan")
    collections = relationship(
        "Collection", secondary=collection_movies_table, back_populates="movies"
    )

    def __repr__(self):
        return f"<Movie(title='{self.title}', year={self.release_date.year if self.release_date else 'N/A'})>"


# NEW: Rating model for Feature 1
class Rating(Base):
    __tablename__ = "ratings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5 stars
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Admin dashboard: soft-delete moderation
    is_deleted = Column(Boolean, nullable=False, default=False, server_default=false())
    deleted_at = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="ratings")
    movie = relationship("Movie", back_populates="ratings")

    # Constraints
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="check_rating_range"),
        Index(
            "idx_user_movie_rating", "user_id", "movie_id", unique=True
        ),  # One rating per user per movie
        Index("idx_ratings_movie_id", "movie_id"),  # Fast avg/count by movie
    )

    def __repr__(self):
        return f"<Rating(user_id={self.user_id}, movie_id={self.movie_id}, rating={self.rating})>"


# NEW: Review model for Feature 1
class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Admin dashboard: soft-delete moderation
    is_deleted = Column(Boolean, nullable=False, default=False, server_default=false())
    deleted_at = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="reviews")
    movie = relationship("Movie", back_populates="reviews")

    # Index for efficient queries
    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", name="uq_reviews_user_movie"),
        Index("idx_movie_reviews", "movie_id"),
        Index("idx_user_reviews", "user_id"),
    )

    def __repr__(self):
        return f"<Review(user_id={self.user_id}, movie_id={self.movie_id})>"


class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    user = relationship("User", back_populates="collections")
    movies = relationship("Movie", secondary=collection_movies_table, back_populates="collections")

    __table_args__ = (Index("idx_collections_user_id", "user_id"),)

    def __repr__(self):
        return f"<Collection(name='{self.name}', user_id={self.user_id})>"


class MovieOfTheDay(Base):
    __tablename__ = "movie_of_the_day"

    id = Column(Integer, primary_key=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    shown_date = Column(Date, nullable=False)

    # Relationships
    movie = relationship("Movie")

    # One featured movie per calendar day
    __table_args__ = (
        UniqueConstraint("shown_date", name="uq_movie_of_the_day_shown_date"),
        Index("idx_movie_of_the_day_movie_id", "movie_id"),
    )

    def __repr__(self):
        return f"<MovieOfTheDay(movie_id={self.movie_id}, shown_date={self.shown_date})>"


class PageView(Base):
    __tablename__ = "page_views"

    id = Column(Integer, primary_key=True)
    path = Column(String(255), nullable=False)
    view_date = Column(Date, nullable=False)
    count = Column(Integer, nullable=False, default=1)

    # One counter row per path per calendar day
    __table_args__ = (
        UniqueConstraint("path", "view_date", name="uq_page_views_path_date"),
        Index("idx_page_views_view_date", "view_date"),
    )

    def __repr__(self):
        return f"<PageView(path='{self.path}', view_date={self.view_date}, count={self.count})>"


class SiteSetting(Base):
    __tablename__ = "site_settings"

    key = Column(String(100), primary_key=True)
    value = Column(String(255))

    def __repr__(self):
        return f"<SiteSetting(key='{self.key}', value='{self.value}')>"


class Genre(Base):
    __tablename__ = "genres"

    id = Column(Integer, primary_key=True)
    tmdb_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(100), nullable=False)

    # Relationships
    movies = relationship("Movie", secondary=movie_genres_table, back_populates="genres")

    def __repr__(self):
        return f"<Genre(name='{self.name}')>"


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True)
    tmdb_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    profile_path = Column(String(255))
    popularity = Column(DECIMAL(10, 2))

    # Relationships (deleting a person removes their credits rather than
    # leaving rows with a NULL person_id)
    cast_roles = relationship("Cast", back_populates="person", cascade="all, delete-orphan")
    crew_roles = relationship("Crew", back_populates="person", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Person(name='{self.name}')>"


class Cast(Base):
    __tablename__ = "cast"

    id = Column(Integer, primary_key=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    # TEXT: TMDB joins every role in an ensemble voice cast into one string
    character_name = Column(Text)
    cast_order = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_cast_movie_id", "movie_id"),
        Index("idx_cast_person_id", "person_id"),
    )

    # Relationships
    movie = relationship("Movie", back_populates="cast_members")
    person = relationship("Person", back_populates="cast_roles")

    def __repr__(self):
        return f"<Cast(person_id={self.person_id}, character='{self.character_name}')>"


class Crew(Base):
    __tablename__ = "crew"

    id = Column(Integer, primary_key=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    job = Column(String(100), nullable=False)
    department = Column(String(100))

    __table_args__ = (
        Index("idx_crew_movie_id", "movie_id"),
        Index("idx_crew_person_id", "person_id"),
        Index("idx_crew_person_job", "person_id", "job"),  # Covers director lookups
    )

    # Relationships
    movie = relationship("Movie", back_populates="crew_members")
    person = relationship("Person", back_populates="crew_roles")

    def __repr__(self):
        return f"<Crew(person_id={self.person_id}, job='{self.job}')>"


class ProductionCompany(Base):
    __tablename__ = "production_companies"

    id = Column(Integer, primary_key=True)
    tmdb_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    logo_path = Column(String(255))
    origin_country = Column(String(10))

    # Relationships
    movies = relationship("Movie", secondary=movie_companies_table, back_populates="companies")

    def __repr__(self):
        return f"<ProductionCompany(name='{self.name}')>"


def init_db():
    """Deprecated: initialize or upgrade schema with Alembic instead."""
    raise RuntimeError("Database schema is managed by Alembic. Run: alembic upgrade head")


if __name__ == "__main__":
    raise SystemExit("Database schema is managed by Alembic. Run: alembic upgrade head")
