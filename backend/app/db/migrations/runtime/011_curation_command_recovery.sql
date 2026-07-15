ALTER TABLE review_curation_command_receipts
    ADD COLUMN original_text TEXT NOT NULL DEFAULT '';

ALTER TABLE review_curation_command_receipts
    ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0);
