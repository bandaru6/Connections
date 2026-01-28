#!/usr/bin/env python3
"""
Seed Demo Data - Creates a sample social graph for demonstration.

This script inserts deterministic, fake data into the database to demonstrate
the social graph functionality without requiring real photos or ML processing.

Usage:
    python scripts/seed_demo.py
    # or via docker compose:
    docker compose --profile seed up seeder
"""

import os
import sys
import uuid
import logging
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Database connection
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://connections:connections@localhost:5433/connections"
)

# Demo data: fictional persons for the social graph
DEMO_PERSONS = [
    "Alice Chen",
    "Bob Martinez",
    "Carol Williams",
    "David Kim",
    "Eva Schmidt",
    "Frank Johnson",
    "Grace Lee",
    "Henry Brown",
    "Iris Patel",
    "Jack Wilson",
]

# Demo edges: connections between persons (weight = number of co-appearances)
# Format: (person_a, person_b, weight)
DEMO_EDGES = [
    ("Alice Chen", "Bob Martinez", 5),
    ("Alice Chen", "Carol Williams", 3),
    ("Alice Chen", "David Kim", 2),
    ("Bob Martinez", "Carol Williams", 4),
    ("Bob Martinez", "Eva Schmidt", 2),
    ("Carol Williams", "Frank Johnson", 3),
    ("David Kim", "Grace Lee", 4),
    ("David Kim", "Henry Brown", 2),
    ("Eva Schmidt", "Frank Johnson", 1),
    ("Eva Schmidt", "Iris Patel", 3),
    ("Frank Johnson", "Grace Lee", 2),
    ("Grace Lee", "Henry Brown", 5),
    ("Grace Lee", "Iris Patel", 2),
    ("Henry Brown", "Jack Wilson", 3),
    ("Iris Patel", "Jack Wilson", 4),
    ("Alice Chen", "Jack Wilson", 1),
    ("Bob Martinez", "Henry Brown", 2),
    ("Carol Williams", "Iris Patel", 1),
]


def get_connection():
    """Get database connection."""
    return psycopg2.connect(DATABASE_URL)


def wait_for_db(max_retries: int = 30, delay: float = 2.0):
    """Wait for database to be ready."""
    import time
    for attempt in range(max_retries):
        try:
            conn = get_connection()
            conn.close()
            logger.info("Database is ready")
            return True
        except psycopg2.OperationalError as e:
            if attempt < max_retries - 1:
                logger.info(f"Waiting for database... (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                logger.error(f"Database not ready after {max_retries} attempts: {e}")
                return False
    return False


def clear_demo_data(cur):
    """Clear existing demo data (edges, faces, uploads) but keep real profiles if any."""
    logger.info("Clearing existing demo data...")

    # Clear in order due to foreign key constraints
    cur.execute("DELETE FROM edge_evidence")
    cur.execute("DELETE FROM edges")
    cur.execute("DELETE FROM faces")
    cur.execute("DELETE FROM uploads")
    cur.execute("DELETE FROM processed_images")

    # Only delete persons that don't have real profile embeddings
    cur.execute("""
        DELETE FROM persons
        WHERE id NOT IN (SELECT DISTINCT person_id FROM person_profiles)
    """)

    logger.info("Demo data cleared")


def seed_persons(cur) -> dict:
    """Insert demo persons and return name->id mapping."""
    logger.info(f"Seeding {len(DEMO_PERSONS)} demo persons...")

    person_ids = {}
    for name in DEMO_PERSONS:
        # Use deterministic UUID based on name for idempotency
        person_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"demo.{name}"))

        cur.execute(
            """
            INSERT INTO persons (id, name, created_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (person_uuid, name, datetime.utcnow())
        )
        result = cur.fetchone()
        person_ids[name] = str(result['id'])
        logger.info(f"  Created: {name}")

    return person_ids


def seed_edges(cur, person_ids: dict):
    """Insert demo edges between persons."""
    logger.info(f"Seeding {len(DEMO_EDGES)} demo edges...")

    for person_a, person_b, weight in DEMO_EDGES:
        id_a = person_ids.get(person_a)
        id_b = person_ids.get(person_b)

        if not id_a or not id_b:
            logger.warning(f"  Skipping edge {person_a} - {person_b}: person not found")
            continue

        # Ensure ordered pair (id_a < id_b)
        if id_a > id_b:
            id_a, id_b = id_b, id_a

        cur.execute(
            """
            INSERT INTO edges (person_a_id, person_b_id, weight, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (person_a_id, person_b_id)
            DO UPDATE SET weight = EXCLUDED.weight, updated_at = EXCLUDED.updated_at
            """,
            (id_a, id_b, weight, datetime.utcnow())
        )
        logger.info(f"  Edge: {person_a} <-> {person_b} (weight={weight})")


def print_summary(cur):
    """Print summary of seeded data."""
    cur.execute("SELECT COUNT(*) as count FROM persons")
    persons = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) as count FROM edges")
    edges = cur.fetchone()['count']

    cur.execute("SELECT SUM(weight) as total FROM edges")
    total_weight = cur.fetchone()['total'] or 0

    logger.info("")
    logger.info("=" * 50)
    logger.info("Demo data seeded successfully!")
    logger.info("=" * 50)
    logger.info(f"  Persons: {persons}")
    logger.info(f"  Edges: {edges}")
    logger.info(f"  Total co-appearances: {total_weight}")
    logger.info("")
    logger.info("Open http://localhost:3000 to explore the graph")
    logger.info("API docs at http://localhost:8000/docs")
    logger.info("=" * 50)


def main():
    """Main entry point."""
    logger.info("Starting demo data seeding...")

    # Wait for database
    if not wait_for_db():
        sys.exit(1)

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Clear and seed
        clear_demo_data(cur)
        person_ids = seed_persons(cur)
        seed_edges(cur, person_ids)

        # Commit
        conn.commit()

        # Print summary
        print_summary(cur)

        cur.close()
        conn.close()

        logger.info("Seeding complete!")
        return 0

    except Exception as e:
        logger.error(f"Seeding failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
