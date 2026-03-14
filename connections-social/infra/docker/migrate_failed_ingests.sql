-- Migration: Add failed_ingests dead-letter table
--
-- WHY THIS TABLE:
--   When an image fails to process (corrupted file, ML inference error,
--   DB write failure), the failure is currently only logged.  There is no
--   persistent record of what failed, why, or how many times it was retried.
--
--   This table is the dead-letter queue for the ingestion pipeline.
--   Failed events are stored here so they can be:
--     - Inspected via GET /admin/report (failure rate, error breakdown)
--     - Retried via POST /admin/retry-failed
--     - Audited for patterns (e.g. "all failures on a specific model version")
--
--   Tesla analog: a telemetry pipeline quarantine bucket where frames that
--   fail cloud-side processing are stored for investigation, rather than
--   silently dropped.
--
-- Apply:
--   psql $DATABASE_URL -f infra/docker/migrate_failed_ingests.sql

CREATE TABLE IF NOT EXISTS failed_ingests (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename        TEXT NOT NULL,
    error_stage     TEXT NOT NULL,       -- Which pipeline stage failed
    error_message   TEXT NOT NULL,       -- Exception message or description
    model_version   TEXT NOT NULL DEFAULT 'buffalo_l',
    retry_count     INT  NOT NULL DEFAULT 0,
    max_retries     INT  NOT NULL DEFAULT 3,
    last_attempted  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE once successfully retried
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_failed_ingests_filename    ON failed_ingests(filename);
CREATE INDEX IF NOT EXISTS idx_failed_ingests_resolved    ON failed_ingests(resolved) WHERE NOT resolved;
CREATE INDEX IF NOT EXISTS idx_failed_ingests_created     ON failed_ingests(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_failed_ingests_stage       ON failed_ingests(error_stage);
