"""
Database connection utilities.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from . import config


def get_connection():
    """Create a new database connection."""
    return psycopg2.connect(config.DATABASE_URL)


@contextmanager
def get_cursor(dict_cursor: bool = True):
    """Context manager for database cursor."""
    conn = get_connection()
    cursor_factory = RealDictCursor if dict_cursor else None
    try:
        cursor = conn.cursor(cursor_factory=cursor_factory)
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
