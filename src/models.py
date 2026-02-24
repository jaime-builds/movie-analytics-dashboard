from datetime import datetime
from typing import List

from sqlalchemy import (
    DECIMAL,
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

from config.config import Config

Base = declarative_base()
engine = create_engine(Config.DATABASE_URL)
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
)

# Association tables for favorites and watchlist
user_favorites_table = Table(
    "user_favorites",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
)

user_watchlist_table = Table(
    "user_watchlist",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_movies_vote_count", "vote_count"),
        Index("idx_movies_title", "title"),
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

    def __repr__(self):
        return f"<Movie(title='{self.title}', year={self.release_date.year if self.release_date else 'N/A'})>"


# NEW: Rating model for Feature 1
class Rating(Base):
    __tablename__ = "ratings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5 stars
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="ratings")
    movie = relationship("Movie", back_populates="ratings")

    # Constraints
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="check_rating_range"),
        Index("idx_user_movie_rating", "user_id", "movie_id", unique=True),  # One rating per user per movie
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="reviews")
    movie = relationship("Movie", back_populates="reviews")

    # Index for efficient queries
    __table_args__ = (
        Index("idx_movie_reviews", "movie_id"),
        Index("idx_user_reviews", "user_id"),
    )

    def __repr__(self):
        return f"<Review(user_id={self.user_id}, movie_id={self.movie_id})>"


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

    # Relationships
    cast_roles = relationship("Cast", back_populates="person")
    crew_roles = relationship("Crew", back_populates="person")

    def __repr__(self):
        return f"<Person(name='{self.name}')>"


class Cast(Base):
    __tablename__ = "cast"

    id = Column(Integer, primary_key=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    character_name = Column(String(255))
    cast_order = Column(Integer, default=0)

    # Relationships
    movie = relationship("Movie", back_populates="cast_members")
    person = relationship("Person", back_populates="cast_roles")

    def __repr__(self):
        return f"<Cast(person='{self.person.name if self.person else 'Unknown'}', character='{self.character_name}')>"


class Crew(Base):
    __tablename__ = "crew"

    id = Column(Integer, primary_key=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    job = Column(String(100), nullable=False)
    department = Column(String(100))

    __table_args__ = (
        Index("idx_crew_person_id", "person_id"),
        Index("idx_crew_person_job", "person_id", "job"),  # Covers director lookups
    )

    # Relationships
    movie = relationship("Movie", back_populates="crew_members")
    person = relationship("Person", back_populates="crew_roles")

    def __repr__(self):
        return (
            f"<Crew(person='{self.person.name if self.person else 'Unknown'}', job='{self.job}')>"
        )


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
    """Initialize the database"""
    Base.metadata.create_all(engine)
    print("Database initialized successfully!")


if __name__ == "__main__":
    init_db()
