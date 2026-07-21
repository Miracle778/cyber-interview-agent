ALTER TABLE review_curation_control_receipts
    ADD COLUMN reserved_execution_id TEXT;

CREATE UNIQUE INDEX idx_review_curation_control_receipts_reserved_execution
    ON review_curation_control_receipts(reserved_execution_id)
    WHERE reserved_execution_id IS NOT NULL;
