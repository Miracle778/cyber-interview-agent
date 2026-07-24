-- R3 unified personal profile: multi-source confirmed facts, typed relations,
-- presentation ordering, and soft-deletable profile cards.

ALTER TABLE profile_claim_proposals
    ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'resume_extraction'
    CHECK (
        source_kind IN (
            'resume_extraction', 'user_input', 'conversation', 'agent_inference'
        )
    );

ALTER TABLE profile_claim_proposals
    ADD COLUMN source_ref_json TEXT NOT NULL DEFAULT '{}'
    CHECK (
        json_valid(source_ref_json) AND json_type(source_ref_json) = 'object'
    );

CREATE TABLE profile_claims_unified (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK (
        claim_type IN (
            'skill', 'project', 'experience', 'education', 'certification',
            'achievement', 'link', 'summary', 'direction', 'highlight'
        )
    ),
    current_confirmed_version_id TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO profile_claims_unified (
    id,
    workspace_id,
    claim_type,
    current_confirmed_version_id,
    version,
    created_at,
    updated_at
)
SELECT
    id,
    workspace_id,
    claim_type,
    current_confirmed_version_id,
    version,
    created_at,
    updated_at
FROM profile_claims;

DROP TABLE profile_claims;
ALTER TABLE profile_claims_unified RENAME TO profile_claims;

CREATE INDEX idx_profile_claims_workspace_type
    ON profile_claims(workspace_id, claim_type, deleted_at, updated_at DESC, id);

CREATE TABLE profile_claim_sources (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    claim_version_id TEXT NOT NULL
        REFERENCES profile_claim_versions(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL CHECK (
        source_kind IN (
            'resume_extraction', 'user_input', 'conversation', 'agent_inference'
        )
    ),
    source_ref_json TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(source_ref_json) AND json_type(source_ref_json) = 'object'
    ),
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('active', 'source_deleted', 'superseded')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(claim_version_id, source_kind, source_ref_json)
);

CREATE INDEX idx_profile_claim_sources_version
    ON profile_claim_sources(claim_version_id, status, created_at, id);
CREATE INDEX idx_profile_claim_sources_workspace
    ON profile_claim_sources(workspace_id, status, created_at DESC, id);

CREATE TABLE profile_claim_relations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    from_claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE CASCADE,
    to_claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL CHECK (
        relation_type IN ('belongs_to', 'used_in', 'supported_by')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_claim_id, to_claim_id, relation_type),
    CHECK(from_claim_id <> to_claim_id)
);

CREATE INDEX idx_profile_claim_relations_from
    ON profile_claim_relations(workspace_id, from_claim_id, relation_type, id);
CREATE INDEX idx_profile_claim_relations_to
    ON profile_claim_relations(workspace_id, to_claim_id, relation_type, id);

CREATE TABLE profile_presentations (
    workspace_id TEXT PRIMARY KEY,
    summary_claim_id TEXT REFERENCES profile_claims(id) ON DELETE SET NULL,
    primary_direction_claim_id TEXT
        REFERENCES profile_claims(id) ON DELETE SET NULL,
    featured_claim_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(featured_claim_ids_json)
        AND json_type(featured_claim_ids_json) = 'array'
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
