-- C05 managed-storage transaction and recovery metadata.
CREATE TABLE managed_storage_records (
    file_id TEXT PRIMARY KEY REFERENCES file_objects(id) ON DELETE RESTRICT,
    layout_version INTEGER NOT NULL CHECK (layout_version = 1),
    storage_key TEXT NOT NULL COLLATE NOCASE UNIQUE,
    storage_reference TEXT NOT NULL COLLATE NOCASE UNIQUE,
    staging_reference TEXT NOT NULL COLLATE NOCASE UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN (
            'prepared', 'finalized', 'verified', 'mismatch',
            'reference_unavailable', 'error'
        )
    ),
    source_created_ns INTEGER CHECK (source_created_ns IS NULL OR source_created_ns >= 0),
    source_modified_ns INTEGER NOT NULL CHECK (source_modified_ns >= 0),
    finalized_at TEXT,
    verified_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_managed_storage_state
    ON managed_storage_records(state, updated_at);

CREATE TRIGGER managed_storage_identity_no_update
BEFORE UPDATE OF
    file_id, layout_version, storage_key, storage_reference,
    staging_reference, source_created_ns, source_modified_ns
ON managed_storage_records
BEGIN
    SELECT RAISE(ABORT, 'managed storage identity is immutable');
END;

CREATE TRIGGER managed_original_metadata_no_update
BEFORE UPDATE OF original_name, source_relative_path, storage_reference, size_bytes, sha256
ON file_objects
WHEN EXISTS (
    SELECT 1
    FROM managed_storage_records
    WHERE file_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'managed original metadata is immutable');
END;

CREATE TRIGGER verified_original_no_delete
BEFORE DELETE ON file_objects
WHEN EXISTS (
    SELECT 1
    FROM managed_storage_records
    WHERE file_id = OLD.id AND state = 'verified'
)
BEGIN
    SELECT RAISE(ABORT, 'verified original is immutable');
END;

CREATE TRIGGER verified_storage_record_no_delete
BEFORE DELETE ON managed_storage_records
WHEN OLD.state = 'verified'
BEGIN
    SELECT RAISE(ABORT, 'verified storage record is immutable');
END;
