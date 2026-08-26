-- C08 evidence-domain services, optimistic review state and finding history.
-- Existing migrations remain immutable; this migration only adds columns/tables/indexes.

ALTER TABLE actors
ADD COLUMN actor_type TEXT NOT NULL DEFAULT 'unknown'
    CHECK (actor_type IN ('person', 'organization', 'court', 'authority', 'unknown'));

ALTER TABLE actors
ADD COLUMN display_name TEXT;

ALTER TABLE actors
ADD COLUMN normalized_name TEXT;

ALTER TABLE actors
ADD COLUMN review_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (
        review_status IN (
            'unreviewed', 'manual_review_required', 'in_review', 'confirmed',
            'rejected', 'resolved', 'superseded'
        )
    );

ALTER TABLE actors
ADD COLUMN notes TEXT;

ALTER TABLE actors
ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1);

ALTER TABLE documents
ADD COLUMN label TEXT;

ALTER TABLE documents
ADD COLUMN summary TEXT;

ALTER TABLE documents
ADD COLUMN process_role TEXT;

ALTER TABLE documents
ADD COLUMN classification TEXT NOT NULL DEFAULT 'unverified'
    CHECK (
        classification IN (
            'confirmed_fact', 'party_position', 'user_position', 'court_reasoning',
            'legal_conclusion', 'contradiction', 'open_question', 'unverified'
        )
    );

ALTER TABLE documents
ADD COLUMN review_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (
        review_status IN (
            'unreviewed', 'manual_review_required', 'in_review', 'confirmed',
            'rejected', 'resolved', 'superseded'
        )
    );

ALTER TABLE documents
ADD COLUMN is_key INTEGER NOT NULL DEFAULT 0 CHECK (is_key IN (0, 1));

ALTER TABLE documents
ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1);

ALTER TABLE events
ADD COLUMN classification TEXT NOT NULL DEFAULT 'unverified'
    CHECK (
        classification IN (
            'confirmed_fact', 'party_position', 'user_position', 'court_reasoning',
            'legal_conclusion', 'contradiction', 'open_question', 'unverified'
        )
    );

ALTER TABLE events
ADD COLUMN review_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (
        review_status IN (
            'unreviewed', 'manual_review_required', 'in_review', 'confirmed',
            'rejected', 'resolved', 'superseded'
        )
    );

ALTER TABLE events
ADD COLUMN process_consequence TEXT;

ALTER TABLE events
ADD COLUMN next_action TEXT;

ALTER TABLE events
ADD COLUMN deadline TEXT;

ALTER TABLE events
ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1);

ALTER TABLE source_references
ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1);

ALTER TABLE claims
ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1);

ALTER TABLE evidence_relations
ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1);

ALTER TABLE review_decisions
ADD COLUMN subject_version INTEGER NOT NULL DEFAULT 1 CHECK (subject_version >= 1);

ALTER TABLE review_decisions
ADD COLUMN decision_origin TEXT NOT NULL DEFAULT 'user'
    CHECK (decision_origin IN ('user', 'compatibility_import'));

CREATE TABLE event_actor_links (
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    actor_id TEXT NOT NULL REFERENCES actors(id) ON DELETE RESTRICT,
    role TEXT NOT NULL DEFAULT 'participant',
    PRIMARY KEY (event_id, actor_id, role)
);

CREATE TABLE evidence_findings (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    finding_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (
        severity IN ('critical', 'high', 'medium', 'low', 'info', 'unknown')
    ),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    detector_name TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    processing_run_id TEXT REFERENCES processing_runs(id) ON DELETE RESTRICT,
    automatic_status TEXT NOT NULL CHECK (
        automatic_status IN ('detected', 'not_detected', 'error', 'unknown')
    ),
    automatic_version INTEGER NOT NULL DEFAULT 1 CHECK (automatic_version >= 1),
    review_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK (
        review_status IN (
            'unreviewed', 'manual_review_required', 'in_review', 'confirmed',
            'rejected', 'resolved', 'superseded', 'open', 'acknowledged',
            'false_positive'
        )
    ),
    review_version INTEGER NOT NULL DEFAULT 0 CHECK (review_version >= 0),
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE finding_observations (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id TEXT NOT NULL REFERENCES evidence_findings(id) ON DELETE RESTRICT,
    processing_run_id TEXT REFERENCES processing_runs(id) ON DELETE RESTRICT,
    observation_status TEXT NOT NULL CHECK (
        observation_status IN ('detected', 'not_detected', 'error', 'unknown', 'compatibility_import')
    ),
    detector_name TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (
        severity IN ('critical', 'high', 'medium', 'low', 'info', 'unknown')
    ),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details_json)),
    observed_at TEXT NOT NULL
);

