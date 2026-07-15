ALTER TABLE review_bulk_publications ADD COLUMN retry_idempotency_key TEXT;

ALTER TABLE review_bulk_publications
    ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0);
