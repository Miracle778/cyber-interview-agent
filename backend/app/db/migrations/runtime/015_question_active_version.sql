ALTER TABLE review_question_candidates
    ADD COLUMN revision_of_question_id TEXT;
ALTER TABLE review_question_candidates
    ADD COLUMN revision_base_hash TEXT;

CREATE INDEX idx_review_question_candidates_revision
    ON review_question_candidates(revision_of_question_id, updated_at DESC, id);
