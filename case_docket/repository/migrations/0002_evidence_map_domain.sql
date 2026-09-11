CREATE TABLE case_profiles (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    schema_version TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    profile_json TEXT NOT NULL CHECK (json_valid(profile_json)),
    profile_sha256 TEXT NOT NULL CHECK (length(profile_sha256) = 64),
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'superseded', 'rejected')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    UNIQUE(case_id, profile_version)
);

CREATE TABLE case_number_candidates (
    id TEXT PRIMARY KEY,
    intake_case_id TEXT NOT NULL,
    case_id TEXT REFERENCES cases(id),
    raw_value TEXT NOT NULL,
    normalized_value TEXT,
    detection_source TEXT NOT NULL CHECK (
        detection_source IN (
            'structured_metadata', 'document_text', 'ocr', 'verified_manifest',
            'filename', 'folder', 'manual'
        )
    ),
    source_location TEXT,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    review_status TEXT NOT NULL CHECK (
        review_status IN (
            'unreviewed', 'manual_review_required', 'in_review', 'confirmed',
            'rejected', 'superseded'
        )
    ),
    decided_by TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE file_objects (
    id TEXT PRIMARY KEY,
    document_file_id TEXT UNIQUE REFERENCES document_files(id),
    document_id TEXT REFERENCES documents(id),
    import_batch_id TEXT,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'content', 'attachment', 'signature', 'ocr_text', 'transcript',
            'metadata_snapshot', 'derived', 'unknown'
        )
    ),
    original_name TEXT NOT NULL,
    managed_name TEXT,
    source_relative_path TEXT,
    storage_reference TEXT,
    extension TEXT,
    media_type TEXT,
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    sha256 TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
    integrity_status TEXT NOT NULL CHECK (
        integrity_status IN (
            'verified', 'mismatch', 'reference_unavailable', 'not_checked', 'error'
        )
    ),
    review_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE processing_runs (
    id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_version TEXT,
    parameters_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(parameters_json)),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'not_available', 'not_verifiable')),
    error_details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE processing_run_files (
    processing_run_id TEXT NOT NULL REFERENCES processing_runs(id),
    file_id TEXT NOT NULL REFERENCES file_objects(id),
    role TEXT NOT NULL CHECK (role IN ('input', 'output', 'log')),
    PRIMARY KEY (processing_run_id, file_id, role)
);

CREATE TABLE signatures (
    id TEXT PRIMARY KEY,
    signature_file_id TEXT NOT NULL REFERENCES file_objects(id),
    signed_file_id TEXT REFERENCES file_objects(id),
    processing_run_id TEXT REFERENCES processing_runs(id),
    status TEXT NOT NULL,
    signer_name TEXT,
    certificate_serial TEXT,
    signed_at TEXT,
    verified_at TEXT,
    public_details_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(public_details_json)),
    error_details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE source_references (
    id TEXT PRIMARY KEY,
    source_entity_type TEXT NOT NULL CHECK (
        source_entity_type IN ('case', 'proceeding', 'actor', 'file', 'document', 'event', 'claim', 'relation', 'manual_note')
    ),
    source_entity_id TEXT NOT NULL,
    source_file_id TEXT REFERENCES file_objects(id),
    location_type TEXT NOT NULL CHECK (
        location_type IN (
            'document', 'page', 'paragraph', 'cell', 'timecode', 'bounding_box',
            'metadata', 'whole_file', 'manual_note'
        )
    ),
    location_value TEXT,
    excerpt TEXT,
    source_sha256 TEXT CHECK (source_sha256 IS NULL OR length(source_sha256) = 64),
    review_status TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE entity_memberships (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('document', 'event', 'actor', 'claim')),
    entity_id TEXT NOT NULL,
    context_type TEXT NOT NULL CHECK (context_type IN ('case', 'proceeding')),
    context_id TEXT NOT NULL,
    role TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    source_reference_id TEXT REFERENCES source_references(id),
    review_status TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, context_type, context_id, role)
);

CREATE TABLE entity_dates (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('case', 'proceeding', 'document', 'event', 'claim', 'relation')),
    entity_id TEXT NOT NULL,
    date_role TEXT NOT NULL CHECK (
        date_role IN (
            'document_date', 'submitted_date', 'registered_date', 'received_date',
            'opened_date', 'closed_date', 'effective_date', 'hearing_date',
            'issued_date', 'due_date', 'other'
        )
    ),
    date_value TEXT,
    precision TEXT NOT NULL CHECK (
        precision IN ('exact_datetime', 'exact_date', 'month', 'year', 'approximate', 'unknown')
    ),
    timezone TEXT,
    source_reference_id TEXT REFERENCES source_references(id),
    review_status TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('case', 'proceeding', 'actor', 'file', 'document', 'event', 'relation')),
    subject_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (
        classification IN (
            'confirmed_fact', 'party_position', 'user_position', 'court_reasoning',
            'legal_conclusion', 'contradiction', 'open_question', 'unverified'
        )
    ),
    review_status TEXT NOT NULL CHECK (
        review_status IN (
            'unreviewed', 'manual_review_required', 'in_review', 'confirmed',
            'rejected', 'resolved', 'superseded'
        )
    ),
    uncertainty_note TEXT,
    process_consequence TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE claim_assertors (
    claim_id TEXT NOT NULL REFERENCES claims(id),
    actor_id TEXT NOT NULL REFERENCES actors(id),
    role TEXT,
    PRIMARY KEY (claim_id, actor_id)
);

CREATE TABLE claim_basis_documents (
    claim_id TEXT NOT NULL REFERENCES claims(id),
    document_id TEXT NOT NULL REFERENCES documents(id),
    PRIMARY KEY (claim_id, document_id)
);

