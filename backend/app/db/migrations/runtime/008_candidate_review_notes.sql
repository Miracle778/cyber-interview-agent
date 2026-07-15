ALTER TABLE review_question_candidates
ADD COLUMN review_note TEXT NOT NULL DEFAULT '';

ALTER TABLE review_question_candidates
ADD COLUMN review_note_updated_at TEXT;
