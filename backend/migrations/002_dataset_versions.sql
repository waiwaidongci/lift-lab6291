-- 002_dataset_versions.sql
-- Dataset versioning + page uploads. Apply after 001 on an existing database.
-- New environments create these objects from SQLAlchemy metadata on boot;
-- this script documents the reviewed upgrade for existing installations.

CREATE TABLE IF NOT EXISTS dataset_versions (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id),
    version INTEGER NOT NULL,
    checksum VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    description VARCHAR NOT NULL DEFAULT '',
    rows_received INTEGER NOT NULL DEFAULT 0,
    rows_unique INTEGER NOT NULL DEFAULT 0,
    duplicates_removed INTEGER NOT NULL DEFAULT 0,
    created_by VARCHAR NOT NULL DEFAULT '',
    created_at VARCHAR NOT NULL DEFAULT '',
    CONSTRAINT dataset_versions_dataset_version_key UNIQUE (dataset_id, version),
    CONSTRAINT dataset_versions_dataset_checksum_key UNIQUE (dataset_id, checksum)
);

CREATE TABLE IF NOT EXISTS dataset_imports (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id),
    version_id INTEGER REFERENCES dataset_versions(id),
    status VARCHAR NOT NULL DEFAULT 'rejected',
    filename VARCHAR NOT NULL DEFAULT '',
    checksum VARCHAR NOT NULL DEFAULT '',
    rows_received INTEGER NOT NULL DEFAULT 0,
    rows_unique INTEGER NOT NULL DEFAULT 0,
    duplicates_removed INTEGER NOT NULL DEFAULT 0,
    errors JSON NOT NULL DEFAULT '[]',
    reason VARCHAR NOT NULL DEFAULT '',
    actor VARCHAR NOT NULL DEFAULT '',
    created_at VARCHAR NOT NULL DEFAULT ''
);

ALTER TABLE datasets ADD COLUMN IF NOT EXISTS created_at VARCHAR NOT NULL DEFAULT '';
ALTER TABLE observations ADD COLUMN IF NOT EXISTS dataset_version_id INTEGER REFERENCES dataset_versions(id);
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS dataset_version_id INTEGER REFERENCES dataset_versions(id);
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS dataset_version_id INTEGER REFERENCES dataset_versions(id);

-- Old uniqueness was one row per subject per dataset; versions need it per snapshot.
ALTER TABLE observations DROP CONSTRAINT IF EXISTS observations_dataset_id_subject_key;
CREATE UNIQUE INDEX IF NOT EXISTS observations_version_subject_key
    ON observations (dataset_version_id, subject);
CREATE INDEX IF NOT EXISTS observations_version_idx ON observations (dataset_version_id);

-- Existing observations become version 1 of their dataset (run the app boot
-- backfill or the equivalent UPDATE below, then add the NOT NULL constraint).
-- UPDATE datasets d SET checksum = COALESCE(NULLIF(d.checksum,''), v.checksum) FROM ...;
