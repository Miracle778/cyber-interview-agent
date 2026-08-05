-- Older cleanup runs promoted every provider uncertainty into a blocking user
-- task, including candidates that could not be located or changed no text.
-- Preserve the audit row while making those non-actionable diagnostics non-blocking.
UPDATE interview_transcript_review_issues
SET decision = 'kept', updated_at = CURRENT_TIMESTAMP
WHERE decision = 'pending'
  AND (
    reason LIKE '模型返回的不确定项无法在当前目标正文中唯一定位%'
    OR reason LIKE '模型无法在当前窗口中唯一定位%'
    OR (
      issue_kind = 'uncertain_term'
      AND (
        suggestion IS NULL
        OR trim(suggestion) = trim(excerpt)
      )
    )
  );
