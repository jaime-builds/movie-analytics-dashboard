from datetime import datetime
from typing import List

from sqlalchemy import (
    DECIMAL,
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
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
)

movie_companies_table = Table(
    "movie_companies",
    Base.metadata,
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
    Column("company_id", Integer, ForeignKey("production_companies.id"), primary_key=True),
)

# New association tables for favorites and watchlist
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

    # Relationships
    genres = relationship("Genre", secondary=movie_genres_table, back_populates="movies")
    cast_members = relationship("Cast", back_populates="movie", cascade="all, delete-orphan")
    crew_members = relationship("Crew", back_populates="movie", cascade="all, delete-orphan")
    companies = relationship(
        "ProductionCompany", secondary=movie_companies_table, back_populates="movies"
    )

    # New relationships for favorites/watchlist
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

    def __repr__(self):
        return f"<Movie(title='{self.title}', year={self.release_date.year if self.release_date else 'N/A'})>"


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
    __tablename__ = "people"  # Changed from "persons" to "people"

    id = Column(Integer, primary_key=True)
    tmdb_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    profile_path = Column(String(255))  # ← ADD THIS LINE FOR ACTOR PHOTOS!

    # Relationships
    cast_roles = relationship("Cast", back_populates="person")
    crew_roles = relationship("Crew", back_populates="person")

    def __repr__(self):
        return f"<Person(name='{self.name}')>"


class Cast(Base):
    __tablename__ = "cast"

    id = Column(Integer, primary_key=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)  # Changed to people
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
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)  # Changed to people
    job = Column(String(100), nullable=False)
    department = Column(String(100))

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
