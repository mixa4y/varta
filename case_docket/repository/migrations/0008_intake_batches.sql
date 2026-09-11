-- C06 authoritative file/folder/ZIP intake inventory and status history.
CREATE TABLE intake_contexts (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (
        status IN ('enumerating', 'processing', 'succeeded', 'partial', 'failed')
    ),
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK (
        (status IN ('succeeded', 'partial', 'failed') AND completed_at IS NOT NULL)
        OR
        (status IN ('enumerating', 'processing') AND completed_at IS NULL)
    )
);

CREATE TABLE import_batches (
    id TEXT PRIMARY KEY,
    intake_context_id TEXT NOT NULL UNIQUE
        REFERENCES intake_contexts(id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL COLLATE BINARY UNIQUE,
    request_fingerprint TEXT NOT NULL CHECK (length(request_fingerprint) = 64),
    source_uri TEXT NOT NULL,
    requested_kind TEXT NOT NULL CHECK (requested_kind = 'auto'),
    detected_kind TEXT CHECK (
        detected_kind IS NULL OR detected_kind IN ('file', 'folder', 'zip')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('enumerating', 'processing', 'succeeded', 'partial', 'failed')
    ),
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK (
        (status IN ('succeeded', 'partial', 'failed') AND completed_at IS NOT NULL)
        OR
        (status IN ('enumerating', 'processing') AND completed_at IS NULL)
    )
);

CREATE TABLE intake_entries (
    id TEXT PRIMARY KEY,
    import_batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    source_uri TEXT NOT NULL,
    source_relative_path TEXT NOT NULL,
    literal_name TEXT NOT NULL,
    entry_kind TEXT NOT NULL CHECK (
        entry_kind IN ('file', 'zip_member', 'directory', 'archive', 'special')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('discovered', 'accepted', 'duplicate', 'failed', 'skipped')
    ),
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    source_created_at TEXT,
    source_modified_at TEXT,
    extension TEXT,
    media_type TEXT,
    type_hint TEXT,
    file_id TEXT UNIQUE REFERENCES file_objects(id) ON DELETE RESTRICT,
    duplicate_of_file_ids_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(duplicate_of_file_ids_json))
        CHECK (json_type(duplicate_of_file_ids_json) = 'array'),
    warning_code TEXT,
    warning_message TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (import_batch_id, ordinal),
    CHECK (
        (status IN ('accepted', 'duplicate') AND file_id IS NOT NULL)
        OR
        (status IN ('discovered', 'failed', 'skipped') AND file_id IS NULL)
    ),
    CHECK (
        (status = 'duplicate' AND json_array_length(duplicate_of_file_ids_json) > 0)
        OR
        (status <> 'duplicate' AND json_array_length(duplicate_of_file_ids_json) = 0)
    ),
    CHECK (
        (status IN ('failed', 'skipped') AND error_code IS NOT NULL)
        OR
        (status NOT IN ('failed', 'skipped') AND error_code IS NULL)
    )
);

CREATE TABLE import_batch_status_history (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    import_batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    from_status TEXT CHECK (
        from_status IS NULL
        OR from_status IN ('enumerating', 'processing', 'succeeded', 'partial', 'failed')
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN ('enumerating', 'processing', 'succeeded', 'partial', 'failed')
    ),
    error_code TEXT,
    error_message TEXT,
    occurred_at TEXT NOT NULL
);

CREATE TABLE intake_entry_status_history (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_entry_id TEXT NOT NULL REFERENCES intake_entries(id) ON DELETE RESTRICT,
    from_status TEXT CHECK (
        from_status IS NULL
        OR from_status IN ('discovered', 'accepted', 'duplicate', 'failed', 'skipped')
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN ('discovered', 'accepted', 'duplicate', 'failed', 'skipped')
    ),
    error_code TEXT,
    error_message TEXT,
    occurred_at TEXT NOT NULL
);

CREATE INDEX idx_import_batches_status_created
    ON import_batches(status, created_at);

CREATE INDEX idx_intake_entries_batch_status
    ON intake_entries(import_batch_id, status, ordinal);

CREATE INDEX idx_intake_entries_source_uri
    ON intake_entries(source_uri);

CREATE INDEX idx_batch_status_history_batch
    ON import_batch_status_history(import_batch_id, sequence);

CREATE INDEX idx_entry_status_history_entry
    ON intake_entry_status_history(intake_entry_id, sequence);

CREATE TRIGGER import_batch_identity_no_update
BEFORE UPDATE OF
    id, intake_context_id, idempotency_key, request_fingerprint,
    source_uri, requested_kind, created_at
ON import_batches
BEGIN
    SELECT RAISE(ABORT, 'import batch identity is immutable');
END;

CREATE TRIGGER intake_entry_provenance_no_update
BEFORE UPDATE OF
    id, import_batch_id, ordinal, source_uri, source_relative_path,
    literal_name, entry_kind, size_bytes, source_created_at,
    source_modified_at, extension, media_type, type_hint, created_at
ON intake_entries
BEGIN
    SELECT RAISE(ABORT, 'intake entry provenance is immutable');
END;

CREATE TRIGGER import_batch_status_transition_guard
BEFORE UPDATE OF status ON import_batches
WHEN NEW.status <> OLD.status
AND NOT (
    (OLD.status = 'enumerating' AND NEW.status IN ('processing', 'failed'))
    OR
    (OLD.status = 'processing' AND NEW.status IN ('succeeded', 'partial', 'failed'))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid import batch status transition');
END;

CREATE TRIGGER intake_context_status_transition_guard
BEFORE UPDATE OF status ON intake_contexts
WHEN NEW.status <> OLD.status
AND NOT (
    (OLD.status = 'enumerating' AND NEW.status IN ('processing', 'failed'))
    OR
    (OLD.status = 'processing' AND NEW.status IN ('succeeded', 'partial', 'failed'))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid intake context status transition');
END;

CREATE TRIGGER intake_entry_status_transition_guard
BEFORE UPDATE OF status ON intake_entries
WHEN NEW.status <> OLD.status
AND NOT (
    OLD.status = 'discovered'
    AND NEW.status IN ('accepted', 'duplicate', 'failed', 'skipped')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid intake entry status transition');
END;

CREATE TRIGGER import_batch_status_history_no_update
BEFORE UPDATE ON import_batch_status_history
BEGIN
    SELECT RAISE(ABORT, 'import batch status history is append-only');
END;

CREATE TRIGGER import_batch_status_history_no_delete
BEFORE DELETE ON import_batch_status_history
BEGIN
    SELECT RAISE(ABORT, 'import batch status history is append-only');
END;

CREATE TRIGGER intake_entry_status_history_no_update
BEFORE UPDATE ON intake_entry_status_history
BEGIN
    SELECT RAISE(ABORT, 'intake entry status history is append-only');
END;

CREATE TRIGGER intake_entry_status_history_no_delete
BEFORE DELETE ON intake_entry_status_history
BEGIN
    SELECT RAISE(ABORT, 'intake entry status history is append-only');
END;

CREATE TRIGGER import_batch_no_delete
BEFORE DELETE ON import_batches
BEGIN
    SELECT RAISE(ABORT, 'import batch inventory is immutable');
END;

CREATE TRIGGER intake_context_no_delete
BEFORE DELETE ON intake_contexts
BEGIN
    SELECT RAISE(ABORT, 'intake context inventory is immutable');
END;

CREATE TRIGGER intake_entry_no_delete
BEFORE DELETE ON intake_entries
BEGIN
    SELECT RAISE(ABORT, 'intake entry inventory is immutable');
END;
