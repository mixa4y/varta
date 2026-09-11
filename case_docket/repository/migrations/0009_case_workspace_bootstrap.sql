-- C07 multi-case workspace, temporary intake case identity and manual bootstrap review.
ALTER TABLE case_number_candidates
ADD COLUMN candidate_kind TEXT NOT NULL DEFAULT 'case_number'
    CHECK (candidate_kind = 'case_number');

ALTER TABLE case_number_candidates
ADD COLUMN evidence_basis TEXT;

ALTER TABLE case_number_candidates
ADD COLUMN tool_name TEXT;

ALTER TABLE case_number_candidates
ADD COLUMN tool_version TEXT;

ALTER TABLE case_number_candidates
ADD COLUMN external_reference_system TEXT;

ALTER TABLE case_number_candidates
ADD COLUMN external_reference_kind TEXT;

ALTER TABLE case_number_candidates
ADD COLUMN external_reference_value TEXT;

ALTER TABLE entity_memberships
ADD COLUMN origin TEXT CHECK (
    origin IS NULL OR origin IN ('manual_command', 'bootstrap_confirmation', 'legacy')
);

ALTER TABLE entity_memberships
ADD COLUMN actor_id TEXT;

CREATE TABLE case_bootstraps (
    intake_case_id TEXT PRIMARY KEY,
    intake_entry_id TEXT NOT NULL UNIQUE
        REFERENCES intake_entries(id) ON DELETE RESTRICT,
    file_id TEXT NOT NULL UNIQUE
        REFERENCES file_objects(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (
        status IN ('manual_review_required', 'candidate_ready', 'confirmed')
    ),
    confirmed_case_id TEXT REFERENCES cases(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    CHECK (
        (status = 'confirmed' AND confirmed_case_id IS NOT NULL AND resolved_at IS NOT NULL)
        OR
        (status <> 'confirmed' AND confirmed_case_id IS NULL AND resolved_at IS NULL)
    )
);

-- Existing accepted C06 rows already have application-generated opaque UUID entry IDs.
-- Reuse that UUID in the new intake-case namespace so an upgrade never leaves a file
-- without either a case membership or an explicit pending-review state.
INSERT INTO case_bootstraps(
    intake_case_id, intake_entry_id, file_id, status,
    confirmed_case_id, created_at, updated_at, resolved_at
)
SELECT
    e.id, e.id, e.file_id, 'manual_review_required',
    NULL, e.updated_at, e.updated_at, NULL
FROM intake_entries AS e
WHERE e.status IN ('accepted', 'duplicate')
  AND e.file_id IS NOT NULL;

CREATE TABLE case_bootstrap_status_history (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_case_id TEXT NOT NULL
        REFERENCES case_bootstraps(intake_case_id) ON DELETE RESTRICT,
    from_status TEXT CHECK (
        from_status IS NULL
        OR from_status IN ('manual_review_required', 'candidate_ready', 'confirmed')
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN ('manual_review_required', 'candidate_ready', 'confirmed')
    ),
    candidate_id TEXT REFERENCES case_number_candidates(id) ON DELETE RESTRICT,
    case_id TEXT REFERENCES cases(id) ON DELETE RESTRICT,
    actor_id TEXT,
    note TEXT,
    occurred_at TEXT NOT NULL
);

INSERT INTO case_bootstrap_status_history(
    intake_case_id, from_status, to_status, candidate_id,
    case_id, actor_id, note, occurred_at
)
SELECT
    intake_case_id, NULL, status, NULL,
    NULL, NULL, 'C07 upgrade bootstrap', created_at
FROM case_bootstraps;

CREATE TABLE case_number_registry (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    raw_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('manual_confirmation', 'case_creation', 'legacy_registration')
    ),
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(case_id, normalized_value),
    UNIQUE(normalized_value)
);

CREATE TABLE case_external_references (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    system TEXT NOT NULL,
    kind TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    evidence_basis TEXT NOT NULL,
    source_location TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(system, kind, normalized_value)
);

CREATE TABLE file_context_memberships (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES file_objects(id) ON DELETE RESTRICT,
    context_type TEXT NOT NULL CHECK (context_type IN ('case', 'proceeding')),
    context_id TEXT NOT NULL,
    role TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('bootstrap_confirmation', 'manual_command')),
    actor_id TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(file_id, context_type, context_id, role)
);

