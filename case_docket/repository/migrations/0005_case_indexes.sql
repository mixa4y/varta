-- C04 additive case scope: case/profile and reverse-membership lookups.
CREATE INDEX IF NOT EXISTS idx_case_profiles_case_status_created
    ON case_profiles(case_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_case_number_candidates_case_review
    ON case_number_candidates(case_id, review_status);

CREATE INDEX IF NOT EXISTS idx_entity_memberships_entity_context
    ON entity_memberships(entity_type, entity_id, context_type, context_id);

CREATE INDEX IF NOT EXISTS idx_case_proceedings_proceeding_case
    ON case_proceedings(proceeding_id, case_id);