CREATE TABLE claim_source_references (
    claim_id TEXT NOT NULL REFERENCES claims(id),
    source_reference_id TEXT NOT NULL REFERENCES source_references(id),
    PRIMARY KEY (claim_id, source_reference_id)
);

CREATE TABLE legal_citations (
    id TEXT PRIMARY KEY,
    jurisdiction TEXT,
    instrument_title TEXT NOT NULL,
    provision TEXT,
    canonical_uri TEXT,
    source_reference_id TEXT REFERENCES source_references(id),
    review_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE claim_legal_citations (
    claim_id TEXT NOT NULL REFERENCES claims(id),
    legal_citation_id TEXT NOT NULL REFERENCES legal_citations(id),
    PRIMARY KEY (claim_id, legal_citation_id)
);

CREATE TABLE evidence_relations (
    id TEXT PRIMARY KEY,
    from_type TEXT NOT NULL CHECK (from_type IN ('case', 'proceeding', 'actor', 'file', 'document', 'event', 'claim')),
    from_id TEXT NOT NULL,
    to_type TEXT NOT NULL CHECK (to_type IN ('case', 'proceeding', 'actor', 'file', 'document', 'event', 'claim')),
    to_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    label TEXT,
    classification TEXT NOT NULL CHECK (
        classification IN (
            'confirmed_fact', 'party_position', 'user_position', 'court_reasoning',
            'legal_conclusion', 'contradiction', 'open_question', 'unverified'
        )
    ),
    review_status TEXT NOT NULL,
    uncertainty_note TEXT,
    valid_from TEXT,
    valid_to TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (from_type <> to_type OR from_id <> to_id)
);

CREATE TABLE relation_basis_documents (
    relation_id TEXT NOT NULL REFERENCES evidence_relations(id),
    document_id TEXT NOT NULL REFERENCES documents(id),
    PRIMARY KEY (relation_id, document_id)
);

CREATE TABLE relation_source_references (
    relation_id TEXT NOT NULL REFERENCES evidence_relations(id),
    source_reference_id TEXT NOT NULL REFERENCES source_references(id),
    PRIMARY KEY (relation_id, source_reference_id)
);

CREATE TABLE review_decisions (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (
        subject_type IN ('case', 'proceeding', 'actor', 'file', 'document', 'event', 'claim', 'relation', 'source_reference')
    ),
    subject_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (
        decision IN ('confirm', 'reject', 'request_review', 'resolve', 'supersede', 'merge', 'split')
    ),
    previous_status TEXT,
    new_status TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    note TEXT
);

CREATE TRIGGER review_decisions_no_update
BEFORE UPDATE ON review_decisions
BEGIN
    SELECT RAISE(ABORT, 'review_decisions is append-only');
END;

CREATE TRIGGER review_decisions_no_delete
BEFORE DELETE ON review_decisions
BEGIN
    SELECT RAISE(ABORT, 'review_decisions is append-only');
END;

CREATE TABLE review_decision_sources (
    review_decision_id TEXT NOT NULL REFERENCES review_decisions(id),
    source_reference_id TEXT NOT NULL REFERENCES source_references(id),
    PRIMARY KEY (review_decision_id, source_reference_id)
);

CREATE TABLE amounts (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('case', 'proceeding', 'document', 'event', 'claim')),
    subject_id TEXT NOT NULL,
    label TEXT NOT NULL,
    amount_value NUMERIC,
    display_value TEXT,
    currency TEXT,
    classification TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_references(id),
    review_status TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE evidence_map_exports (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    case_profile_id TEXT NOT NULL REFERENCES case_profiles(id),
    schema_version TEXT NOT NULL,
    product_version TEXT NOT NULL,
    export_profile TEXT NOT NULL CHECK (export_profile IN ('full_local', 'redacted', 'metadata_only')),
    source_revision TEXT,
    source_snapshot_sha256 TEXT CHECK (source_snapshot_sha256 IS NULL OR length(source_snapshot_sha256) = 64),
    status TEXT NOT NULL CHECK (status IN ('building', 'valid', 'invalid', 'superseded')),
    sealed INTEGER NOT NULL CHECK (sealed IN (0, 1)),
    generated_by TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    data_cutoff TEXT,
    limitations_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(limitations_json))
);

CREATE TABLE evidence_map_export_artifacts (
    export_id TEXT NOT NULL REFERENCES evidence_map_exports(id),
    artifact_role TEXT NOT NULL CHECK (artifact_role IN ('index_html', 'map_data', 'manifest', 'validation_report', 'other')),
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    PRIMARY KEY (export_id, artifact_role, relative_path)
);

CREATE INDEX idx_case_number_candidates_normalized
    ON case_number_candidates(normalized_value, review_status);
CREATE INDEX idx_file_objects_sha256 ON file_objects(sha256);
CREATE INDEX idx_file_objects_document ON file_objects(document_id);
CREATE INDEX idx_source_references_subject
    ON source_references(source_entity_type, source_entity_id);
CREATE INDEX idx_entity_memberships_context
    ON entity_memberships(context_type, context_id, entity_type);
CREATE INDEX idx_entity_dates_subject
    ON entity_dates(entity_type, entity_id, date_role);
CREATE INDEX idx_claims_subject ON claims(subject_type, subject_id);
CREATE INDEX idx_claims_classification ON claims(classification, review_status);
CREATE INDEX idx_evidence_relations_from ON evidence_relations(from_type, from_id);
CREATE INDEX idx_evidence_relations_to ON evidence_relations(to_type, to_id);
CREATE INDEX idx_review_decisions_subject
    ON review_decisions(subject_type, subject_id, decided_at);
CREATE INDEX idx_amounts_subject ON amounts(subject_type, subject_id);
CREATE INDEX idx_evidence_map_exports_case
    ON evidence_map_exports(case_id, generated_at);
