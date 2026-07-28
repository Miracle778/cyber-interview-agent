CREATE TABLE review_round_control_receipts (
    id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES review_rounds(id) ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK (
        operation IN ('interrupt_evaluation', 'skip_current')
    ),
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(round_id, operation, idempotency_key)
);

CREATE INDEX idx_review_round_control_receipts_round
    ON review_round_control_receipts(round_id, created_at);
