"""Database connection utilities."""

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extras import RealDictCursor

from app.config import DATABASE_URL

logger = logging.getLogger(__name__)


def get_connection():
    """Create a new database connection."""
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def get_cursor(dict_cursor: bool = True) -> Generator:
    """Context manager for database cursor with automatic commit/rollback."""
    conn = get_connection()
    cursor_factory = RealDictCursor if dict_cursor else None
    try:
        cursor = conn.cursor(cursor_factory=cursor_factory)
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def check_db_connection() -> bool:
    """Check if database is reachable."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False
