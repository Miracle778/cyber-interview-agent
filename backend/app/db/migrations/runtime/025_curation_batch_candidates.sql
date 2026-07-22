CREATE TABLE review_curation_batch_candidates (
    batch_id TEXT NOT NULL
        REFERENCES review_question_batches(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL
        REFERENCES review_question_candidates(id) ON DELETE CASCADE,
    draft_id TEXT REFERENCES knowledge_drafts(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (batch_id, candidate_id)
);

CREATE INDEX idx_review_curation_batch_candidates_decision
    ON review_curation_batch_candidates(candidate_id, draft_id, batch_id);

INSERT INTO review_curation_batch_candidates (
    batch_id, candidate_id, draft_id, created_at
)
SELECT candidate.batch_id, candidate.id, candidate.draft_id,
       candidate.created_at
FROM review_question_candidates candidate
JOIN review_question_batches batch ON batch.id = candidate.batch_id
LEFT JOIN knowledge_drafts draft ON draft.id = candidate.draft_id
WHERE draft.run_id IS NOT NULL
  AND batch.run_id IS NOT NULL
  AND draft.run_id = batch.run_id;

INSERT OR IGNORE INTO review_curation_batch_candidates (
    batch_id, candidate_id, draft_id, created_at
)
SELECT finalization.batch_id, candidate.id, candidate.draft_id,
       finalization.updated_at
FROM review_curation_finalizations finalization
JOIN json_each(finalization.candidate_ids_json) committed_candidate
JOIN review_question_candidates candidate
    ON candidate.id = committed_candidate.value
JOIN knowledge_drafts draft
    ON draft.id = candidate.draft_id
    AND draft.run_id = finalization.execution_id
WHERE finalization.state = 'committed';
