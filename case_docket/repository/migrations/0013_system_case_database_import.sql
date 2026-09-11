-- R05: authoritative local case database import/reconciliation foundation.
-- Existing domain tables remain canonical; this migration only adds durable
-- import provenance, resumability, identity bindings, and issue tracking.

CREATE TABLE airtable_import_runs (
    id TEXT PRIMARY KEY,
    source_identity_sha256 TEXT NOT NULL,
    schema_sha256 TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    selected_case_record_id TEXT NOT NULL,
    selected_case_id TEXT REFERENCES cases(id) ON DELETE RESTRICT,
    corpus_manifest_sha256 TEXT,
    mapping_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN ('planned', 'running', 'interrupted', 'failed', 'ready', 'finalized', 'rejected')
    ),
    counts_json TEXT NOT NULL DEFAULT '{}',
    restart_verified INTEGER NOT NULL DEFAULT 0 CHECK (restart_verified IN (0, 1)),
    backup_verified INTEGER NOT NULL DEFAULT 0 CHECK (backup_verified IN (0, 1)),
    cutover_marker TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX idx_airtable_import_runs_status
    ON airtable_import_runs(status, started_at);
CREATE INDEX idx_airtable_import_runs_snapshot
    ON airtable_import_runs(snapshot_sha256, corpus_manifest_sha256);

CREATE TRIGGER airtable_import_runs_identity_immutable
BEFORE UPDATE OF id, source_identity_sha256, schema_sha256, snapshot_sha256,
                 selected_case_record_id,
                 corpus_manifest_sha256, mapping_version, idempotency_key, started_at
ON airtable_import_runs
BEGIN
    SELECT RAISE(ABORT, 'airtable import identity is immutable');
END;

CREATE TABLE airtable_import_schema_snapshots (
    import_run_id TEXT PRIMARY KEY REFERENCES airtable_import_runs(id) ON DELETE RESTRICT,
    schema_json TEXT NOT NULL CHECK (json_valid(schema_json)),
    schema_sha256 TEXT NOT NULL CHECK (length(schema_sha256) = 64),
    catalog_mapping_sha256 TEXT NOT NULL CHECK (length(catalog_mapping_sha256) = 64),
    captured_start TEXT NOT NULL,
    captured_end TEXT NOT NULL
);

CREATE TRIGGER airtable_import_schema_snapshots_no_update
BEFORE UPDATE ON airtable_import_schema_snapshots
BEGIN
    SELECT RAISE(ABORT, 'airtable schema snapshots are immutable');
END;

CREATE TRIGGER airtable_import_schema_snapshots_no_delete
BEFORE DELETE ON airtable_import_schema_snapshots
BEGIN
    SELECT RAISE(ABORT, 'airtable schema snapshots are immutable');
END;

CREATE TABLE airtable_corpus_manifest_entries (
    import_run_id TEXT NOT NULL REFERENCES airtable_import_runs(id) ON DELETE RESTRICT,
    relative_path TEXT NOT NULL,
    relative_path_sha256 TEXT NOT NULL CHECK (length(relative_path_sha256) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    file_sha256 TEXT NOT NULL CHECK (length(file_sha256) = 64),
    PRIMARY KEY(import_run_id, relative_path_sha256)
);

CREATE TRIGGER airtable_corpus_manifest_entries_no_update
BEFORE UPDATE ON airtable_corpus_manifest_entries
BEGIN
    SELECT RAISE(ABORT, 'corpus manifest entries are immutable');
END;

CREATE TRIGGER airtable_corpus_manifest_entries_no_delete
BEFORE DELETE ON airtable_corpus_manifest_entries
BEGIN
    SELECT RAISE(ABORT, 'corpus manifest entries are immutable');
END;

CREATE TRIGGER airtable_import_runs_no_delete
BEFORE DELETE ON airtable_import_runs
BEGIN
    SELECT RAISE(ABORT, 'airtable import runs cannot be deleted');
END;

CREATE TABLE airtable_import_batches (
    id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES airtable_import_runs(id) ON DELETE RESTRICT,
    phase TEXT NOT NULL,
    batch_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'completed', 'interrupted', 'failed')
    ),
    item_count INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    input_sha256 TEXT,
    output_sha256 TEXT,
    last_error_code TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(import_run_id, phase, batch_key)
);

