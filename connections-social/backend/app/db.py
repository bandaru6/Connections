"""Database connection utilities with connection pooling.

Uses psycopg2.pool.ThreadedConnectionPool so that concurrent requests
share a fixed set of database connections instead of opening a new TCP
connection per request.  A new connection per request is the single
biggest scalability bottleneck in a synchronous WSGI/ASGI stack:
  - Each new connection costs ~5-10ms of TCP + auth handshake.
  - Under burst load you exhaust PostgreSQL's max_connections limit.
  - The pool turns "connection establishment" into "connection checkout"
    (~0.1ms), and queues requests when all connections are busy rather
    than crashing.

Pool sizing rationale (configurable via env):
  DB_POOL_MIN_CONN=2   — keep 2 warm connections even at idle
  DB_POOL_MAX_CONN=10  — cap at 10; rule of thumb is (2 * CPU cores) + spindles
"""

import logging
import threading
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

from app.config import DATABASE_URL, DB_POOL_MIN_CONN, DB_POOL_MAX_CONN

logger = logging.getLogger(__name__)

# Module-level pool singleton. Initialized lazily on first use so the
# import itself does not require a live database (important for tests).
_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Return the shared connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:  # double-checked locking
                logger.info(
                    "Initializing PostgreSQL connection pool "
                    f"(min={DB_POOL_MIN_CONN}, max={DB_POOL_MAX_CONN})"
                )
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=DB_POOL_MIN_CONN,
                    maxconn=DB_POOL_MAX_CONN,
                    dsn=DATABASE_URL,
                )
    return _pool


def get_pool_status() -> dict:
    """Return current pool utilization for observability endpoints."""
    if _pool is None:
        return {"initialized": False, "min": DB_POOL_MIN_CONN, "max": DB_POOL_MAX_CONN}
    # psycopg2 does not expose a public count of checked-out connections,
    # but _used and _pool are internal dicts we can safely inspect.
    try:
        used = len(_pool._used)       # connections currently checked out
        available = len(_pool._pool)  # connections available in the pool
    except AttributeError:
        used = -1
        available = -1
    return {
        "initialized": True,
        "min": DB_POOL_MIN_CONN,
        "max": DB_POOL_MAX_CONN,
        "checked_out": used,
        "available": available,
    }


@contextmanager
def get_cursor(dict_cursor: bool = True) -> Generator:
    """Context manager that checks out a pooled connection and yields a cursor.

    Commits on success, rolls back on exception, and always returns the
    connection to the pool — even if an error occurs.  Callers never
    interact with the connection directly.
    """
    pool = _get_pool()
    conn = pool.getconn()
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
        pool.putconn(conn)


def check_db_connection() -> bool:
    """Check if the database is reachable via the pool."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False


def close_pool() -> None:
    """Gracefully close all pool connections (call at shutdown)."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL connection pool closed")
