-- C04 additive intake scope: processing/file traversal without schema rewrites.
CREATE INDEX IF NOT EXISTS idx_processing_runs_status_started
    ON processing_runs(status, started_at);

CREATE INDEX IF NOT EXISTS idx_processing_run_files_file_role
    ON processing_run_files(file_id, role);

CREATE INDEX IF NOT EXISTS idx_signatures_signed_file_status
    ON signatures(signed_file_id, status);

CREATE INDEX IF NOT EXISTS idx_source_references_file_review
    ON source_references(source_file_id, review_status);
