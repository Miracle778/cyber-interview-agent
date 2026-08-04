-- Workspace-level retrospective search snapshots and versioned reports.

CREATE TABLE interview_retrospective_search_sets (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    query_text TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}',
    search_plan_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'searching', 'completed', 'failed')),
    total_questions INTEGER NOT NULL DEFAULT 0 CHECK (total_questions >= 0),
    total_retrospectives INTEGER NOT NULL DEFAULT 0
        CHECK (total_retrospectives >= 0),
    summary_markdown TEXT NOT NULL DEFAULT '',
    summary_citations_json TEXT NOT NULL DEFAULT '[]',
    summary_execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    last_error_code TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_retrospective_search_sets_workspace
    ON interview_retrospective_search_sets(
        workspace_id, created_at DESC, id
    );

CREATE TABLE interview_retrospective_search_results (
    id TEXT PRIMARY KEY,
    search_set_id TEXT NOT NULL
        REFERENCES interview_retrospective_search_sets(id) ON DELETE CASCADE,
    retrospective_id TEXT
        REFERENCES interview_retrospectives(id) ON DELETE SET NULL,
    question_unit_id TEXT
        REFERENCES interview_question_units(id) ON DELETE SET NULL,
    question_analysis_id TEXT
        REFERENCES interview_question_analyses(id) ON DELETE SET NULL,
    rank INTEGER NOT NULL CHECK (rank > 0),
    score REAL NOT NULL CHECK (score >= 0),
    matched_terms_json TEXT NOT NULL DEFAULT '[]',
    source_metadata_json TEXT NOT NULL DEFAULT '{}',
    question_snapshot_json TEXT NOT NULL DEFAULT '{}',
    answer_excerpt TEXT NOT NULL DEFAULT '',
    analysis_snapshot_json TEXT NOT NULL DEFAULT '{}',
    source_available INTEGER NOT NULL DEFAULT 1 CHECK (source_available IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(search_set_id, rank),
    UNIQUE(search_set_id, question_unit_id)
);
CREATE INDEX idx_retrospective_search_results_page
    ON interview_retrospective_search_results(search_set_id, rank, id);
CREATE INDEX idx_retrospective_search_results_source
    ON interview_retrospective_search_results(retrospective_id, question_unit_id);

CREATE TABLE interview_retrospective_search_reports (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    search_set_id TEXT
        REFERENCES interview_retrospective_search_sets(id) ON DELETE SET NULL,
    report_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    supersedes_report_id TEXT
        REFERENCES interview_retrospective_search_reports(id) ON DELETE SET NULL,
    execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    focus TEXT NOT NULL
        CHECK (focus IN ('question_summary', 'performance_review', 'preparation')),
    selected_result_ids_json TEXT NOT NULL DEFAULT '[]',
    body_json TEXT NOT NULL DEFAULT '{}',
    markdown TEXT NOT NULL DEFAULT '',
    citation_question_ids_json TEXT NOT NULL DEFAULT '[]',
    include_answer_excerpts INTEGER NOT NULL DEFAULT 1
        CHECK (include_answer_excerpts IN (0, 1)),
    include_action_plan INTEGER NOT NULL DEFAULT 1
        CHECK (include_action_plan IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    last_error_code TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, report_key, ordinal)
);
CREATE INDEX idx_retrospective_search_reports_workspace
    ON interview_retrospective_search_reports(
        workspace_id, updated_at DESC, id
    );
