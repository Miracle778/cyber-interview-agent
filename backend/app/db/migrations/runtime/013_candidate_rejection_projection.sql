ALTER TABLE review_question_candidates
ADD COLUMN rejection_reason TEXT;

ALTER TABLE review_question_candidates
ADD COLUMN rejected_at TEXT;

ALTER TABLE review_question_candidates
ADD COLUMN rejection_action_id TEXT;

UPDATE review_question_candidates
SET status = 'rejected',
    rejection_reason = (
        SELECT resolution.reason
        FROM pending_actions action
        JOIN pending_action_resolutions resolution
          ON resolution.action_id = action.id
        WHERE json_extract(action.payload_json, '$.draftId') = review_question_candidates.draft_id
          AND resolution.status = 'rejected'
        ORDER BY resolution.created_at DESC, resolution.id DESC
        LIMIT 1
    ),
    rejected_at = (
        SELECT COALESCE(action.resolved_at, resolution.created_at)
        FROM pending_actions action
        JOIN pending_action_resolutions resolution
          ON resolution.action_id = action.id
        WHERE json_extract(action.payload_json, '$.draftId') = review_question_candidates.draft_id
          AND resolution.status = 'rejected'
        ORDER BY resolution.created_at DESC, resolution.id DESC
        LIMIT 1
    ),
    rejection_action_id = (
        SELECT action.id
        FROM pending_actions action
        JOIN pending_action_resolutions resolution
          ON resolution.action_id = action.id
        WHERE json_extract(action.payload_json, '$.draftId') = review_question_candidates.draft_id
          AND resolution.status = 'rejected'
        ORDER BY resolution.created_at DESC, resolution.id DESC
        LIMIT 1
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE draft_id IN (
    SELECT id FROM knowledge_drafts WHERE status = 'rejected'
);
