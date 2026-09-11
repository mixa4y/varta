CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_table TEXT NOT NULL,
    entity_id TEXT,
    details TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details))
);

CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    airtable_record_id TEXT UNIQUE,
    case_number TEXT,
    name TEXT,
    dispute_summary TEXT,
    parties_text TEXT,
    court TEXT,
    category TEXT,
    status TEXT,
    current_stage TEXT,
    opened_on TEXT,
    closed_on TEXT,
    next_action TEXT,
    short_description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS proceedings (
    id TEXT PRIMARY KEY,
    airtable_record_id TEXT UNIQUE,
    name TEXT,
    proceeding_number TEXT,
    proceeding_type TEXT,
    category TEXT,
    authority TEXT,
    status TEXT,
    started_on TEXT,
    ended_on TEXT,
    outcome TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    airtable_record_id TEXT UNIQUE,
    full_name TEXT NOT NULL,
    short_name TEXT,
    participant_type TEXT NOT NULL CHECK (participant_type IN ('person', 'organization')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    email TEXT,
    phone TEXT,
    additional_phone TEXT,
    address TEXT,
    tax_id TEXT,
    edrpou TEXT,
    birth_or_registration_date TEXT,
    representative_or_contact_person TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    airtable_record_id TEXT UNIQUE,
    title TEXT,
    interaction_type TEXT,
    event_at TEXT,
    sent_at TEXT,
    delivered_at TEXT,
    channel TEXT,
    channel_details TEXT,
    description TEXT,
    attachments_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(attachments_json)),
    workflow_status TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    airtable_record_id TEXT UNIQUE,
    title TEXT,
    doc_type TEXT,
    sent_on TEXT,
    delivered_on TEXT,
    channel TEXT,
    channel_details TEXT,
    file_attachments_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(file_attachments_json)),
    category TEXT,
    registered_on TEXT,
    source TEXT,
    source_archive TEXT,
    imported_on TEXT,
    origin_format TEXT,
    requires_manual_review INTEGER NOT NULL DEFAULT 0
        CHECK (requires_manual_review IN (0, 1)),
    signature_status TEXT,
    transcript TEXT,
    file_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS actors (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS document_files (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    role TEXT,
    sequence_number INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS case_participants (
    id TEXT PRIMARY KEY,
    airtable_record_id TEXT UNIQUE,
    role_external_id TEXT,
    contact_id TEXT REFERENCES contacts(id),
    case_id TEXT REFERENCES cases(id),
    proceeding_id TEXT REFERENCES proceedings(id),
    role TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload)),
    UNIQUE(contact_id, case_id, proceeding_id, role)
);

CREATE TABLE IF NOT EXISTS document_links (
    id TEXT PRIMARY KEY,
    airtable_record_id TEXT UNIQUE,
    title TEXT,
    source_document_id TEXT REFERENCES documents(id),
    target_document_id TEXT REFERENCES documents(id),
    link_type TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS compliance_flags (
    id TEXT PRIMARY KEY,
    airtable_record_id TEXT UNIQUE,
    title TEXT,
    document_id TEXT REFERENCES documents(id),
    flag_type TEXT,
    severity TEXT,
    detected_by TEXT,
    note TEXT,
    manually_confirmed INTEGER NOT NULL DEFAULT 0
        CHECK (manually_confirmed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS document_version_match (
    id TEXT PRIMARY KEY,
    airtable_record_id TEXT UNIQUE,
    title TEXT,
    user_document_id TEXT REFERENCES documents(id),
    court_document_id TEXT REFERENCES documents(id),
    hashes_equal INTEGER NOT NULL DEFAULT 0 CHECK (hashes_equal IN (0, 1)),
    text_similarity_score REAL,
    mismatch_type TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(legacy_payload))
);

CREATE TABLE IF NOT EXISTS contact_cases (
    contact_id TEXT NOT NULL REFERENCES contacts(id),
    case_id TEXT NOT NULL REFERENCES cases(id),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    PRIMARY KEY (contact_id, case_id)
);

CREATE TABLE IF NOT EXISTS contact_proceedings (
    contact_id TEXT NOT NULL REFERENCES contacts(id),
    proceeding_id TEXT NOT NULL REFERENCES proceedings(id),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    PRIMARY KEY (contact_id, proceeding_id)
);

CREATE TABLE IF NOT EXISTS case_proceedings (
    case_id TEXT NOT NULL REFERENCES cases(id),
    proceeding_id TEXT NOT NULL REFERENCES proceedings(id),
    relationship_kind TEXT NOT NULL DEFAULT 'membership'
        CHECK (relationship_kind IN ('membership', 'main')),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_id, proceeding_id, relationship_kind)
);

CREATE TABLE IF NOT EXISTS case_events (
    case_id TEXT NOT NULL REFERENCES cases(id),
    event_id TEXT NOT NULL REFERENCES events(id),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_id, event_id)
);

