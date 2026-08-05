ALTER TABLE interview_source_versions
ADD COLUMN recording_coverage TEXT NOT NULL DEFAULT 'mixed_unknown'
    CHECK (recording_coverage IN ('full_dialogue', 'candidate_only', 'mixed_unknown'));
