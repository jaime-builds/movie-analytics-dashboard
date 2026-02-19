"""
Verification Script for Movie Analytics Dashboard
Run this to check if movie_genres table and backdrop_path exist
"""

import sys

sys.path.append(".")

from sqlalchemy import inspect, text

from src.models import Genre, Movie, Session


def check_movie_genres_table():
    """Check if movie_genres junction table exists"""
    print("\n" + "=" * 60)
    print("CHECKING MOVIE_GENRES TABLE")
    print("=" * 60)

    session = Session()
    inspector = inspect(session.bind)
    tables = inspector.get_table_names()

    if "movie_genres" in tables:
        print("✅ movie_genres table EXISTS")

        # Check the structure
        columns = inspector.get_columns("movie_genres")
        print("\n📋 Table structure:")
        for col in columns:
            print(f"   - {col['name']}: {col['type']}")

        # Check if there's data
        result = session.execute(text("SELECT COUNT(*) FROM movie_genres")).scalar()
        print(f"\n📊 Total rows in movie_genres: {result:,}")

        if result > 0:
            print("✅ movie_genres has data")
        else:
            print("⚠️  WARNING: movie_genres table is EMPTY")
            print("   You need to populate this table with movie-genre relationships")

        return True
    else:
        print("❌ movie_genres table DOES NOT EXIST")
        print("\n🔧 Available tables:")
        for table in tables:
            print(f"   - {table}")
        print("\n⚠️  You need to create the movie_genres junction table!")
        return False

    session.close()


def check_backdrop_path():
    """Check if movies have backdrop_path field and data"""
    print("\n" + "=" * 60)
    print("CHECKING BACKDROP_PATH FIELD")
    print("=" * 60)

    session = Session()

    # Check if the column exists
    inspector = inspect(session.bind)
    columns = inspector.get_columns("movies")
    column_names = [col["name"] for col in columns]

    if "backdrop_path" in column_names:
        print("✅ backdrop_path column EXISTS in movies table")

        # Check how many movies have backdrop_path
        total_movies = session.query(Movie).count()
        movies_with_backdrop = (
            session.query(Movie)
            .filter(Movie.backdrop_path.isnot(None), Movie.backdrop_path != "")
            .count()
        )

        print(f"\n📊 Movie Statistics:")
        print(f"   Total movies: {total_movies:,}")
        print(f"   Movies with backdrop: {movies_with_backdrop:,}")
        print(f"   Movies without backdrop: {total_movies - movies_with_backdrop:,}")
        print(f"   Percentage with backdrop: {(movies_with_backdrop/total_movies*100):.1f}%")

        if movies_with_backdrop > 0:
            print("\n✅ Some movies have backdrop images")

            # Show a few examples
            print("\n🎬 Sample movies with backdrops:")
            sample_movies = (
                session.query(Movie).filter(Movie.backdrop_path.isnot(None)).limit(5).all()
            )

            for movie in sample_movies:
                print(
                    f"   - {movie.title} ({movie.release_date.year if movie.release_date else 'N/A'})"
                )
                print(f"     Backdrop: {movie.backdrop_path}")
        else:
            print("\n⚠️  WARNING: NO movies have backdrop images")
            print("   The backdrop banner feature won't display without this data")

        return movies_with_backdrop > 0

    else:
        print("❌ backdrop_path column DOES NOT EXIST in movies table")
        print("\n📋 Available columns in movies table:")
        for col in columns:
            print(f"   - {col['name']}")
        print("\n⚠️  You need to add backdrop_path column to movies table!")
        return False

    session.close()


def check_models_import():
    """Check if movie_genres is properly imported in models.py"""
    print("\n" + "=" * 60)
    print("CHECKING MODELS.PY IMPORTS")
    print("=" * 60)

    # Try both possible names
    try:
        from src.models import movie_genres_table

        print("✅ movie_genres_table is IMPORTED in models.py")
        print(f"   Type: {type(movie_genres_table)}")
        return True
    except ImportError:
        pass

    try:
        from src.models import movie_genres

        print("✅ movie_genres is IMPORTED in models.py")
        print(f"   Type: {type(movie_genres)}")
        return True
    except ImportError:
        print("❌ movie_genres (or movie_genres_table) is NOT IMPORTED in models.py")
        print("\n🔧 You need to add this to your models.py:")
        print(
            """
# Junction table for many-to-many relationship
movie_genres_table = Table(
    'movie_genres',
    Base.metadata,
    Column('movie_id', Integer, ForeignKey('movies.id'), primary_key=True),
    Column('genre_id', Integer, ForeignKey('genres.id'), primary_key=True)
)
"""
        )
        return False


def main():
    """Run all checks"""
    print("\n" + "=" * 60)
    print("🎬 MOVIE ANALYTICS DASHBOARD - VERIFICATION SCRIPT")
    print("=" * 60)

    try:
        # Check 1: movie_genres import
        import_check = check_models_import()

        # Check 2: movie_genres table
        table_check = check_movie_genres_table()

        # Check 3: backdrop_path
        backdrop_check = check_backdrop_path()

        # Summary
        print("\n" + "=" * 60)
        print("📊 VERIFICATION SUMMARY")
        print("=" * 60)

        checks = [
            ("movie_genres import", import_check),
            ("movie_genres table", table_check),
            ("backdrop_path data", backdrop_check),
        ]

        for check_name, passed in checks:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status} - {check_name}")

        all_passed = all(result for _, result in checks)

        print("\n" + "=" * 60)
        if all_passed:
            print("🎉 ALL CHECKS PASSED!")
            print("Your database is ready for all 5 new features!")
        else:
            print("⚠️  SOME CHECKS FAILED")
            print("Please fix the issues above before using the new features.")
        print("=" * 60 + "\n")

        return all_passed

    except Exception as e:
        print(f"\n❌ ERROR running verification: {e}")
        print(f"   Type: {type(e).__name__}")
        import traceback

        print("\n🔍 Full traceback:")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
