CREATE TABLE interview_retrospective_corrections (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL
        REFERENCES interview_retrospectives(id) ON DELETE CASCADE,
    chat_message_id TEXT REFERENCES agent_messages(id) ON DELETE SET NULL,
    proposal_type TEXT NOT NULL CHECK (proposal_type IN (
        'question_text_correction', 'question_segment_rebind',
        'speaker_correction', 'analysis_reconsideration'
    )),
    target_question_id TEXT REFERENCES interview_question_units(id) ON DELETE CASCADE,
    source_cleanup_version_id TEXT NOT NULL
        REFERENCES interview_cleanup_versions(id) ON DELETE RESTRICT,
    source_analysis_run_id TEXT
        REFERENCES interview_analysis_runs(id) ON DELETE SET NULL,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    rationale TEXT NOT NULL DEFAULT '',
    expected_version INTEGER NOT NULL CHECK (expected_version > 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'rejected')),
    resulting_cleanup_version_id TEXT
        REFERENCES interview_cleanup_versions(id) ON DELETE SET NULL,
    resulting_analysis_run_id TEXT
        REFERENCES interview_analysis_runs(id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_interview_corrections_retrospective
    ON interview_retrospective_corrections(retrospective_id, status, created_at, id);
