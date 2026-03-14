-- ============================================================================
-- Migration: Add pgvector ANN search to person_profiles
-- ============================================================================
--
-- WHY THIS MIGRATION:
--   The current matching path loads all embeddings into Python RAM and runs
--   O(n_profiles) cosine similarity operations per detected face.  At small
--   scale (< 500 profiles) this is fine — 500 × 512 float32 = ~1MB, ~0.2ms.
--   At 10 000 profiles it becomes ~20MB and ~4ms per face; at 100 000 profiles
--   it exceeds practical limits for a synchronous API request.
--
--   pgvector's IVFFlat index reduces matching to O(sqrt(n)) approximate
--   nearest neighbor search entirely inside PostgreSQL, eliminating the Python
--   loop and the per-request memory allocation.
--
-- PREREQUISITES:
--   1. PostgreSQL must have the pgvector extension installed:
--        docker image: ankane/pgvector  (drop-in replacement for postgres)
--        or: apt install postgresql-16-pgvector
--   2. Run this script against the running database:
--        psql $DATABASE_URL -f infra/docker/migrate_pgvector.sql
--   3. After this script, populate embedding_vec from the BYTEA column:
--        python scripts/migrate_embeddings.py
--   4. Then create the index (IVFFlat requires data to exist first):
--        psql $DATABASE_URL -c "SELECT build_ivfflat_index();"
--      or run the index creation section below manually.
--
-- ROLLING MIGRATION SAFETY:
--   The new embedding_vec column is added alongside the existing BYTEA column.
--   The application continues reading from BYTEA until you flip the feature
--   flag (USE_PGVECTOR=true).  Both columns coexist until verified and old
--   column can be dropped.  This is a safe, zero-downtime schema change.

-- Enable pgvector extension (idempotent)
CREATE EXTENSION IF NOT EXISTS vector;

-- Add the new vector column alongside existing BYTEA column.
-- NULL until populated by migrate_embeddings.py.
ALTER TABLE person_profiles
    ADD COLUMN IF NOT EXISTS embedding_vec vector(512);

-- ─────────────────────────────────────────────────────────────────────────────
-- AFTER running migrate_embeddings.py to populate embedding_vec, create index:
-- ─────────────────────────────────────────────────────────────────────────────

-- IVFFlat index for cosine similarity ANN search.
--
-- Parameter guidance:
--   lists = sqrt(n_rows) is the standard starting point.
--   For 100 profiles: lists=10.  For 10K profiles: lists=100.  For 1M: lists=1000.
--   Higher lists → better recall but slower build and more memory.
--
--   At query time, set ivfflat.probes (default=1) higher for better recall:
--     SET ivfflat.probes = 10;  -- searches 10 lists instead of 1
--
-- vector_cosine_ops: uses 1 - cosine_similarity as the distance metric.
-- <=> operator returns this distance; lower = more similar.
-- To convert back: similarity = 1 - distance.

CREATE INDEX IF NOT EXISTS idx_person_profiles_embedding_ivfflat
    ON person_profiles
    USING ivfflat (embedding_vec vector_cosine_ops)
    WITH (lists = 100);

-- Alternative: HNSW (better recall and query speed, higher build cost + memory).
-- Prefer HNSW when recall > throughput, IVFFlat when throughput > recall.
--
-- CREATE INDEX IF NOT EXISTS idx_person_profiles_embedding_hnsw
--     ON person_profiles
--     USING hnsw (embedding_vec vector_cosine_ops)
--     WITH (m = 16, ef_construction = 64);

-- ─────────────────────────────────────────────────────────────────────────────
-- Example ANN query (run after migration + index creation):
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Find top-5 most similar profiles to a query embedding:
--
--   SET ivfflat.probes = 10;
--   SELECT p.name,
--          1 - (pp.embedding_vec <=> '[0.1, 0.2, ...]'::vector) AS cosine_similarity
--   FROM person_profiles pp
--   JOIN persons p ON pp.person_id = p.id
--   WHERE pp.embedding_vec IS NOT NULL
--   ORDER BY pp.embedding_vec <=> '[0.1, 0.2, ...]'::vector
--   LIMIT 5;
--
-- vs current brute-force Python path which does:
--   SELECT p.id, p.name, pp.embedding FROM person_profiles pp JOIN persons p ...
--   then: [cosine_sim(query, e) for e in embeddings]  # O(n) Python loop
