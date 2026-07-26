ALTER TABLE review_attempts
    ADD COLUMN coverage_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE review_attempts
    ADD COLUMN result_kind TEXT CHECK (
        result_kind IS NULL OR result_kind IN (
            'independent_mastery',
            'assisted_mastery',
            'revealed',
            'skipped'
        )
    );

ALTER TABLE review_attempts
    ADD COLUMN hint_level INTEGER NOT NULL DEFAULT 0 CHECK (hint_level >= 0);

ALTER TABLE review_attempts
    ADD COLUMN answer_revisions_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE review_question_assistance (
    round_id TEXT NOT NULL REFERENCES review_rounds(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    hint_level INTEGER NOT NULL DEFAULT 0 CHECK (hint_level >= 0),
    revealed INTEGER NOT NULL DEFAULT 0 CHECK (revealed IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (round_id, ordinal)
);

CREATE TABLE review_auxiliary_turn_receipts (
    id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES review_rounds(id) ON DELETE CASCADE,
    input_request_id TEXT NOT NULL
        REFERENCES review_input_requests(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    intent TEXT NOT NULL CHECK (
        intent IN (
            'show_question',
            'request_hint',
            'reveal_answer',
            'explain',
            'unrelated'
        )
    ),
    user_message_id TEXT NOT NULL,
    assistant_message_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(input_request_id, idempotency_key)
);
