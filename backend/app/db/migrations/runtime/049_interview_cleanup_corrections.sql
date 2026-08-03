-- Auditable transcript corrections owned by an interview cleanup version.

CREATE TABLE interview_corrections (
    id TEXT PRIMARY KEY,
    cleanup_version_id TEXT NOT NULL
        REFERENCES interview_cleanup_versions(id) ON DELETE CASCADE,
    segment_id TEXT NOT NULL
        REFERENCES interview_segments(id) ON DELETE CASCADE,
    source_start INTEGER NOT NULL CHECK (source_start >= 0),
    source_end INTEGER NOT NULL CHECK (source_end > source_start),
    original_text TEXT,
    original_sha256 TEXT NOT NULL CHECK (length(original_sha256) = 64),
    suggested_text TEXT,
    adopted_text TEXT,
    change_type TEXT NOT NULL
        CHECK (change_type IN ('formatting', 'recognition', 'semantic')),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'high')),
    reason TEXT,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    decision TEXT NOT NULL
        CHECK (decision IN (
            'auto_accepted', 'pending', 'accepted', 'kept_original',
            'manual', 'superseded'
        )),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_interview_corrections_review
    ON interview_corrections(
        cleanup_version_id, segment_id, decision, source_start, source_end, id
    );