CREATE TABLE finding_subjects (
    finding_id TEXT NOT NULL REFERENCES evidence_findings(id) ON DELETE RESTRICT,
    subject_type TEXT NOT NULL CHECK (
        subject_type IN (
            'case', 'proceeding', 'actor', 'file', 'document', 'event',
            'claim', 'relation', 'source_reference', 'legacy_document'
        )
    ),
    subject_id TEXT NOT NULL,
    PRIMARY KEY (finding_id, subject_type, subject_id)
);

CREATE TABLE finding_source_references (
    finding_id TEXT NOT NULL REFERENCES evidence_findings(id) ON DELETE RESTRICT,
    source_reference_id TEXT NOT NULL REFERENCES source_references(id) ON DELETE RESTRICT,
    PRIMARY KEY (finding_id, source_reference_id)
);

CREATE TABLE finding_review_decisions (
    id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL REFERENCES evidence_findings(id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK (
        decision IN (
            'confirm', 'reject', 'request_review', 'resolve', 'supersede',
            'acknowledge', 'reopen', 'false_positive'
        )
    ),
    previous_status TEXT,
    new_status TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    subject_version INTEGER NOT NULL CHECK (subject_version >= 1),
    decided_at TEXT NOT NULL,
    note TEXT,
    decision_origin TEXT NOT NULL DEFAULT 'user'
        CHECK (decision_origin IN ('user', 'compatibility_import'))
);

CREATE TABLE finding_review_decision_sources (
    finding_review_decision_id TEXT NOT NULL
        REFERENCES finding_review_decisions(id) ON DELETE RESTRICT,
    source_reference_id TEXT NOT NULL REFERENCES source_references(id) ON DELETE RESTRICT,
    PRIMARY KEY (finding_review_decision_id, source_reference_id)
);

CREATE TABLE compatibility_review_states (
    subject_type TEXT NOT NULL CHECK (
        subject_type IN ('legacy_document', 'legacy_finding')
    ),
    external_id TEXT NOT NULL,
    current_status TEXT NOT NULL,
    note TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (subject_type, external_id)
);

CREATE TABLE compatibility_review_decisions (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    subject_type TEXT NOT NULL CHECK (
        subject_type IN ('legacy_document', 'legacy_finding')
    ),
    external_id TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    subject_version INTEGER NOT NULL CHECK (subject_version >= 1),
    decided_at TEXT NOT NULL,
    note TEXT,
    decision_origin TEXT NOT NULL CHECK (
        decision_origin IN ('user', 'compatibility_import')
    )
);

CREATE TABLE compatibility_review_imports (
    source_token TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (
        subject_type IN ('legacy_document', 'legacy_finding')
    ),
    imported_count INTEGER NOT NULL CHECK (imported_count >= 0),
    imported_at TEXT NOT NULL
);

CREATE TRIGGER finding_observations_no_update
BEFORE UPDATE ON finding_observations
BEGIN
    SELECT RAISE(ABORT, 'finding observations are append-only');
END;

CREATE TRIGGER finding_observations_no_delete
BEFORE DELETE ON finding_observations
BEGIN
    SELECT RAISE(ABORT, 'finding observations are append-only');
END;

CREATE TRIGGER finding_review_decisions_no_update
BEFORE UPDATE ON finding_review_decisions
BEGIN
    SELECT RAISE(ABORT, 'finding review decisions are append-only');
END;

CREATE TRIGGER finding_review_decisions_no_delete
BEFORE DELETE ON finding_review_decisions
BEGIN
    SELECT RAISE(ABORT, 'finding review decisions are append-only');
END;

CREATE TRIGGER compatibility_review_decisions_no_update
BEFORE UPDATE ON compatibility_review_decisions
BEGIN
    SELECT RAISE(ABORT, 'compatibility review decisions are append-only');
END;

CREATE TRIGGER compatibility_review_decisions_no_delete
BEFORE DELETE ON compatibility_review_decisions
BEGIN
    SELECT RAISE(ABORT, 'compatibility review decisions are append-only');
END;

CREATE INDEX idx_actor_review_name
    ON actors(review_status, normalized_name, id);

CREATE INDEX idx_document_review_created
    ON documents(review_status, created_at, id);

CREATE INDEX idx_event_review_time
    ON events(review_status, event_at, created_at, id);

CREATE INDEX idx_finding_fingerprint_version
    ON evidence_findings(fingerprint, automatic_version);

CREATE INDEX idx_finding_review_status_time
    ON evidence_findings(review_status, last_observed_at, id);

CREATE INDEX idx_finding_observations_finding_sequence
    ON finding_observations(finding_id, sequence);

CREATE INDEX idx_finding_subject_lookup
    ON finding_subjects(subject_type, subject_id, finding_id);

CREATE INDEX idx_finding_review_history
    ON finding_review_decisions(finding_id, decided_at, id);

CREATE INDEX idx_compatibility_review_history
    ON compatibility_review_decisions(subject_type, external_id, sequence);