CREATE TABLE IF NOT EXISTS case_documents (
    case_id TEXT NOT NULL REFERENCES cases(id),
    document_id TEXT NOT NULL REFERENCES documents(id),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_id, document_id)
);

CREATE TABLE IF NOT EXISTS proceeding_events (
    proceeding_id TEXT NOT NULL REFERENCES proceedings(id),
    event_id TEXT NOT NULL REFERENCES events(id),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    PRIMARY KEY (proceeding_id, event_id)
);

CREATE TABLE IF NOT EXISTS proceeding_documents (
    proceeding_id TEXT NOT NULL REFERENCES proceedings(id),
    document_id TEXT NOT NULL REFERENCES documents(id),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    PRIMARY KEY (proceeding_id, document_id)
);

CREATE TABLE IF NOT EXISTS proceeding_relations (
    parent_proceeding_id TEXT NOT NULL REFERENCES proceedings(id),
    child_proceeding_id TEXT NOT NULL REFERENCES proceedings(id),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    CHECK (parent_proceeding_id <> child_proceeding_id),
    PRIMARY KEY (parent_proceeding_id, child_proceeding_id)
);

CREATE TABLE IF NOT EXISTS event_documents (
    event_id TEXT NOT NULL REFERENCES events(id),
    document_id TEXT NOT NULL REFERENCES documents(id),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    PRIMARY KEY (event_id, document_id)
);

CREATE TABLE IF NOT EXISTS event_contacts (
    event_id TEXT NOT NULL REFERENCES events(id),
    contact_id TEXT NOT NULL REFERENCES contacts(id),
    role TEXT NOT NULL CHECK (role IN ('sender', 'recipient')),
    origin TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    PRIMARY KEY (event_id, contact_id, role)
);

CREATE TABLE IF NOT EXISTS airtable_schema_snapshots (
    source_sha256 TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    base_id TEXT NOT NULL,
    base_name TEXT NOT NULL,
    schema_json TEXT NOT NULL CHECK (json_valid(schema_json)),
    installed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS airtable_table_mappings (
    airtable_table_id TEXT PRIMARY KEY,
    airtable_name TEXT NOT NULL,
    sql_table_name TEXT NOT NULL UNIQUE,
    field_count INTEGER NOT NULL CHECK (field_count >= 0)
);

CREATE TABLE IF NOT EXISTS airtable_field_mappings (
    airtable_field_id TEXT PRIMARY KEY,
    airtable_table_id TEXT NOT NULL REFERENCES airtable_table_mappings(airtable_table_id),
    airtable_name TEXT NOT NULL,
    airtable_type TEXT NOT NULL,
    sql_kind TEXT NOT NULL CHECK (sql_kind IN ('column', 'relation', 'lookup', 'formula')),
    sql_target TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(config_json))
);

CREATE TABLE IF NOT EXISTS airtable_select_choices (
    airtable_field_id TEXT NOT NULL
        REFERENCES airtable_field_mappings(airtable_field_id),
    airtable_choice_id TEXT NOT NULL,
    choice_name TEXT NOT NULL,
    color TEXT,
    position INTEGER NOT NULL,
    PRIMARY KEY (airtable_field_id, airtable_choice_id)
);

