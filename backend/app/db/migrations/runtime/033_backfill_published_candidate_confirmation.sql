UPDATE review_question_candidates
SET confirmation_status = 'confirmed',
    confirmation_version = CASE
        WHEN confirmation_version < 1 THEN 1
        ELSE confirmation_version
    END,
    confirmed_at = COALESCE(confirmed_at, updated_at)
WHERE status = 'published'
  AND (
      confirmation_status <> 'confirmed'
      OR confirmation_version < 1
      OR confirmed_at IS NULL
  );
