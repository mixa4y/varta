-- C04 additive system scope: audit lookup and recovery diagnostics.
CREATE INDEX IF NOT EXISTS idx_audit_log_entity_time
    ON audit_log(entity_table, entity_id, ts);

CREATE INDEX IF NOT EXISTS idx_audit_log_time
    ON audit_log(ts);