CREATE INDEX idx_airtable_import_batches_resume
    ON airtable_import_batches(import_run_id, phase, status, ordinal);

CREATE TABLE airtable_record_versions (
    id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES airtable_import_runs(id) ON DELETE RESTRICT,
    airtable_table_id TEXT NOT NULL
        REFERENCES airtable_table_mappings(airtable_table_id) ON DELETE RESTRICT,
    airtable_record_id TEXT NOT NULL,
    local_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    raw_fields_json TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    UNIQUE(import_run_id, airtable_table_id, airtable_record_id)
);

CREATE INDEX idx_airtable_record_versions_record
    ON airtable_record_versions(airtable_table_id, airtable_record_id, captured_at);

CREATE TRIGGER airtable_record_versions_no_update
BEFORE UPDATE ON airtable_record_versions
BEGIN
    SELECT RAISE(ABORT, 'airtable record versions are append-only');
END;

CREATE TRIGGER airtable_record_versions_no_delete
BEFORE DELETE ON airtable_record_versions
BEGIN
    SELECT RAISE(ABORT, 'airtable record versions are append-only');
END;

CREATE TABLE airtable_record_scopes (
    import_run_id TEXT NOT NULL REFERENCES airtable_import_runs(id) ON DELETE RESTRICT,
    airtable_table_id TEXT NOT NULL,
    airtable_record_id TEXT NOT NULL,
    local_id TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (
        classification IN ('selected_case', 'shared', 'cross_case', 'unresolved')
    ),
    owning_case_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(owning_case_ids_json)),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(import_run_id, airtable_table_id, airtable_record_id),
    FOREIGN KEY(import_run_id, airtable_table_id, airtable_record_id)
        REFERENCES airtable_record_versions(import_run_id, airtable_table_id, airtable_record_id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_airtable_record_scopes_classification
    ON airtable_record_scopes(import_run_id, classification, airtable_table_id);

CREATE TRIGGER airtable_record_scopes_no_update
BEFORE UPDATE ON airtable_record_scopes
BEGIN
    SELECT RAISE(ABORT, 'airtable record scope is immutable');
END;

CREATE TRIGGER airtable_record_scopes_no_delete
BEFORE DELETE ON airtable_record_scopes
BEGIN
    SELECT RAISE(ABORT, 'airtable record scope is immutable');
END;

CREATE TABLE airtable_attachment_references (
    id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES airtable_import_runs(id) ON DELETE RESTRICT,
    source_table_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_field_id TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    metadata_sha256 TEXT NOT NULL CHECK (length(metadata_sha256) = 64),
    file_id TEXT REFERENCES file_objects(id) ON DELETE RESTRICT,
    match_status TEXT NOT NULL CHECK (
        match_status IN ('pending', 'matched', 'ambiguous', 'missing', 'download_failed')
    ),
    match_method TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(import_run_id, source_table_id, source_record_id, source_field_id, attachment_id)
);

CREATE INDEX idx_airtable_attachment_references_match
    ON airtable_attachment_references(import_run_id, match_status);
CREATE INDEX idx_airtable_attachment_references_file
    ON airtable_attachment_references(file_id);

CREATE TRIGGER airtable_attachment_identity_immutable
BEFORE UPDATE OF id, import_run_id, source_table_id, source_record_id,
                 source_field_id, attachment_id, metadata_json, metadata_sha256, created_at
ON airtable_attachment_references
BEGIN
    SELECT RAISE(ABORT, 'airtable attachment identity is immutable');
END;

CREATE TABLE airtable_reconciliation_issues (
    id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES airtable_import_runs(id) ON DELETE RESTRICT,
    issue_code TEXT NOT NULL CHECK (
        issue_code IN (
            'schema_drift', 'unknown_field', 'missing_table', 'unresolved_link',
            'orphan_record', 'missing_local_file', 'ambiguous_file_match',
            'hash_mismatch', 'duplicate_identity_suggestion', 'conflicting_date',
            'broken_graph_endpoint', 'missing_source_basis', 'cross_case_relation',
            'unsupported_value', 'attachment_download_failure'
        )
    ),
    severity TEXT NOT NULL CHECK (severity IN ('critical', 'warning', 'info')),
    subject_type TEXT NOT NULL,
    subject_key_sha256 TEXT NOT NULL CHECK (length(subject_key_sha256) = 64),
    detail_code TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'accepted', 'rejected')),
    resolution_review_id TEXT REFERENCES review_decisions(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE(import_run_id, issue_code, subject_type, subject_key_sha256, detail_code)
);

