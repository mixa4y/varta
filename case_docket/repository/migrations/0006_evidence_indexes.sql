-- C04 additive evidence scope: reverse evidence-basis and review lookups.
CREATE INDEX IF NOT EXISTS idx_claim_assertors_actor_claim
    ON claim_assertors(actor_id, claim_id);

CREATE INDEX IF NOT EXISTS idx_claim_basis_documents_document_claim
    ON claim_basis_documents(document_id, claim_id);

CREATE INDEX IF NOT EXISTS idx_claim_source_references_source_claim
    ON claim_source_references(source_reference_id, claim_id);

CREATE INDEX IF NOT EXISTS idx_relation_basis_documents_document_relation
    ON relation_basis_documents(document_id, relation_id);

CREATE INDEX IF NOT EXISTS idx_relation_source_references_source_relation
    ON relation_source_references(source_reference_id, relation_id);

CREATE INDEX IF NOT EXISTS idx_review_decision_sources_source_decision
    ON review_decision_sources(source_reference_id, review_decision_id);
