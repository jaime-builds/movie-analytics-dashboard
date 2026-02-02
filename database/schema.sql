-- Movies table
CREATE TABLE movies (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    original_title VARCHAR(255),
    overview TEXT,
    release_date DATE,
    runtime INTEGER,
    budget BIGINT,
    revenue BIGINT,
    popularity DECIMAL(10, 2),
    vote_average DECIMAL(3, 1),
    vote_count INTEGER,
    poster_path VARCHAR(255),
    backdrop_path VARCHAR(255),
    imdb_id VARCHAR(20),
    status VARCHAR(50),
    tagline TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Genres table
CREATE TABLE genres (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL
);

-- Movie-Genre junction table (many-to-many)
CREATE TABLE movie_genres (
    movie_id INTEGER,
    genre_id INTEGER,
    PRIMARY KEY (movie_id, genre_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE CASCADE
);

-- People table (actors, directors, crew)
CREATE TABLE people (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    profile_path VARCHAR(255),
    biography TEXT,
    birthday DATE,
    place_of_birth VARCHAR(255),
    popularity DECIMAL(10, 2)
);

-- Cast table (actors in movies)
CREATE TABLE cast (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER,
    person_id INTEGER,
    character_name VARCHAR(255),
    cast_order INTEGER,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
);

-- Crew table (directors, writers, etc.)
CREATE TABLE crew (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER,
    person_id INTEGER,
    job VARCHAR(100),
    department VARCHAR(100),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
);

-- Production companies
CREATE TABLE production_companies (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    logo_path VARCHAR(255),
    origin_country VARCHAR(10)
);

-- Movie-Production Company junction
CREATE TABLE movie_companies (
    movie_id INTEGER,
    company_id INTEGER,
    PRIMARY KEY (movie_id, company_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (company_id) REFERENCES production_companies(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX idx_movies_release_date ON movies(release_date);
CREATE INDEX idx_movies_vote_average ON movies(vote_average);
CREATE INDEX idx_movies_popularity ON movies(popularity);
CREATE INDEX idx_cast_movie_id ON cast(movie_id);
CREATE INDEX idx_cast_person_id ON cast(person_id);
CREATE INDEX idx_crew_movie_id ON crew(movie_id);