CREATE INDEX idx_airtable_reconciliation_issues_gate
    ON airtable_reconciliation_issues(import_run_id, severity, status);

CREATE TRIGGER airtable_reconciliation_issues_no_delete
BEFORE DELETE ON airtable_reconciliation_issues
BEGIN
    SELECT RAISE(ABORT, 'reconciliation issues cannot be deleted');
END;

CREATE TABLE airtable_import_verifications (
    id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES airtable_import_runs(id) ON DELETE RESTRICT,
    verification_sha256 TEXT NOT NULL UNIQUE CHECK (length(verification_sha256) = 64),
    source_integrity TEXT NOT NULL,
    restored_integrity TEXT NOT NULL,
    source_foreign_keys_ok INTEGER NOT NULL CHECK (source_foreign_keys_ok IN (0, 1)),
    restored_foreign_keys_ok INTEGER NOT NULL CHECK (restored_foreign_keys_ok IN (0, 1)),
    source_revision TEXT NOT NULL CHECK (length(source_revision) = 64),
    restored_revision TEXT NOT NULL CHECK (length(restored_revision) = 64),
    source_counts_sha256 TEXT NOT NULL CHECK (length(source_counts_sha256) = 64),
    restored_counts_sha256 TEXT NOT NULL CHECK (length(restored_counts_sha256) = 64),
    managed_files_verified INTEGER NOT NULL CHECK (managed_files_verified >= 0),
    created_at TEXT NOT NULL
);

CREATE TRIGGER airtable_import_verifications_no_update
BEFORE UPDATE ON airtable_import_verifications
BEGIN
    SELECT RAISE(ABORT, 'import verification evidence is append-only');
END;

CREATE TRIGGER airtable_import_verifications_no_delete
BEFORE DELETE ON airtable_import_verifications
BEGIN
    SELECT RAISE(ABORT, 'import verification evidence is append-only');
END;

CREATE TABLE contact_identifiers (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    identifier_type TEXT NOT NULL CHECK (
        identifier_type IN ('phone', 'email', 'address', 'tax_id', 'registration_id', 'other')
    ),
    normalized_value TEXT NOT NULL,
    display_value TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_references(id) ON DELETE RESTRICT,
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(contact_id, identifier_type, normalized_value, source_reference_id)
);

CREATE INDEX idx_contact_identifiers_contact
    ON contact_identifiers(contact_id, identifier_type);
CREATE INDEX idx_contact_identifiers_suggestion
    ON contact_identifiers(identifier_type, normalized_value);

CREATE TABLE contact_actor_links (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    actor_id TEXT NOT NULL REFERENCES actors(id) ON DELETE RESTRICT,
    source_reference_id TEXT REFERENCES source_references(id) ON DELETE RESTRICT,
    match_method TEXT NOT NULL CHECK (
        match_method IN ('airtable_link', 'explicit_review', 'import_identity')
    ),
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(case_id, contact_id, actor_id)
);

CREATE INDEX idx_contact_actor_links_case
    ON contact_actor_links(case_id, contact_id, actor_id);

CREATE TABLE relation_type_catalog (
    relation_type TEXT NOT NULL,
    catalog_version INTEGER NOT NULL CHECK (catalog_version >= 1),
    directed INTEGER NOT NULL CHECK (directed IN (0, 1)),
    inverse_type TEXT,
    allowed_from_types_json TEXT NOT NULL,
    allowed_to_types_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    PRIMARY KEY(relation_type, catalog_version)
);

CREATE INDEX idx_relation_type_catalog_active
    ON relation_type_catalog(active, relation_type, catalog_version);

CREATE TRIGGER relation_type_catalog_no_update
BEFORE UPDATE ON relation_type_catalog
BEGIN
    SELECT RAISE(ABORT, 'relation type catalog versions are append-only');
END;

