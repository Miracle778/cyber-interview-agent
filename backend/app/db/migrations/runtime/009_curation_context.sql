CREATE TABLE review_curation_context (
    session_id TEXT PRIMARY KEY
        REFERENCES review_curation_sessions(session_id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    focused_candidate_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(focused_candidate_ids_json)
        AND json_type(focused_candidate_ids_json) = 'array'
    ),
    last_intent TEXT,
    last_result_candidate_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(last_result_candidate_ids_json)
        AND json_type(last_result_candidate_ids_json) = 'array'
    ),
    dialogue_summary_json TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(dialogue_summary_json)
        AND json_type(dialogue_summary_json) = 'object'
    ),
    summarized_through_message_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
