#!/usr/bin/env python3
"""Populate person_profiles.embedding_vec from the existing BYTEA column.

Run AFTER applying infra/docker/migrate_pgvector.sql (which adds the vector
column and requires pgvector extension).

Usage:
    python scripts/migrate_embeddings.py
    DATABASE_URL=postgresql://... python scripts/migrate_embeddings.py

The BYTEA column stores embeddings as little-endian float32[512] packed with
Python's struct.pack.  This script reads each row, unpacks the bytes, and
writes the result as a pgvector vector(512) value.

Progress is printed every 10 rows.  The script is idempotent — rows that
already have embedding_vec set are skipped.
"""

import os
import struct
import sys

import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://connections:connections@localhost:5433/connections"
)
EMBEDDING_DIM = 512


def bytea_to_pgvector(data: bytes) -> str:
    """Convert packed float32 bytes → pgvector text literal '[f1, f2, ...]'."""
    count = len(data) // 4
    floats = struct.unpack(f"{count}f", data)
    return "[" + ",".join(f"{v:.8f}" for v in floats) + "]"


def main():
    print(f"Connecting to {DATABASE_URL.split('@')[-1]} ...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Check pgvector is available
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            if not cur.fetchone():
                print("ERROR: pgvector extension not found.")
                print("       Run: psql $DATABASE_URL -f infra/docker/migrate_pgvector.sql")
                sys.exit(1)

            # Check the column exists
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='person_profiles' AND column_name='embedding_vec'
            """)
            if not cur.fetchone():
                print("ERROR: embedding_vec column not found.")
                print("       Run: psql $DATABASE_URL -f infra/docker/migrate_pgvector.sql")
                sys.exit(1)

            # Fetch rows that still need migration
            cur.execute("""
                SELECT id, embedding
                FROM person_profiles
                WHERE embedding_vec IS NULL AND embedding IS NOT NULL
            """)
            rows = cur.fetchall()
            total = len(rows)

            if total == 0:
                print("Nothing to migrate — all rows already have embedding_vec set.")
                return

            print(f"Migrating {total} embedding(s) ...")

            with conn.cursor() as update_cur:
                for i, row in enumerate(rows, start=1):
                    vec_str = bytea_to_pgvector(bytes(row["embedding"]))
                    update_cur.execute(
                        "UPDATE person_profiles SET embedding_vec = %s::vector WHERE id = %s",
                        (vec_str, row["id"])
                    )
                    if i % 10 == 0 or i == total:
                        print(f"  {i}/{total} rows migrated")

            conn.commit()
            print(f"Done. {total} embedding(s) migrated successfully.")
            print()
            print("Next step: verify the index exists or create it:")
            print("  psql $DATABASE_URL -c '\\d person_profiles'")
            print("  -- Look for idx_person_profiles_embedding_ivfflat")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