CREATE TABLE IF NOT EXISTS airtable_relationship_mappings (
    airtable_field_id TEXT PRIMARY KEY
        REFERENCES airtable_field_mappings(airtable_field_id),
    target_table_id TEXT NOT NULL
        REFERENCES airtable_table_mappings(airtable_table_id),
    inverse_field_id TEXT,
    sql_target TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS airtable_computed_dependencies (
    computed_field_id TEXT NOT NULL
        REFERENCES airtable_field_mappings(airtable_field_id),
    dependency_field_id TEXT NOT NULL,
    dependency_kind TEXT NOT NULL CHECK (dependency_kind IN ('link', 'value', 'formula')),
    position INTEGER NOT NULL,
    PRIMARY KEY (computed_field_id, dependency_field_id, dependency_kind)
);

CREATE TABLE IF NOT EXISTS airtable_record_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    airtable_table_id TEXT NOT NULL
        REFERENCES airtable_table_mappings(airtable_table_id),
    airtable_record_id TEXT NOT NULL,
    local_id TEXT NOT NULL,
    raw_fields_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(raw_fields_json)),
    imported_at TEXT NOT NULL,
    UNIQUE (airtable_table_id, airtable_record_id),
    UNIQUE (airtable_table_id, local_id)
);

CREATE TABLE IF NOT EXISTS airtable_record_links (
    source_map_id INTEGER NOT NULL REFERENCES airtable_record_map(id) ON DELETE CASCADE,
    airtable_field_id TEXT NOT NULL
        REFERENCES airtable_relationship_mappings(airtable_field_id),
    target_table_id TEXT NOT NULL
        REFERENCES airtable_table_mappings(airtable_table_id),
    target_airtable_record_id TEXT NOT NULL,
    target_map_id INTEGER REFERENCES airtable_record_map(id),
    position INTEGER NOT NULL,
    PRIMARY KEY (source_map_id, airtable_field_id, target_airtable_record_id)
);

CREATE INDEX IF NOT EXISTS idx_contacts_full_name ON contacts(full_name);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);
CREATE INDEX IF NOT EXISTS idx_cases_number ON cases(case_number);
CREATE INDEX IF NOT EXISTS idx_proceedings_number ON proceedings(proceeding_number);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_events_activity ON events(event_at, sent_at, delivered_at);
CREATE INDEX IF NOT EXISTS idx_airtable_links_target
    ON airtable_record_links(target_table_id, target_airtable_record_id);

CREATE VIEW IF NOT EXISTS v_cases AS
SELECT
    c.*,
    COUNT(DISTINCT cp.proceeding_id) AS proceeding_count
FROM cases AS c
LEFT JOIN case_proceedings AS cp
    ON cp.case_id = c.id AND cp.relationship_kind = 'membership'
GROUP BY c.id;

CREATE VIEW IF NOT EXISTS v_events AS
SELECT
    e.*,
    COALESCE(e.event_at, e.sent_at, e.delivered_at) AS activity_date
FROM events AS e;

CREATE VIEW IF NOT EXISTS v_contact_proceeding_details AS
SELECT
    cp.contact_id,
    p.id AS proceeding_id,
    p.name AS proceeding_name,
    p.proceeding_number,
    p.proceeding_type,
    p.category AS proceeding_category,
    p.authority,
    p.status AS proceeding_status,
    p.started_on,
    p.ended_on,
    p.outcome,
    c.id AS case_id,
    c.case_number
FROM contact_proceedings AS cp
JOIN proceedings AS p ON p.id = cp.proceeding_id
LEFT JOIN case_proceedings AS cpr
    ON cpr.proceeding_id = p.id AND cpr.relationship_kind = 'membership'
LEFT JOIN cases AS c ON c.id = cpr.case_id;

CREATE VIEW IF NOT EXISTS v_airtable_unresolved_links AS
SELECT
    source.airtable_table_id AS source_table_id,
    source.airtable_record_id AS source_record_id,
    links.airtable_field_id,
    links.target_table_id,
    links.target_airtable_record_id,
    links.position
FROM airtable_record_links AS links
JOIN airtable_record_map AS source ON source.id = links.source_map_id
WHERE links.target_map_id IS NULL;