CREATE TABLE workspace_case_preferences (
    preference_id TEXT PRIMARY KEY,
    active_case_id TEXT REFERENCES cases(id) ON DELETE RESTRICT,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_case_bootstraps_status_created
    ON case_bootstraps(status, created_at, intake_case_id);

CREATE INDEX idx_case_bootstraps_confirmed_case
    ON case_bootstraps(confirmed_case_id, resolved_at);

CREATE INDEX idx_case_candidates_intake_normalized
    ON case_number_candidates(intake_case_id, normalized_value, review_status);

CREATE INDEX idx_bootstrap_history_intake_sequence
    ON case_bootstrap_status_history(intake_case_id, sequence);

CREATE INDEX idx_file_context_memberships_context
    ON file_context_memberships(context_type, context_id, file_id);

CREATE INDEX idx_file_context_memberships_file
    ON file_context_memberships(file_id, context_type, context_id);

CREATE TRIGGER case_bootstrap_requires_accepted_entry
BEFORE INSERT ON case_bootstraps
WHEN NOT EXISTS (
    SELECT 1
    FROM intake_entries AS e
    WHERE e.id = NEW.intake_entry_id
      AND e.file_id = NEW.file_id
      AND e.status IN ('accepted', 'duplicate')
)
BEGIN
    SELECT RAISE(ABORT, 'case bootstrap requires accepted intake entry');
END;

CREATE TRIGGER case_candidate_requires_bootstrap
BEFORE INSERT ON case_number_candidates
WHEN NOT EXISTS (
    SELECT 1
    FROM case_bootstraps
    WHERE intake_case_id = NEW.intake_case_id
)
BEGIN
    SELECT RAISE(ABORT, 'case candidate requires intake bootstrap');
END;

CREATE TRIGGER case_bootstrap_identity_no_update
BEFORE UPDATE OF intake_case_id, intake_entry_id, file_id, created_at
ON case_bootstraps
BEGIN
    SELECT RAISE(ABORT, 'case bootstrap identity is immutable');
END;

CREATE TRIGGER case_bootstrap_status_transition_guard
BEFORE UPDATE OF status ON case_bootstraps
WHEN NEW.status <> OLD.status
AND NOT (
    OLD.status IN ('manual_review_required', 'candidate_ready')
    AND NEW.status IN ('manual_review_required', 'candidate_ready', 'confirmed')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid case bootstrap status transition');
END;

CREATE TRIGGER case_bootstrap_confirmation_requires_membership
BEFORE UPDATE OF status, confirmed_case_id ON case_bootstraps
WHEN NEW.status = 'confirmed'
AND NOT EXISTS (
    SELECT 1
    FROM file_context_memberships
    WHERE file_id = NEW.file_id
      AND context_type = 'case'
      AND context_id = NEW.confirmed_case_id
)
BEGIN
    SELECT RAISE(ABORT, 'confirmed bootstrap requires file case membership');
END;

CREATE TRIGGER case_bootstrap_no_delete
BEFORE DELETE ON case_bootstraps
BEGIN
    SELECT RAISE(ABORT, 'case bootstrap records are immutable');
END;

CREATE TRIGGER case_bootstrap_history_no_update
BEFORE UPDATE ON case_bootstrap_status_history
BEGIN
    SELECT RAISE(ABORT, 'case bootstrap history is append-only');
END;

CREATE TRIGGER case_bootstrap_history_no_delete
BEFORE DELETE ON case_bootstrap_status_history
BEGIN
    SELECT RAISE(ABORT, 'case bootstrap history is append-only');
END;

CREATE TRIGGER case_candidate_provenance_no_update
BEFORE UPDATE OF
    id, intake_case_id, raw_value, normalized_value, detection_source,
    source_location, confidence, created_at, candidate_kind, evidence_basis,
    tool_name, tool_version, external_reference_system,
    external_reference_kind, external_reference_value
ON case_number_candidates
BEGIN
    SELECT RAISE(ABORT, 'case candidate provenance is immutable');
END;

CREATE TRIGGER case_candidate_no_delete
BEFORE DELETE ON case_number_candidates
BEGIN
    SELECT RAISE(ABORT, 'case candidates are append-only');
END;

CREATE TRIGGER case_number_registry_no_update
BEFORE UPDATE ON case_number_registry
BEGIN
    SELECT RAISE(ABORT, 'confirmed case numbers are append-only');
END;

CREATE TRIGGER case_number_registry_no_delete
BEFORE DELETE ON case_number_registry
BEGIN
    SELECT RAISE(ABORT, 'confirmed case numbers are append-only');
END;

CREATE TRIGGER case_external_reference_no_update
BEFORE UPDATE ON case_external_references
BEGIN
    SELECT RAISE(ABORT, 'case external references are append-only');
END;

CREATE TRIGGER case_external_reference_no_delete
BEFORE DELETE ON case_external_references
BEGIN
    SELECT RAISE(ABORT, 'case external references are append-only');
END;

CREATE TRIGGER file_context_membership_context_guard
BEFORE INSERT ON file_context_memberships
WHEN (
    NEW.context_type = 'case'
    AND NOT EXISTS (SELECT 1 FROM cases WHERE id = NEW.context_id)
)
OR (
    NEW.context_type = 'proceeding'
    AND NOT EXISTS (SELECT 1 FROM proceedings WHERE id = NEW.context_id)
)
BEGIN
    SELECT RAISE(ABORT, 'membership context does not exist');
END;

CREATE TRIGGER file_context_membership_no_update
BEFORE UPDATE ON file_context_memberships
BEGIN
    SELECT RAISE(ABORT, 'file memberships are append-only');
END;

CREATE TRIGGER file_context_membership_no_delete
BEFORE DELETE ON file_context_memberships
BEGIN
    SELECT RAISE(ABORT, 'file memberships are append-only');
END;
