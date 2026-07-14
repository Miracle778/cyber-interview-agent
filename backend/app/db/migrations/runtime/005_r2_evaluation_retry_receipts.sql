CREATE TABLE review_evaluation_retry_receipts (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES review_attempts(id) ON DELETE CASCADE,
    input_request_id TEXT NOT NULL REFERENCES review_input_requests(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(attempt_id, idempotency_key)
);

CREATE INDEX idx_review_evaluation_retry_attempt
    ON review_evaluation_retry_receipts(attempt_id, created_at);
