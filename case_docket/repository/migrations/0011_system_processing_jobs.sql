CREATE TABLE processing_jobs (
    id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
    processor TEXT NOT NULL, request_json TEXT NOT NULL CHECK (json_valid(request_json)),
    result_json TEXT, status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted','not_available')),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0), lease_token TEXT,
    lease_expires_at TEXT, timeout_seconds INTEGER NOT NULL CHECK (timeout_seconds > 0),
    created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, error_json TEXT
);
CREATE TABLE processing_job_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES processing_jobs(id),
    from_status TEXT, to_status TEXT NOT NULL, occurred_at TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail_json))
);
CREATE INDEX idx_processing_jobs_queue ON processing_jobs(status, created_at);
CREATE INDEX idx_processing_jobs_lease ON processing_jobs(status, lease_expires_at);