CREATE TRIGGER relation_type_catalog_no_delete
BEFORE DELETE ON relation_type_catalog
BEGIN
    SELECT RAISE(ABORT, 'relation type catalog versions are append-only');
END;

INSERT INTO relation_type_catalog(
    relation_type, catalog_version, directed, inverse_type,
    allowed_from_types_json, allowed_to_types_json, created_at
) VALUES
    ('member_of', 1, 1, NULL, '["actor","contact","document","event","proceeding"]', '["case","proceeding"]', '2026-09-07T00:00:00Z'),
    ('main_proceeding_of', 1, 1, NULL, '["proceeding"]', '["case"]', '2026-09-07T00:00:00Z'),
    ('parent_of', 1, 1, 'child_of', '["document","event","proceeding"]', '["document","event","proceeding"]', '2026-09-07T00:00:00Z'),
    ('child_of', 1, 1, 'parent_of', '["document","event","proceeding"]', '["document","event","proceeding"]', '2026-09-07T00:00:00Z'),
    ('participant_in', 1, 1, NULL, '["actor","contact"]', '["case","event","proceeding"]', '2026-09-07T00:00:00Z'),
    ('represents', 1, 1, NULL, '["actor","contact"]', '["actor","contact"]', '2026-09-07T00:00:00Z'),
    ('sender_of', 1, 1, 'recipient_of', '["actor","contact"]', '["document","event"]', '2026-09-07T00:00:00Z'),
    ('recipient_of', 1, 1, 'sender_of', '["actor","contact"]', '["document","event"]', '2026-09-07T00:00:00Z'),
    ('documented_by', 1, 1, NULL, '["claim","event"]', '["document"]', '2026-09-07T00:00:00Z'),
    ('attachment_of', 1, 1, NULL, '["file"]', '["document"]', '2026-09-07T00:00:00Z'),
    ('response_to', 1, 1, NULL, '["document"]', '["document"]', '2026-09-07T00:00:00Z'),
    ('technical_for', 1, 1, NULL, '["document"]', '["document"]', '2026-09-07T00:00:00Z'),
    ('appeals', 1, 1, NULL, '["document"]', '["document"]', '2026-09-07T00:00:00Z'),
    ('amends', 1, 1, NULL, '["document"]', '["document"]', '2026-09-07T00:00:00Z'),
    ('revokes', 1, 1, NULL, '["document"]', '["document"]', '2026-09-07T00:00:00Z'),
    ('replaces', 1, 1, NULL, '["document"]', '["document"]', '2026-09-07T00:00:00Z'),
    ('refers_to', 1, 1, NULL, '["document"]', '["document"]', '2026-09-07T00:00:00Z'),
    ('version_of', 1, 1, NULL, '["document","file"]', '["document","file"]', '2026-09-07T00:00:00Z'),
    ('duplicates', 1, 0, 'duplicates', '["actor","contact","document","file"]', '["actor","contact","document","file"]', '2026-09-07T00:00:00Z'),
    ('supports', 1, 1, NULL, '["claim","document","event"]', '["claim","document","event"]', '2026-09-07T00:00:00Z'),
    ('contradicts', 1, 0, 'contradicts', '["claim","document","event"]', '["claim","document","event"]', '2026-09-07T00:00:00Z'),
    ('cites', 1, 1, NULL, '["claim","document"]', '["claim","document"]', '2026-09-07T00:00:00Z'),
    ('derived_from', 1, 1, NULL, '["claim","document","event","file"]', '["claim","document","event","file"]', '2026-09-07T00:00:00Z');

CREATE VIEW v_airtable_import_gate AS
SELECT
    runs.id AS import_run_id,
    runs.status,
    SUM(CASE WHEN issues.severity = 'critical' AND issues.status = 'open' THEN 1 ELSE 0 END)
        AS open_critical_issues,
    SUM(CASE WHEN issues.severity = 'warning' AND issues.status = 'open' THEN 1 ELSE 0 END)
        AS open_warning_issues,
    SUM(CASE WHEN issues.severity = 'info' AND issues.status = 'open' THEN 1 ELSE 0 END)
        AS open_info_issues
FROM airtable_import_runs AS runs
LEFT JOIN airtable_reconciliation_issues AS issues ON issues.import_run_id = runs.id
GROUP BY runs.id, runs.status;
