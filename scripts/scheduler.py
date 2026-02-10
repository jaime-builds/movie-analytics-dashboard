"""
Data Sync Scheduler

Schedules automatic TMDB data synchronization tasks.
Runs daily at 2 AM to update movie data.

Usage:
    python scripts/scheduler.py

Or as a background service:
    nohup python scripts/scheduler.py &
"""

import logging
import sys
import time
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import schedule

from scripts.sync_tmdb_data import TMDBDataSyncer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/scheduler.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def daily_full_sync():
    """Run full daily sync of 5000 movies"""
    logger.info("=" * 60)
    logger.info("Starting scheduled daily full sync")
    logger.info("=" * 60)

    syncer = TMDBDataSyncer(limit=5000, update_existing=False)

    try:
        syncer.sync_genres()
        syncer.sync_popular_movies()

        logger.info("Daily sync completed successfully")
        logger.info(f"Statistics: {syncer.stats}")

    except Exception as e:
        logger.error(f"Daily sync failed: {e}")
    finally:
        syncer.close()


def hourly_recent_updates():
    """Update recently modified movies every hour"""
    logger.info("Starting hourly recent updates")

    syncer = TMDBDataSyncer(limit=5000, update_existing=True)

    try:
        syncer.sync_recent_updates(days=1)
        logger.info("Hourly updates completed")

    except Exception as e:
        logger.error(f"Hourly updates failed: {e}")
    finally:
        syncer.close()


def setup_schedule():
    """Configure sync schedule"""
    # Daily full sync at 2 AM
    schedule.every().day.at("02:00").do(daily_full_sync)

    # Hourly recent updates
    schedule.every().hour.do(hourly_recent_updates)

    logger.info("Scheduler configured:")
    logger.info("  - Daily full sync: 2:00 AM")
    logger.info("  - Hourly updates: Every hour")


def main():
    """Main scheduler loop"""
    logger.info("Starting TMDB Data Sync Scheduler")

    # Ensure logs directory exists
    Path("logs").mkdir(exist_ok=True)

    # Setup schedule
    setup_schedule()

    # Run initial sync immediately
    logger.info("Running initial sync...")
    try:
        daily_full_sync()
    except Exception as e:
        logger.error(f"Initial sync failed: {e}")

    # Main loop
    logger.info("Entering scheduler loop...")
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
