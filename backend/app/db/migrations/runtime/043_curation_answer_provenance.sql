ALTER TABLE review_curation_seed_tasks
    ADD COLUMN source_answer TEXT;

ALTER TABLE review_curation_seed_tasks
    ADD COLUMN supplemental_answer TEXT;

ALTER TABLE review_question_candidates
    ADD COLUMN source_answer TEXT;

ALTER TABLE review_question_candidates
    ADD COLUMN supplemental_answer TEXT;
