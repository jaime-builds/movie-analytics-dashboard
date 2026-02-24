"""
Complete Database Migration Script
Adds all missing tables and columns for ratings, reviews, and people.popularity
"""

import sqlite3


def migrate_database():
    # Connect directly to movies.db
    conn = sqlite3.connect("movies.db")
    cursor = conn.cursor()

    try:
        print("Starting database migration...\n")

        # 1. Add popularity column to people table (if missing)
        print("1. Checking 'people' table...")
        cursor.execute("PRAGMA table_info(people)")
        columns = [column[1] for column in cursor.fetchall()]

        if "popularity" not in columns:
            print("   Adding 'popularity' column to 'people' table...")
            cursor.execute("ALTER TABLE people ADD COLUMN popularity DECIMAL(10, 2)")
            conn.commit()
            print("   ✓ Column added successfully!")
        else:
            print("   ✓ Column 'popularity' already exists")

        # 2. Create users table (if not exists)
        print("\n2. Checking 'users' table...")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(128) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.commit()
        print("   ✓ 'users' table created/verified")

        # 3. Create ratings table (if not exists)
        print("\n3. Checking 'ratings' table...")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                movie_id INTEGER NOT NULL,
                rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (movie_id) REFERENCES movies(id),
                UNIQUE(user_id, movie_id)
            )
        """
        )
        conn.commit()
        print("   ✓ 'ratings' table created/verified")

        # 4. Create reviews table (if not exists)
        print("\n4. Checking 'reviews' table...")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                movie_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (movie_id) REFERENCES movies(id)
            )
        """
        )
        conn.commit()
        print("   ✓ 'reviews' table created/verified")

        # 5. Create indexes for performance
        print("\n5. Creating indexes...")

        indexes = [
            # Ratings
            (
                "idx_ratings_user_movie",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ratings_user_movie ON ratings(user_id, movie_id)",
            ),
            (
                "idx_ratings_movie",
                "CREATE INDEX IF NOT EXISTS idx_ratings_movie ON ratings(movie_id)",
            ),
            # Reviews
            (
                "idx_reviews_movie",
                "CREATE INDEX IF NOT EXISTS idx_reviews_movie ON reviews(movie_id)",
            ),
            (
                "idx_reviews_user",
                "CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id)",
            ),
            # Movies - vote_count used in almost every filtered query
            (
                "idx_movies_vote_count",
                "CREATE INDEX IF NOT EXISTS idx_movies_vote_count ON movies(vote_count)",
            ),
            # Movies - title for search ordering
            (
                "idx_movies_title",
                "CREATE INDEX IF NOT EXISTS idx_movies_title ON movies(title)",
            ),
            # Crew - person_id for director/filmography lookups
            (
                "idx_crew_person_id",
                "CREATE INDEX IF NOT EXISTS idx_crew_person_id ON crew(person_id)",
            ),
            # Crew - composite for director-specific queries (person_id + job)
            (
                "idx_crew_person_job",
                "CREATE INDEX IF NOT EXISTS idx_crew_person_job ON crew(person_id, job)",
            ),
            # movie_genres - genre_id for genre filter on movies page
            (
                "idx_movie_genres_genre_id",
                "CREATE INDEX IF NOT EXISTS idx_movie_genres_genre_id ON movie_genres(genre_id)",
            ),
        ]

        for idx_name, idx_sql in indexes:
            cursor.execute(idx_sql)
            print(f"   ✓ Index '{idx_name}' created/verified")

        conn.commit()

        # 6. Verify everything
        print("\n6. Verifying migration...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [table[0] for table in cursor.fetchall()]

        required_tables = [
            "users",
            "movies",
            "genres",
            "people",
            "cast",
            "crew",
            "production_companies",
            "ratings",
            "reviews",
        ]

        missing = [t for t in required_tables if t not in tables]
        if missing:
            print(f"   ⚠ Warning: Missing tables: {missing}")
        else:
            print("   ✓ All required tables exist")

        print("\n" + "=" * 60)
        print("✓ Migration completed successfully!")
        print("=" * 60)
        print("\nYou can now restart your Flask app:")
        print("  python -m src.app")

    except Exception as e:
        print(f"\n✗ Error during migration: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

    return True


if __name__ == "__main__":
    success = migrate_database()
    exit(0 if success else 1)
